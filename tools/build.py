"""Build reviewable Model Fit plugin archives from one public source tree."""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGINS = ROOT / "plugins"
OUTPUT = ROOT / "dist"
FORBIDDEN_TEXT = ("/Users/", "codex://threads/", "-----BEGIN PRIVATE KEY-----")
FIXTURES = (
    "cases.json",
    "triage-cases.json",
    "replay-answer-cases.json",
    "behavior-calibration.json",
)


def validate_fixtures() -> None:
    directory = ROOT / "evals/model-fit"
    for name in FIXTURES:
        content = (directory / name).read_text()
        json.loads(content)
        if (
            any(value in content for value in FORBIDDEN_TEXT)
            or "data:image/" in content
        ):
            raise ValueError(f"Public eval fixture contains private input: {name}")


def manifest(package: Path) -> dict:
    manifest_path = package / "plugin.json"
    if not manifest_path.exists():
        manifest_path = package / ".codex-plugin/plugin.json"
    value = json.loads(manifest_path.read_text())
    if value.get("$schema") not in (
        None,
        "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
    ):
        raise ValueError("Unsupported plugin manifest schema")
    if value.get("name") != package.name or not isinstance(value.get("version"), str):
        raise ValueError("Plugin identity does not match package directory")
    return value


def release_version() -> str:
    full = manifest(PLUGINS / "model-fit")["version"]
    guidance = manifest(PLUGINS / "model-fit-guidance")["version"]
    if full != guidance:
        raise ValueError("Plugin variants must share one GitHub Release version")
    return full


def source_files(package: Path) -> dict[str, bytes]:
    files = {}
    for path in sorted(package.rglob("*")):
        if any(
            part in {".venv", "__pycache__", "tests", "build", "dist"}
            or part.endswith(".egg-info")
            for part in path.relative_to(package).parts
        ):
            continue
        if path.is_symlink():
            raise ValueError("Plugin package contains a symlink")
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        data = path.read_bytes()
        if path.suffix in {".py", ".md", ".json", ".yaml", ".yml"}:
            text = data.decode("utf-8")
            if any(value in text for value in FORBIDDEN_TEXT):
                raise ValueError(
                    f"Plugin package contains local or private content: {path.name}"
                )
        files[str(path.relative_to(package))] = data
    return files


def full_package() -> tuple[dict, dict[str, bytes]]:
    package = PLUGINS / "model-fit"
    identity = manifest(package)
    files = source_files(package)
    files["LICENSE"] = (ROOT / "LICENSE").read_bytes()
    if (
        "skills/model-fit/SKILL.md" not in files
        or "src/assessment.py" not in files
        or "assets/icon.png" not in files
    ):
        raise ValueError("Full Model Fit package is incomplete")
    return identity, files


def guidance_package() -> tuple[dict, dict[str, bytes]]:
    package = PLUGINS / "model-fit-guidance"
    identity = manifest(package)
    full = source_files(PLUGINS / "model-fit")
    excluded = (
        "src/application/handoff/",
        "src/application/conversation/",
        "src/entrypoints/desktop/",
        "src/infrastructure/handoff/",
        "src/infrastructure/audit/",
        "src/infrastructure/codex/conversation/",
        "src/infrastructure/codex/input/",
    )
    files = {
        name: data
        for name, data in full.items()
        if name.startswith("src/")
        and not name.startswith(excluded)
        and name
        not in {
            "src/api.py",
            "src/infrastructure/codex/identity.py",
            "src/infrastructure/assessment/client.py",
            "src/infrastructure/assessment/relevance.py",
            "src/infrastructure/assessment/relevance.schema.json",
        }
    }
    files.update(source_files(package))
    files["LICENSE"] = (ROOT / "LICENSE").read_bytes()
    rules = full["skills/model-fit/SKILL.md"].decode().split("\n## Ответ\n", 1)[0]
    files["skills/model-fit/SKILL.md"] = (
        rules
        + "\n## Ответ\n\nВерни результат явной оценки и его обоснование. Этот вариант не применяет рекомендацию к текущему чату.\n\n## Явная оценка через CLI\n\nДля явного вызова оценки используй установленный CLI с JSON-вводом по [README пакета](../../README.md). Отсутствующие данные профиля запроси у пользователя; не угадывай их. Оценка возвращает рекомендацию и сама не меняет модель.\n"
    ).encode()
    files["skills/model-fit/agents/openai.yaml"] = full[
        "skills/model-fit/agents/openai.yaml"
    ]
    files["assets/icon.png"] = full["assets/icon.png"]
    packages = sorted(
        "model_fit"
        + ("." + name[4:-12].replace("/", ".") if name != "src/__init__.py" else "")
        for name in files
        if name.startswith("src/") and name.endswith("/__init__.py")
    )
    config = full["pyproject.toml"].decode()
    import re

    config = re.sub(r"packages = \[.*?\]", "packages = " + json.dumps(packages), config)
    files["pyproject.toml"] = config.encode()
    files["uv.lock"] = full["uv.lock"]
    if any(
        name.startswith("hooks/") or name.startswith("src/entrypoints/desktop/")
        for name in files
    ):
        raise ValueError("CLI package contains automatic integration")
    return identity, files


def write_archive(identity: dict, files: dict[str, bytes], output: Path) -> Path:
    name = identity["name"]
    archive = output / f"{name}-{identity['version']}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as package:
        for relative, data in sorted(files.items()):
            info = zipfile.ZipInfo(f"{name}/{relative}", (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            package.writestr(info, data)
    with zipfile.ZipFile(archive) as package:
        names = package.namelist()
        if len(names) != len(set(names)) or len(names) != len(files):
            raise ValueError("Archive has duplicate or missing members")
        if any(not path.startswith(name + "/") for path in names):
            raise ValueError("Archive contains another package")
        manifest_name = (
            "plugin.json" if "plugin.json" in files else ".codex-plugin/plugin.json"
        )
        if json.loads(package.read(f"{name}/{manifest_name}"))["name"] != name:
            raise ValueError("Archived manifest does not match package")
    return archive


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--version", action="store_true", help="print release version")
    args = parser.parse_args()
    version = release_version()
    if args.version:
        print(version)
        return 0
    destination = args.output.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    validate_fixtures()
    for identity, files in (full_package(), guidance_package()):
        archive = write_archive(identity, files, destination)
        print(f"{archive}: {len(files)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Build reviewable Model Fit plugin archives from one public source tree."""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGINS = ROOT / "plugins"
OUTPUT = ROOT / "dist"
GUIDANCE_BOUNDARY = "\n## Локальный hook\n"
FORBIDDEN_TEXT = ("/Users/", "codex://threads/", "-----BEGIN PRIVATE KEY-----")
FIXTURES = (
    "cases.json",
    "triage-cases.json",
    "answer-cases.json",
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
    cases = json.loads((directory / "cases.json").read_text())
    if not all(case.get("source", "").startswith("Synthetic") for case in cases):
        raise ValueError("Public cases must use synthetic provenance")


def manifest(package: Path) -> dict:
    value = json.loads((package / "plugin.json").read_text())
    if (
        value.get("$schema")
        != "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
    ):
        raise ValueError("Unsupported plugin manifest schema")
    if value.get("name") != package.name or not isinstance(value.get("version"), str):
        raise ValueError("Plugin identity does not match package directory")
    return value


def source_files(package: Path) -> dict[str, bytes]:
    files = {}
    for path in sorted(package.rglob("*")):
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
        or "skills/model-fit/scripts/hook.py" not in files
        or "assets/icon.png" not in files
    ):
        raise ValueError("Full Model Fit package is incomplete")
    return identity, files


def guidance_package() -> tuple[dict, dict[str, bytes]]:
    package = PLUGINS / "model-fit-guidance"
    identity = manifest(package)
    source = (PLUGINS / "model-fit/skills/model-fit/SKILL.md").read_text()
    if source.count(GUIDANCE_BOUNDARY) != 1:
        raise ValueError("Model Fit guidance boundary is missing or ambiguous")
    guidance = source.split(GUIDANCE_BOUNDARY, 1)[0].rstrip() + "\n"
    if "references/hook.md" in guidance or "desktop_auto_switch" in guidance:
        raise ValueError("Guidance package refers to the omitted hook")
    files = source_files(package)
    files["LICENSE"] = (ROOT / "LICENSE").read_bytes()
    files["skills/model-fit/SKILL.md"] = guidance.encode()
    full_agents = PLUGINS / "model-fit/skills/model-fit/agents/openai.yaml"
    if full_agents.is_file():
        files["skills/model-fit/agents/openai.yaml"] = full_agents.read_bytes()
    files["assets/icon.png"] = (PLUGINS / "model-fit/assets/icon.png").read_bytes()
    if any("/hooks/" in path or "/scripts/" in path for path in files):
        raise ValueError("Guidance package contains executable hooks or scripts")
    if "assets/icon.png" not in files:
        raise ValueError("Guidance package is missing its icon")
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
        if json.loads(package.read(f"{name}/plugin.json"))["name"] != name:
            raise ValueError("Archived manifest does not match package")
    return archive


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    destination = args.output.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    validate_fixtures()
    for identity, files in (full_package(), guidance_package()):
        archive = write_archive(identity, files, destination)
        print(f"{archive}: {len(files)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

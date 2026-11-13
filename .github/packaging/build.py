"""Build the two Vector Prime distributions from their file inventories."""

import argparse
import json
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[2]
PACKAGING = Path(".github/packaging")
MARKETPLACE_MANIFEST = Path(".codex-plugin/plugin.json")
GUIDANCE_MANIFEST = PACKAGING / "directory/plugin.json"
DISTRIBUTIONS = {
    "vector-prime": PACKAGING / "marketplace.files",
    "vector-prime-guidance": PACKAGING / "directory/files",
}


def update_version(version: str) -> None:
    subprocess.run(["uv", "version", "--no-sync", version], cwd=ROOT, check=True)
    subprocess.run(["uv", "lock", "--project", "evals/model-fit"], cwd=ROOT, check=True)
    for manifest in (MARKETPLACE_MANIFEST, GUIDANCE_MANIFEST):
        path = ROOT / manifest
        metadata = json.loads(path.read_text(encoding="utf-8"))
        metadata["version"] = version
        path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


def build(name: str) -> None:
    inventory = (ROOT / DISTRIBUTIONS[name]).read_text(encoding="utf-8").splitlines()
    files = set()
    for entry in inventory:
        path = ROOT / entry
        candidates = path.rglob("*") if path.is_dir() else (path,)
        for candidate in candidates:
            relative = candidate.relative_to(ROOT)
            if (
                candidate.is_file()
                and candidate.resolve() == candidate
                and "__pycache__" not in relative.parts
                and candidate.suffix != ".pyc"
            ):
                files.add(relative)

    destination = ROOT / "dist" / f"{name}.zip"
    destination.parent.mkdir(exist_ok=True)
    with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
        for file in sorted(files):
            archive.write(ROOT / file, Path(name) / file)
        if name == "vector-prime-guidance":
            archive.write(ROOT / GUIDANCE_MANIFEST, f"{name}/plugin.json")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version")
    parser.add_argument("--distribution", choices=DISTRIBUTIONS)
    args = parser.parse_args()
    if args.version:
        update_version(args.version)
    for name in (args.distribution,) if args.distribution else DISTRIBUTIONS:
        build(name)


if __name__ == "__main__":
    main()

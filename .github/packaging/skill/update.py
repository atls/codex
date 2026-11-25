"""Install the published Model Fit policy and update the checked-in distribution."""

import argparse
import json
import re
import subprocess
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
ROOT = PACKAGE_DIR.parents[2]
PACKAGE = "@atls/skill-model-fit"
POLICY = "references/assessment-policy.md"


def version(value: str) -> tuple[int, ...]:
    if not re.fullmatch(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)", value):
        raise ValueError("Expected an exact Model Fit package version")
    return tuple(map(int, value.split(".")))


def update(tag: str) -> None:
    prefix = f"{PACKAGE}@"
    if not tag.startswith(prefix):
        raise ValueError("Expected a Model Fit package release tag")
    requested = tag.removeprefix(prefix)
    version(requested)
    selected = json.loads(
        subprocess.check_output(
            ["npm", "view", PACKAGE, "version", "--json"], cwd=PACKAGE_DIR, text=True
        )
    )
    if version(selected) < version(requested):
        raise ValueError("The registry has not published the dispatched version")
    tag = prefix + selected
    path = PACKAGE_DIR / "package.json"
    current = json.loads(path.read_text())["dependencies"][PACKAGE]
    if version(selected) < version(current):
        return
    subprocess.run(
        [
            "npm",
            "install",
            "--package-lock-only",
            "--save-exact",
            "--ignore-scripts",
            "--no-audit",
            "--no-fund",
            tag,
        ],
        cwd=PACKAGE_DIR,
        check=True,
    )
    subprocess.run(
        ["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"],
        cwd=PACKAGE_DIR,
        check=True,
    )
    installed = PACKAGE_DIR / "node_modules" / PACKAGE
    manifest = json.loads((installed / "package.json").read_text())
    if manifest["name"] != PACKAGE or manifest["version"] != selected:
        raise ValueError("Installed package differs from the requested release")
    (ROOT / "skills/model-fit" / POLICY).write_bytes((installed / POLICY).read_bytes())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag")
    update(parser.parse_args().tag)

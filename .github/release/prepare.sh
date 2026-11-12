#!/usr/bin/env bash
set -euo pipefail

version=$1
python3 - "$version" <<'PY'
import json
import sys
from pathlib import Path
import re

version = sys.argv[1]
for name in (".codex-plugin/plugin.json", ".github/packaging/directory/plugin.json"):
    path = Path(name)
    manifest = json.loads(path.read_text())
    manifest["version"] = version
    path.write_text(json.dumps(manifest, indent=2) + "\n")

path = Path("pyproject.toml")
text, count = re.subn(r'(?m)^version = "[^"]+"$', f'version = "{version}"', path.read_text())
if count != 1:
    raise ValueError("Expected exactly one Python project version")
path.write_text(text)
PY
uv lock
uv lock --project evals/model-fit
bash .github/packaging/archive.sh vector-prime .github/packaging/marketplace.files
bash .github/packaging/archive.sh vector-prime-guidance .github/packaging/directory/files .github/packaging/directory/plugin.json
unzip -tq dist/vector-prime.zip
unzip -tq dist/vector-prime-guidance.zip

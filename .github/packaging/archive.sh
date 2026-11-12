#!/usr/bin/env bash
set -euo pipefail

name=$1
inventory=$2
manifest=${3:-}

mkdir -p dist
rsync -r --no-links --exclude __pycache__ --exclude '*.pyc' \
  --files-from="$inventory" ./ "dist/$name/"
if [[ -n "$manifest" ]]; then
  cp "$manifest" "dist/$name/plugin.json"
fi
(cd dist && zip -qr "$name.zip" "$name")

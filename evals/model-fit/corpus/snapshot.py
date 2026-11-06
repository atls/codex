"""Integrity of source and disposable read-only workspace snapshots."""

import hashlib
import json
from pathlib import Path


def snapshot_hash(directory):
    rows = []

    def visit(current, relative=""):
        for path in sorted(
            Path(current).iterdir(),
            key=lambda entry: entry.name.encode("utf-16-be", "surrogatepass"),
        ):
            if path.name == ".git":
                continue
            identity = f"{relative}/{path.name}" if relative else path.name
            if path.is_symlink():
                raise ValueError("Snapshot contains a symlink")
            if path.is_dir():
                visit(path, identity)
            elif path.is_file():
                rows.append([identity, hashlib.sha256(path.read_bytes()).hexdigest()])
            else:
                raise ValueError("Snapshot contains an unsupported file")

    visit(directory)
    return hashlib.sha256(
        json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()

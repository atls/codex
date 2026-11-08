"Hash and inspect native input without reconstructing it."

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any


def prompt_digest(prompt: str) -> str:
    return sha256(prompt.encode()).hexdigest()


def input_text(content: list[dict[str, Any]]) -> str:
    return "\n".join((item["text"] for item in content if item.get("type") == "text"))


def hook_prompt(content: list[dict[str, Any]]) -> str:
    return "".join((item["text"] for item in content if item.get("type") == "text"))


def input_digest(content: list[dict[str, Any]]) -> str:
    return sha256(
        json.dumps(content, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()

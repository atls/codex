"""Hash and inspect native input without reconstructing it."""

from __future__ import annotations

import json
from hashlib import sha256
from collections.abc import Mapping, Sequence

from model_fit.native_input.types.json import JsonValue


def prompt_digest(prompt: str) -> str:
    return sha256(prompt.encode()).hexdigest()


def _text(item: Mapping[str, JsonValue]) -> str:
    text = item["text"]
    if not isinstance(text, str):
        raise TypeError("Native text content must be a string")
    return text


def input_text(content: Sequence[Mapping[str, JsonValue]]) -> str:
    return "\n".join(_text(item) for item in content if item.get("type") == "text")


def hook_prompt(content: Sequence[Mapping[str, JsonValue]]) -> str:
    return "".join(_text(item) for item in content if item.get("type") == "text")


def input_digest(content: Sequence[Mapping[str, JsonValue]]) -> str:
    return sha256(
        json.dumps(content, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()

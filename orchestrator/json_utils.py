from __future__ import annotations

import json
from typing import Any


class ModelOutputError(ValueError):
    pass


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = _strip_markdown_fence(text.strip())
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        value = json.loads(_first_json_object(cleaned))
    if not isinstance(value, dict):
        raise ModelOutputError("Expected a JSON object from the model.")
    return value


def dumps_compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def _strip_markdown_fence(text: str) -> str:
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if len(lines) >= 3 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return text


def _first_json_object(text: str) -> str:
    start = text.find("{")
    if start < 0:
        raise ModelOutputError("Model response did not contain a JSON object.")

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_string:
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise ModelOutputError("Model response contained incomplete JSON.")

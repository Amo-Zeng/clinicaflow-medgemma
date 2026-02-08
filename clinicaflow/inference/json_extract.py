from __future__ import annotations

import json


class JsonExtractError(ValueError):
    pass


def extract_first_json_object(text: str) -> dict:
    """Extract the first JSON object found in a string.

    Models sometimes wrap JSON in prose or code fences. This helper tries to
    robustly recover a JSON object without additional dependencies.
    """
    text = text.strip()
    if not text:
        raise JsonExtractError("Empty text")

    # Fast path: direct JSON
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
        raise JsonExtractError("Top-level JSON is not an object")
    except json.JSONDecodeError:
        pass

    # Strip common Markdown fences
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].startswith("```"):
            candidate = "\n".join(lines[1:-1]).strip()
            return extract_first_json_object(candidate)

    start = text.find("{")
    if start == -1:
        raise JsonExtractError("No JSON object start found")

    # Greedy scan: find a closing brace that yields valid JSON.
    for end in range(len(text) - 1, start, -1):
        if text[end] != "}":
            continue
        candidate = text[start : end + 1]
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value

    raise JsonExtractError("Failed to extract a valid JSON object")


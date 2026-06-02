"""LLM output parsing utilities."""

from __future__ import annotations

import json


def load_json_object(content: str) -> dict:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    # Search for the first balanced JSON object
    start = content.find("{")
    if start == -1:
        raise ValueError("no JSON object found in output")
    depth = 0
    for i in range(start, len(content)):
        if content[i] == "{":
            depth += 1
        elif content[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(content[start : i + 1])
    raise ValueError("unbalanced JSON braces in output")

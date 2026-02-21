from __future__ import annotations

import json
from datetime import datetime
from typing import Any


def json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    return value


def json_dumps(value: Any) -> str:
    return json.dumps(json_safe(value), sort_keys=True)


def parse_json_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def extract_path_value(payload: Any, path: str) -> Any:
    cleaned_path = (path or "").strip()
    if not cleaned_path:
        return None
    current = payload
    for token in cleaned_path.split("."):
        segment = token.strip()
        if not segment:
            continue
        if isinstance(current, dict):
            if segment not in current:
                return None
            current = current[segment]
            continue
        if isinstance(current, list):
            if not segment.isdigit():
                return None
            index = int(segment)
            if index < 0 or index >= len(current):
                return None
            current = current[index]
            continue
        return None
    return current


def parse_optional_int(
    value: Any,
    *,
    default: int = 0,
    minimum: int | None = None,
) -> int:
    parsed = default
    if isinstance(value, bool):
        parsed = int(value)
    elif isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        raw = value.strip()
        if raw:
            try:
                parsed = int(raw)
            except ValueError:
                parsed = default
    if minimum is not None and parsed < minimum:
        return minimum
    return parsed


def coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


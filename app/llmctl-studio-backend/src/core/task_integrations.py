from __future__ import annotations

import json
from collections.abc import Iterable

TASK_INTEGRATION_OPTIONS = (
    {
        "key": "github",
        "label": "GitHub",
        "description": "Use GitHub settings and run repo checkout in Integration stage.",
    },
    {
        "key": "jira",
        "label": "Jira",
        "description": "Include Jira board/project settings in task context.",
    },
    {
        "key": "confluence",
        "label": "Confluence",
        "description": "Include Confluence site/space settings in task context.",
    },
    {
        "key": "chroma",
        "label": "ChromaDB",
        "description": "Include Chroma host/port/ssl settings in task context.",
    },
)
TASK_INTEGRATION_KEYS = frozenset(
    str(option["key"]).strip().lower()
    for option in TASK_INTEGRATION_OPTIONS
    if option.get("key")
)
TASK_INTEGRATION_LABELS = {
    str(option["key"]).strip().lower(): str(option.get("label") or option["key"])
    for option in TASK_INTEGRATION_OPTIONS
    if option.get("key")
}


def validate_task_integration_keys(
    values: Iterable[str] | None,
) -> tuple[list[str], list[str]]:
    if values is None:
        return [], []
    valid: list[str] = []
    invalid: list[str] = []
    seen_valid: set[str] = set()
    seen_invalid: set[str] = set()
    for value in values:
        key = str(value or "").strip().lower()
        if not key:
            continue
        if key in TASK_INTEGRATION_KEYS:
            if key not in seen_valid:
                valid.append(key)
                seen_valid.add(key)
            continue
        if key not in seen_invalid:
            invalid.append(key)
            seen_invalid.add(key)
    return valid, invalid


def normalize_task_integration_keys(values: Iterable[str] | None) -> list[str]:
    valid, _ = validate_task_integration_keys(values)
    return sorted(valid)


def serialize_task_integration_keys(values: Iterable[str] | None) -> str:
    return json.dumps(normalize_task_integration_keys(values), sort_keys=True)


def parse_task_integration_keys(raw: str | None) -> set[str] | None:
    if raw is None:
        return None
    stripped = str(raw).strip()
    if not stripped:
        return None
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return set()
    if payload is None:
        return None
    if not isinstance(payload, list):
        return set()
    valid, _ = validate_task_integration_keys(payload)
    return set(valid)


def is_task_integration_selected(
    key: str,
    selected_keys: set[str] | None,
) -> bool:
    normalized = str(key or "").strip().lower()
    if normalized not in TASK_INTEGRATION_KEYS:
        return False
    if selected_keys is None:
        return True
    return normalized in selected_keys

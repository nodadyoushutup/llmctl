from __future__ import annotations

import json

from core.models import FLOWCHART_NODE_TYPE_TASK

STAGE_STATUS_CLASSES = {
    "pending": "status-queued",
    "running": "status-running",
    "completed": "status-success",
    "failed": "status-failed",
    "skipped": "status-idle",
}


def format_bytes(value: int | None) -> str:
    if value is None:
        return "-"
    if value < 1024:
        return f"{value} B"
    size = float(value)
    for unit in ("KB", "MB", "GB", "TB"):
        size /= 1024
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
    return f"{size:.1f} TB"


def parse_stage_logs(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key): str(value) for key, value in payload.items() if value is not None}


def task_output_for_display(raw: str | None) -> str:
    if not raw:
        return ""
    stripped = raw.strip()
    if not stripped.startswith("{"):
        return raw
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return raw
    if not isinstance(payload, dict):
        return raw
    if str(payload.get("node_type") or "").strip() != FLOWCHART_NODE_TYPE_TASK:
        return raw

    raw_output = payload.get("raw_output")
    if isinstance(raw_output, str) and raw_output.strip():
        return raw_output

    structured_output = payload.get("structured_output")
    if isinstance(structured_output, str) and structured_output.strip():
        return structured_output
    if isinstance(structured_output, dict):
        text_value = structured_output.get("text")
        if isinstance(text_value, str) and text_value.strip():
            return text_value

    return raw


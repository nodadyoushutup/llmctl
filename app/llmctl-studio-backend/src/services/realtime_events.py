from __future__ import annotations

import uuid
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from web.realtime import REALTIME_NAMESPACE, emit_realtime

EVENT_CONTRACT_VERSION = "v1"

_sequence_lock = Lock()
_sequence_counters: dict[str, int] = {}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _clean_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _coerce_entity_id(value: int | str | None) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _next_sequence(stream_key: str) -> int:
    with _sequence_lock:
        current = int(_sequence_counters.get(stream_key, 0)) + 1
        _sequence_counters[stream_key] = current
        return current


def combine_room_keys(*room_groups: list[str] | tuple[str, ...] | None) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for group in room_groups:
        if not group:
            continue
        for raw_room in group:
            room = str(raw_room or "").strip()
            if not room or room in seen:
                continue
            seen.add(room)
            unique.append(room)
    return unique


def room_key(prefix: str, value: int | str | None) -> str | None:
    suffix = _coerce_entity_id(value)
    if not suffix:
        return None
    return f"{prefix}:{suffix}"


def task_scope_rooms(
    *,
    task_id: int | str | None,
    run_id: int | str | None = None,
    flowchart_id: int | str | None = None,
    flowchart_run_id: int | str | None = None,
    flowchart_node_id: int | str | None = None,
) -> list[str]:
    return combine_room_keys(
        [room for room in [room_key("task", task_id)] if room],
        [room for room in [room_key("run", run_id)] if room],
        [room for room in [room_key("flowchart", flowchart_id)] if room],
        [room for room in [room_key("flowchart_run", flowchart_run_id)] if room],
        [room for room in [room_key("flowchart_node", flowchart_node_id)] if room],
    )


def flowchart_scope_rooms(
    *,
    flowchart_id: int | str | None,
    flowchart_run_id: int | str | None = None,
    flowchart_node_id: int | str | None = None,
) -> list[str]:
    return combine_room_keys(
        [room for room in [room_key("flowchart", flowchart_id)] if room],
        [room for room in [room_key("flowchart_run", flowchart_run_id)] if room],
        [room for room in [room_key("flowchart_node", flowchart_node_id)] if room],
    )


def thread_scope_rooms(*, thread_id: int | str | None) -> list[str]:
    return combine_room_keys([room for room in [room_key("thread", thread_id)] if room])


def download_scope_rooms(*, job_id: int | str | None) -> list[str]:
    return combine_room_keys(
        [room for room in [room_key("download_job", job_id)] if room]
    )


def normalize_runtime_metadata(runtime: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(runtime, dict):
        return None
    return {
        "selected_provider": _clean_text(runtime.get("selected_provider")),
        "final_provider": _clean_text(runtime.get("final_provider")),
        "provider_dispatch_id": _clean_text(runtime.get("provider_dispatch_id")),
        "workspace_identity": _clean_text(runtime.get("workspace_identity")),
        "dispatch_status": _clean_text(runtime.get("dispatch_status")),
        "execution_mode": _clean_text(runtime.get("execution_mode")),
        "fallback_attempted": _as_bool(runtime.get("fallback_attempted"), default=False),
        "fallback_reason": _clean_text(runtime.get("fallback_reason")),
        "dispatch_uncertain": _as_bool(runtime.get("dispatch_uncertain"), default=False),
        "api_failure_category": _clean_text(runtime.get("api_failure_category")),
        "cli_fallback_used": _as_bool(runtime.get("cli_fallback_used"), default=False),
        "cli_preflight_passed": (
            None
            if runtime.get("cli_preflight_passed") is None
            else _as_bool(runtime.get("cli_preflight_passed"), default=False)
        ),
    }


def build_event_envelope(
    *,
    event_type: str,
    entity_kind: str,
    entity_id: int | str | None,
    room_keys: list[str] | None = None,
    payload: dict[str, Any] | None = None,
    runtime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event_id = str(uuid.uuid4())
    normalized_entity_id = _coerce_entity_id(entity_id)
    stream_key = (
        f"{entity_kind}:{normalized_entity_id}" if normalized_entity_id else f"{event_type}:global"
    )
    sequence = _next_sequence(stream_key)
    normalized_rooms = combine_room_keys(room_keys or [])
    return {
        "contract_version": EVENT_CONTRACT_VERSION,
        "event_id": event_id,
        "idempotency_key": event_id,
        "sequence": sequence,
        "sequence_stream": stream_key,
        "emitted_at": _utcnow_iso(),
        "event_type": str(event_type),
        "entity_kind": str(entity_kind),
        "entity_id": normalized_entity_id,
        "room_keys": normalized_rooms,
        "runtime": normalize_runtime_metadata(runtime),
        "payload": payload or {},
    }


def emit_contract_event(
    *,
    event_type: str,
    entity_kind: str,
    entity_id: int | str | None,
    room_keys: list[str] | None = None,
    payload: dict[str, Any] | None = None,
    runtime: dict[str, Any] | None = None,
    namespace: str = REALTIME_NAMESPACE,
) -> dict[str, Any]:
    envelope = build_event_envelope(
        event_type=event_type,
        entity_kind=entity_kind,
        entity_id=entity_id,
        room_keys=room_keys,
        payload=payload,
        runtime=runtime,
    )
    if envelope["room_keys"]:
        for room in envelope["room_keys"]:
            emit_realtime(event_type, envelope, room=room, namespace=namespace)
    else:
        emit_realtime(event_type, envelope, namespace=namespace)
    return envelope

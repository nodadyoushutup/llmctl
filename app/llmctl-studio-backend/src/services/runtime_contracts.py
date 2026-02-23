from __future__ import annotations

import re
from typing import Any

from core.models import (
    FLOWCHART_NODE_TYPE_DECISION,
    FLOWCHART_NODE_TYPE_MEMORY,
    FLOWCHART_NODE_TYPE_MILESTONE,
    FLOWCHART_NODE_TYPE_PLAN,
    NODE_ARTIFACT_TYPE_DECISION,
    NODE_ARTIFACT_TYPE_END,
    NODE_ARTIFACT_TYPE_FLOWCHART,
    NODE_ARTIFACT_TYPE_MEMORY,
    NODE_ARTIFACT_TYPE_MILESTONE,
    NODE_ARTIFACT_TYPE_PLAN,
    NODE_ARTIFACT_TYPE_RAG,
    NODE_ARTIFACT_TYPE_START,
    NODE_ARTIFACT_TYPE_TASK,
)

RUNTIME_CONTRACT_VERSION = "v1"
NODE_OUTPUT_CONTRACT_VERSION = RUNTIME_CONTRACT_VERSION
ROUTING_OUTPUT_CONTRACT_VERSION = RUNTIME_CONTRACT_VERSION
NODE_ARTIFACT_CONTRACT_VERSION = RUNTIME_CONTRACT_VERSION
NODE_ARTIFACT_PAYLOAD_VERSION = 1
API_ERROR_CONTRACT_VERSION = RUNTIME_CONTRACT_VERSION
SOCKET_EVENT_CONTRACT_VERSION = RUNTIME_CONTRACT_VERSION

SOCKET_EVENT_TYPE_PATTERN = re.compile(r"^[a-z0-9_]+:[a-z0-9_]+:[a-z0-9_]+$")

NODE_OUTPUT_BASE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["node_type"],
    "properties": {
        "node_type": {"type": "string"},
    },
    "additionalProperties": True,
}

ROUTING_OUTPUT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "route_key": {"type": "string"},
        "terminate_run": {"type": "boolean"},
        "matched_connector_ids": {"type": "array", "items": {"type": "string"}},
        "evaluations": {"type": "array", "items": {"type": "object"}},
        "no_match": {"type": "boolean"},
    },
    "additionalProperties": True,
}

SPECIAL_NODE_OUTPUT_JSON_SCHEMAS: dict[str, dict[str, Any]] = {
    FLOWCHART_NODE_TYPE_DECISION: {
        "required": ["node_type", "matched_connector_ids", "evaluations", "no_match"]
    },
    FLOWCHART_NODE_TYPE_MEMORY: {
        "required": ["node_type", "action", "action_results"]
    },
    FLOWCHART_NODE_TYPE_MILESTONE: {
        "required": ["node_type", "action", "action_results"]
    },
    FLOWCHART_NODE_TYPE_PLAN: {
        "required": ["node_type", "mode", "store_mode", "action_results"]
    },
}

NODE_ARTIFACT_JSON_SCHEMAS: dict[str, dict[str, Any]] = {
    NODE_ARTIFACT_TYPE_DECISION: {
        "required": ["matched_connector_ids", "evaluations", "no_match", "routing_state"]
    },
    NODE_ARTIFACT_TYPE_END: {
        "required": ["node_type", "input_context", "output_state", "routing_state"]
    },
    NODE_ARTIFACT_TYPE_FLOWCHART: {
        "required": ["node_type", "input_context", "output_state", "routing_state"]
    },
    NODE_ARTIFACT_TYPE_MEMORY: {
        "required": ["action", "action_results", "routing_state"]
    },
    NODE_ARTIFACT_TYPE_MILESTONE: {
        "required": ["action", "action_results", "milestone", "routing_state"]
    },
    NODE_ARTIFACT_TYPE_PLAN: {
        "required": ["mode", "store_mode", "action_results", "plan", "routing_state"]
    },
    NODE_ARTIFACT_TYPE_RAG: {
        "required": ["node_type", "input_context", "output_state", "routing_state"]
    },
    NODE_ARTIFACT_TYPE_START: {
        "required": ["node_type", "input_context", "output_state", "routing_state"]
    },
    NODE_ARTIFACT_TYPE_TASK: {
        "required": ["node_type", "input_context", "output_state", "routing_state"]
    },
}

API_ERROR_ENVELOPE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["ok", "error"],
    "properties": {
        "ok": {"type": "boolean"},
        "error": {
            "type": "object",
            "required": ["contract_version", "code", "message", "details", "request_id"],
        },
        "correlation_id": {"type": "string"},
    },
}

SOCKET_EVENT_ENVELOPE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "contract_version",
        "event_id",
        "idempotency_key",
        "event_type",
        "entity_kind",
        "entity_id",
        "request_id",
        "payload",
    ],
}


def _ensure_mapping(value: Any, *, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object.")
    return value


def _ensure_required_keys(
    payload: dict[str, Any],
    *,
    required: tuple[str, ...],
    name: str,
) -> None:
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError(f"{name} is missing required keys: {', '.join(missing)}.")


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            result.append(text)
    return result


def canonical_socket_event_type(event_type: str) -> str:
    raw = str(event_type or "").strip().lower()
    if not raw:
        raise ValueError("event_type is required.")
    delimiter = ":" if ":" in raw else "."
    parts = [part.strip() for part in raw.split(delimiter) if part.strip()]
    if len(parts) < 3:
        raise ValueError(
            "event_type must have at least domain/entity/action segments."
        )

    def _norm(part: str) -> str:
        cleaned = re.sub(r"[^a-z0-9_]+", "_", part.strip().lower()).strip("_")
        return cleaned or "unknown"

    domain = _norm(parts[0])
    entity = _norm(parts[1])
    action = _norm("_".join(parts[2:]))
    canonical = f"{domain}:{entity}:{action}"
    if not SOCKET_EVENT_TYPE_PATTERN.match(canonical):
        raise ValueError(
            f"event_type '{event_type}' cannot be normalized to domain:entity:action."
        )
    return canonical


def validate_node_output_contract(
    output_state: dict[str, Any],
    *,
    expected_node_type: str | None = None,
) -> None:
    payload = _ensure_mapping(output_state, name="output_state")
    node_type = str(payload.get("node_type") or "").strip().lower()
    if not node_type:
        raise ValueError("output_state.node_type is required.")
    if expected_node_type and node_type != str(expected_node_type).strip().lower():
        raise ValueError(
            f"output_state.node_type must be '{expected_node_type}', got '{node_type}'."
        )


def validate_routing_output_contract(routing_state: dict[str, Any]) -> None:
    payload = _ensure_mapping(routing_state, name="routing_state")
    if "route_key" in payload:
        route_key = str(payload.get("route_key") or "").strip()
        if not route_key:
            raise ValueError("routing_state.route_key must be a non-empty string.")
    if "terminate_run" in payload and not isinstance(payload.get("terminate_run"), bool):
        raise ValueError("routing_state.terminate_run must be boolean.")
    if "matched_connector_ids" in payload and not isinstance(
        payload.get("matched_connector_ids"), list
    ):
        raise ValueError("routing_state.matched_connector_ids must be an array.")
    if "evaluations" in payload and not isinstance(payload.get("evaluations"), list):
        raise ValueError("routing_state.evaluations must be an array.")
    if "no_match" in payload and not isinstance(payload.get("no_match"), bool):
        raise ValueError("routing_state.no_match must be boolean.")


def validate_special_node_output_contract(
    node_type: str,
    output_state: dict[str, Any],
    routing_state: dict[str, Any],
) -> None:
    normalized_type = str(node_type or "").strip().lower()
    validate_node_output_contract(output_state, expected_node_type=normalized_type)
    validate_routing_output_contract(routing_state)

    schema = SPECIAL_NODE_OUTPUT_JSON_SCHEMAS.get(normalized_type)
    if schema:
        required = tuple(str(item) for item in schema.get("required", []))
        if required:
            _ensure_required_keys(output_state, required=required, name="output_state")

    if normalized_type == FLOWCHART_NODE_TYPE_DECISION:
        if not isinstance(output_state.get("evaluations"), list):
            raise ValueError("Decision output_state.evaluations must be an array.")
        if not isinstance(output_state.get("no_match"), bool):
            raise ValueError("Decision output_state.no_match must be boolean.")
        connector_ids = _string_list(output_state.get("matched_connector_ids"))
        if connector_ids != list(output_state.get("matched_connector_ids") or []):
            raise ValueError(
                "Decision output_state.matched_connector_ids must contain non-empty strings."
            )
        routing_connector_ids = _string_list(routing_state.get("matched_connector_ids"))
        if routing_connector_ids != list(routing_state.get("matched_connector_ids") or []):
            raise ValueError(
                "Decision routing_state.matched_connector_ids must contain non-empty strings."
            )
    elif normalized_type in {
        FLOWCHART_NODE_TYPE_MILESTONE,
        FLOWCHART_NODE_TYPE_MEMORY,
    }:
        action = str(output_state.get("action") or "").strip()
        if not action:
            raise ValueError(f"{normalized_type} output_state.action is required.")
        if not isinstance(output_state.get("action_results"), list):
            raise ValueError(
                f"{normalized_type} output_state.action_results must be an array."
            )
    elif normalized_type == FLOWCHART_NODE_TYPE_PLAN:
        mode = str(output_state.get("mode") or "").strip()
        if not mode:
            raise ValueError("plan output_state.mode is required.")
        store_mode = str(output_state.get("store_mode") or "").strip()
        if not store_mode:
            raise ValueError("plan output_state.store_mode is required.")
        if not isinstance(output_state.get("action_results"), list):
            raise ValueError("plan output_state.action_results must be an array.")


def validate_node_artifact_payload_contract(
    artifact_type: str,
    artifact_payload: dict[str, Any],
) -> None:
    normalized_artifact_type = str(artifact_type or "").strip().lower()
    payload = _ensure_mapping(artifact_payload, name="artifact_payload")
    schema = NODE_ARTIFACT_JSON_SCHEMAS.get(normalized_artifact_type)
    if schema:
        required = tuple(str(item) for item in schema.get("required", []))
        if required:
            _ensure_required_keys(payload, required=required, name="artifact_payload")
    routing_payload = payload.get("routing_state")
    if not isinstance(routing_payload, dict):
        raise ValueError("artifact_payload.routing_state must be a JSON object.")
    validate_routing_output_contract(routing_payload)


def resolve_node_degraded_markers(
    runtime_payload: dict[str, Any] | None,
) -> tuple[bool, str | None]:
    if not isinstance(runtime_payload, dict):
        return False, None
    fallback_attempted = bool(runtime_payload.get("fallback_attempted"))
    dispatch_uncertain = bool(runtime_payload.get("dispatch_uncertain"))
    cli_fallback_used = bool(runtime_payload.get("cli_fallback_used"))
    deterministic_fallback_used = bool(runtime_payload.get("deterministic_fallback_used"))
    deterministic_execution_status = str(
        runtime_payload.get("deterministic_execution_status") or ""
    ).strip()
    fallback_reason = str(runtime_payload.get("fallback_reason") or "").strip()
    api_failure_category = str(runtime_payload.get("api_failure_category") or "").strip()
    degraded = bool(
        fallback_attempted
        or dispatch_uncertain
        or cli_fallback_used
        or deterministic_fallback_used
        or deterministic_execution_status == "success_with_warning"
        or fallback_reason
        or api_failure_category
    )
    if not degraded:
        return False, None
    if fallback_reason:
        return True, fallback_reason
    if api_failure_category:
        return True, api_failure_category
    if dispatch_uncertain:
        return True, "dispatch_uncertain"
    if cli_fallback_used:
        return True, "cli_fallback_used"
    if deterministic_fallback_used:
        return True, "deterministic_fallback_used"
    if deterministic_execution_status == "success_with_warning":
        return True, "success_with_warning"
    return True, "degraded"


def build_node_run_idempotency_key(
    *,
    flowchart_run_id: int,
    flowchart_node_id: int,
    execution_index: int,
) -> str:
    return (
        f"flowchart_run:{int(flowchart_run_id)}:"
        f"flowchart_node:{int(flowchart_node_id)}:"
        f"execution:{int(execution_index)}"
    )


def build_node_artifact_idempotency_key(
    *,
    flowchart_run_id: int,
    flowchart_run_node_id: int,
    artifact_type: str,
) -> str:
    return (
        f"flowchart_run:{int(flowchart_run_id)}:"
        f"node_run:{int(flowchart_run_node_id)}:"
        f"artifact:{str(artifact_type or '').strip().lower() or 'unknown'}"
    )

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import time
from typing import Any, Callable

from services.execution.idempotency import register_runtime_idempotency_key

DETERMINISTIC_TOOLING_CONTRACT_VERSION = "v1"
DETERMINISTIC_TOOL_STATUS_SUCCESS = "success"
DETERMINISTIC_TOOL_STATUS_SUCCESS_WITH_WARNING = "success_with_warning"
DETERMINISTIC_TOOL_WARNING_CODE = "deterministic_tool_failure"

DETERMINISTIC_BASE_TOOLS: dict[str, dict[str, Any]] = {
    "decision": {
        "tool_name": "deterministic.decision",
        "default_operation": "evaluate",
        "operations": ("evaluate", "legacy_route"),
        "artifact_hook_key": "decision_final_state",
    },
    "memory": {
        "tool_name": "deterministic.memory",
        "default_operation": "add",
        "operations": ("add", "retrieve"),
        "artifact_hook_key": "memory_final_state",
    },
    "milestone": {
        "tool_name": "deterministic.milestone",
        "default_operation": "create_or_update",
        "operations": ("create_or_update", "mark_complete"),
        "artifact_hook_key": "milestone_final_state",
    },
    "plan": {
        "tool_name": "deterministic.plan",
        "default_operation": "create_or_update_plan",
        "operations": ("create_or_update_plan", "complete_plan_item"),
        "artifact_hook_key": "plan_final_state",
    },
}


class ToolInvocationError(RuntimeError):
    pass


class ToolInvocationIdempotencyError(ToolInvocationError):
    pass


@dataclass(frozen=True)
class ToolInvocationConfig:
    node_type: str
    tool_name: str
    operation: str
    execution_id: int | None = None
    request_id: str | None = None
    correlation_id: str | None = None
    idempotency_scope: str | None = None
    idempotency_key: str | None = None
    max_attempts: int = 1
    retry_backoff_seconds: float = 0.0
    artifact_hook_key: str | None = None


@dataclass
class ToolInvocationOutcome:
    output_state: dict[str, Any]
    routing_state: dict[str, Any]
    trace_envelope: dict[str, Any]
    execution_status: str
    fallback_used: bool
    warnings: list[dict[str, Any]]


ToolCallable = Callable[[], tuple[dict[str, Any], dict[str, Any]]]
ToolValidator = Callable[[dict[str, Any], dict[str, Any]], None]
ToolArtifactHook = Callable[[dict[str, Any], dict[str, Any]], None]
ToolFallbackBuilder = Callable[[Exception], tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso8601(value: datetime) -> str:
    return value.isoformat()


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_operation(value: Any, *, default: str = "execute") -> str:
    operation = _normalize_text(value).lower()
    return operation or default


def build_tool_idempotency_scope(
    *,
    node_type: str,
    tool_name: str,
    operation: str,
) -> str:
    normalized_node_type = _normalize_text(node_type).lower() or "unknown"
    normalized_tool_name = _normalize_text(tool_name).lower() or "unknown"
    normalized_operation = _normalize_operation(operation)
    return (
        f"deterministic_tool:{normalized_node_type}:"
        f"{normalized_tool_name}:{normalized_operation}"
    )


def resolve_base_tool_scaffold(
    *,
    node_type: str,
    operation: str | None = None,
) -> dict[str, Any]:
    normalized_node_type = _normalize_text(node_type).lower()
    scaffold = DETERMINISTIC_BASE_TOOLS.get(normalized_node_type)
    if scaffold is None:
        raise ValueError(f"No deterministic base tool scaffold for node type '{node_type}'.")

    resolved_operation = _normalize_operation(
        operation if operation is not None else scaffold.get("default_operation")
    )
    allowed_operations = tuple(str(item) for item in scaffold.get("operations") or [])
    if allowed_operations and resolved_operation not in allowed_operations:
        resolved_operation = str(scaffold.get("default_operation") or resolved_operation)

    return {
        "node_type": normalized_node_type,
        "tool_name": str(scaffold.get("tool_name") or "").strip()
        or f"deterministic.{normalized_node_type}",
        "operation": resolved_operation,
        "artifact_hook_key": str(scaffold.get("artifact_hook_key") or "").strip() or None,
    }


def build_fallback_warning(
    *,
    message: str,
    code: str = DETERMINISTIC_TOOL_WARNING_CODE,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "code": _normalize_text(code) or DETERMINISTIC_TOOL_WARNING_CODE,
        "message": _normalize_text(message) or "Deterministic tool invocation failed.",
    }
    if isinstance(details, dict) and details:
        payload["details"] = details
    return payload


def apply_fallback_contract(
    output_state: dict[str, Any],
    routing_state: dict[str, Any],
    *,
    warning: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    next_output = dict(output_state or {})
    next_routing = dict(routing_state or {})
    warnings = list(next_output.get("warnings") or [])
    warnings.append(dict(warning))
    next_output["warnings"] = warnings
    next_output["execution_status"] = DETERMINISTIC_TOOL_STATUS_SUCCESS_WITH_WARNING
    next_output["fallback_used"] = True
    next_routing["fallback_used"] = True
    return next_output, next_routing


def _build_trace_envelope(
    *,
    config: ToolInvocationConfig,
    idempotency_scope: str | None,
    call_traces: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    execution_status: str,
    fallback_used: bool,
) -> dict[str, Any]:
    envelope: dict[str, Any] = {
        "contract_version": DETERMINISTIC_TOOLING_CONTRACT_VERSION,
        "node_type": _normalize_text(config.node_type).lower() or "unknown",
        "tool_name": _normalize_text(config.tool_name) or "unknown",
        "operation": _normalize_operation(config.operation),
        "execution_status": execution_status,
        "fallback_used": bool(fallback_used),
        "warnings": list(warnings),
        "attempt_count": len(call_traces),
        "calls": call_traces,
    }
    if config.execution_id is not None:
        envelope["execution_id"] = int(config.execution_id)
    if config.request_id:
        envelope["request_id"] = config.request_id
    if config.correlation_id:
        envelope["correlation_id"] = config.correlation_id
    if idempotency_scope:
        envelope["idempotency_scope"] = idempotency_scope
    if config.idempotency_key:
        envelope["idempotency_key"] = config.idempotency_key
    if config.artifact_hook_key:
        envelope["artifact_hook_key"] = config.artifact_hook_key
    return envelope


def _attach_trace_to_outputs(
    *,
    output_state: dict[str, Any],
    routing_state: dict[str, Any],
    trace_envelope: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    next_output = dict(output_state or {})
    next_routing = dict(routing_state or {})
    next_output["deterministic_tooling"] = dict(trace_envelope)
    next_routing["deterministic_tooling"] = {
        "contract_version": trace_envelope.get("contract_version"),
        "tool_name": trace_envelope.get("tool_name"),
        "operation": trace_envelope.get("operation"),
        "execution_status": trace_envelope.get("execution_status"),
        "fallback_used": trace_envelope.get("fallback_used"),
        "warnings": list(trace_envelope.get("warnings") or []),
        "request_id": trace_envelope.get("request_id"),
        "correlation_id": trace_envelope.get("correlation_id"),
        "artifact_hook_key": trace_envelope.get("artifact_hook_key"),
    }
    next_output["execution_status"] = trace_envelope.get("execution_status")
    next_output["fallback_used"] = bool(trace_envelope.get("fallback_used"))
    if trace_envelope.get("warnings"):
        next_output["warnings"] = list(trace_envelope.get("warnings") or [])
    return next_output, next_routing


def invoke_deterministic_tool(
    *,
    config: ToolInvocationConfig,
    invoke: ToolCallable,
    validate: ToolValidator | None = None,
    artifact_hook: ToolArtifactHook | None = None,
    fallback_builder: ToolFallbackBuilder | None = None,
) -> ToolInvocationOutcome:
    if not callable(invoke):
        raise ValueError("invoke callback is required.")

    operation = _normalize_operation(config.operation)
    max_attempts = max(1, int(config.max_attempts or 1))
    backoff_seconds = max(0.0, float(config.retry_backoff_seconds or 0.0))
    idempotency_scope = _normalize_text(config.idempotency_scope) or build_tool_idempotency_scope(
        node_type=config.node_type,
        tool_name=config.tool_name,
        operation=operation,
    )
    call_traces: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    idempotency_key = _normalize_text(config.idempotency_key)
    if idempotency_key:
        accepted = register_runtime_idempotency_key(idempotency_scope, idempotency_key)
        if not accepted:
            raise ToolInvocationIdempotencyError(
                "Deterministic tool invocation was blocked by idempotency controls."
            )

    for attempt in range(1, max_attempts + 1):
        started_at = _utcnow()
        try:
            output_state, routing_state = invoke()
            if not isinstance(output_state, dict) or not isinstance(routing_state, dict):
                raise ToolInvocationError(
                    "Deterministic tool invocation must return (output_state, routing_state)."
                )
            if validate is not None:
                validate(output_state, routing_state)
            if artifact_hook is not None:
                artifact_hook(output_state, routing_state)
            finished_at = _utcnow()
            call_traces.append(
                {
                    "attempt": attempt,
                    "status": "succeeded",
                    "started_at": _iso8601(started_at),
                    "finished_at": _iso8601(finished_at),
                    "duration_ms": int((finished_at - started_at).total_seconds() * 1000),
                }
            )
            trace_envelope = _build_trace_envelope(
                config=config,
                idempotency_scope=idempotency_scope,
                call_traces=call_traces,
                warnings=warnings,
                execution_status=DETERMINISTIC_TOOL_STATUS_SUCCESS,
                fallback_used=False,
            )
            traced_output, traced_routing = _attach_trace_to_outputs(
                output_state=output_state,
                routing_state=routing_state,
                trace_envelope=trace_envelope,
            )
            return ToolInvocationOutcome(
                output_state=traced_output,
                routing_state=traced_routing,
                trace_envelope=trace_envelope,
                execution_status=DETERMINISTIC_TOOL_STATUS_SUCCESS,
                fallback_used=False,
                warnings=[],
            )
        except Exception as exc:
            finished_at = _utcnow()
            call_traces.append(
                {
                    "attempt": attempt,
                    "status": "failed",
                    "started_at": _iso8601(started_at),
                    "finished_at": _iso8601(finished_at),
                    "duration_ms": int((finished_at - started_at).total_seconds() * 1000),
                    "error_type": type(exc).__name__,
                    "error": _normalize_text(exc),
                }
            )
            if attempt < max_attempts:
                if backoff_seconds > 0.0:
                    time.sleep(backoff_seconds)
                continue
            if fallback_builder is None:
                raise
            fallback_output, fallback_routing, warning = fallback_builder(exc)
            if not isinstance(fallback_output, dict) or not isinstance(fallback_routing, dict):
                raise ToolInvocationError(
                    "Fallback builder must return (output_state, routing_state, warning)."
                ) from exc
            warning_payload = (
                dict(warning)
                if isinstance(warning, dict)
                else build_fallback_warning(message=str(exc))
            )
            warnings = [warning_payload]
            fallback_output, fallback_routing = apply_fallback_contract(
                fallback_output,
                fallback_routing,
                warning=warning_payload,
            )
            if validate is not None:
                validate(fallback_output, fallback_routing)
            if artifact_hook is not None:
                artifact_hook(fallback_output, fallback_routing)
            trace_envelope = _build_trace_envelope(
                config=config,
                idempotency_scope=idempotency_scope,
                call_traces=call_traces,
                warnings=warnings,
                execution_status=DETERMINISTIC_TOOL_STATUS_SUCCESS_WITH_WARNING,
                fallback_used=True,
            )
            traced_output, traced_routing = _attach_trace_to_outputs(
                output_state=fallback_output,
                routing_state=fallback_routing,
                trace_envelope=trace_envelope,
            )
            return ToolInvocationOutcome(
                output_state=traced_output,
                routing_state=traced_routing,
                trace_envelope=trace_envelope,
                execution_status=DETERMINISTIC_TOOL_STATUS_SUCCESS_WITH_WARNING,
                fallback_used=True,
                warnings=warnings,
            )

    raise ToolInvocationError("Deterministic tool invocation ended in an invalid state.")

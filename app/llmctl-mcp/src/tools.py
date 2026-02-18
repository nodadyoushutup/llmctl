from __future__ import annotations

import json
import re
from typing import Any

from datetime import datetime, timedelta, timezone

from fastmcp import FastMCP
from sqlalchemy import delete, func, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import selectinload

from core.config import Config
from core.db import session_scope, utcnow
from core.models import (
    Agent,
    AgentTask,
    Attachment,
    Flowchart,
    FlowchartEdge,
    FlowchartNode,
    FlowchartRun,
    FlowchartRunNode,
    FLOWCHART_NODE_TYPE_CHOICES,
    FLOWCHART_NODE_TYPE_DECISION,
    FLOWCHART_NODE_TYPE_MEMORY,
    FLOWCHART_NODE_TYPE_MILESTONE,
    FLOWCHART_NODE_TYPE_PLAN,
    FLOWCHART_NODE_TYPE_START,
    FLOWCHART_NODE_TYPE_TASK,
    flowchart_node_mcp_servers,
    flowchart_node_skills,
    flowchart_node_scripts,
    LLMModel,
    MCPServer,
    Memory,
    Milestone,
    MILESTONE_HEALTH_CHOICES,
    MILESTONE_HEALTH_GREEN,
    MILESTONE_PRIORITY_CHOICES,
    MILESTONE_PRIORITY_MEDIUM,
    MILESTONE_STATUS_CHOICES,
    MILESTONE_STATUS_DONE,
    MILESTONE_STATUS_PLANNED,
    NodeArtifact,
    NODE_ARTIFACT_RETENTION_FOREVER,
    NODE_ARTIFACT_RETENTION_MAX_COUNT,
    NODE_ARTIFACT_RETENTION_TTL,
    NODE_ARTIFACT_RETENTION_TTL_MAX_COUNT,
    NODE_ARTIFACT_TYPE_MILESTONE,
    NODE_ARTIFACT_TYPE_PLAN,
    Plan,
    PlanStage,
    PlanTask,
    Run,
    RUN_ACTIVE_STATUSES,
    SKILL_STATUS_ARCHIVED,
    SKILL_STATUS_CHOICES,
    Skill,
    SkillVersion,
    Role,
    Script,
    agent_task_scripts,
    is_legacy_skill_script_type,
)
from core.task_kinds import QUICK_TASK_KIND, is_quick_task_kind
from services.celery_app import celery_app
from services.code_review import (
    CODE_REVIEW_TASK_KIND,
    ensure_code_reviewer_agent,
    ensure_code_reviewer_role,
)
from services.integrations import load_integration_settings
from services.skills import (
    SkillPackageValidationError,
    build_skill_package,
    format_validation_errors,
    import_skill_package_to_db,
)
from services.tasks import run_agent, run_agent_task, run_flowchart
from storage.attachment_storage import remove_attachment_file

from attachments import (
    _attach_attachments,
    _create_attachment_record,
    _decode_base64,
    _delete_attachment_if_unused,
    _resolve_attachment_target,
)
from constants import DEFAULT_LIMIT, MAX_LIMIT, MODEL_REGISTRY
from db_utils import (
    _clamp_limit,
    _coerce_value,
    _column_map,
    _resolve_model,
    _serialize_model,
)
from prompts import _build_code_review_prompt, _build_quick_task_prompt
from scripts import _parse_script_ids_by_type, _resolve_script_ids_by_type, _set_script_links


def _parse_optional_datetime(value: Any, field_name: str) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        cleaned = str(value).strip()
        if not cleaned:
            return None
        if cleaned.endswith("Z"):
            cleaned = f"{cleaned[:-1]}+00:00"
        try:
            if "T" in cleaned:
                parsed = datetime.fromisoformat(cleaned)
            else:
                parsed = datetime.fromisoformat(f"{cleaned}T00:00:00")
        except ValueError as exc:
            raise ValueError(f"{field_name} must be a valid ISO date/datetime.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _normalize_choice(
    value: Any,
    *,
    choices: tuple[str, ...],
    fallback: str,
) -> str:
    cleaned = str(value or "").strip().lower()
    if cleaned in choices:
        return cleaned
    return fallback


def _parse_milestone_progress(value: Any) -> int:
    cleaned = str(value or "").strip()
    if not cleaned:
        return 0
    try:
        parsed = int(cleaned)
    except (TypeError, ValueError) as exc:
        raise ValueError("progress_percent must be an integer between 0 and 100.") from exc
    if parsed < 0 or parsed > 100:
        raise ValueError("progress_percent must be an integer between 0 and 100.")
    return parsed


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        cleaned = value.strip().lower()
        if cleaned in {"1", "true", "yes", "on"}:
            return True
        if cleaned in {"0", "false", "no", "off"}:
            return False
    return bool(value)


FLOWCHART_NODE_TYPE_WITH_REF = {
    FLOWCHART_NODE_TYPE_PLAN,
    FLOWCHART_NODE_TYPE_MILESTONE,
    FLOWCHART_NODE_TYPE_MEMORY,
}
FLOWCHART_NODE_TYPE_REQUIRES_REF = {
    FLOWCHART_NODE_TYPE_PLAN,
    FLOWCHART_NODE_TYPE_MILESTONE,
    FLOWCHART_NODE_TYPE_MEMORY,
}
MILESTONE_NODE_ACTION_CREATE_OR_UPDATE = "create_or_update"
MILESTONE_NODE_ACTION_MARK_COMPLETE = "mark_complete"
PLAN_NODE_ACTION_CREATE_OR_UPDATE = "create_or_update_plan"
PLAN_NODE_ACTION_COMPLETE_PLAN_ITEM = "complete_plan_item"
DEFAULT_NODE_ARTIFACT_RETENTION_TTL_SECONDS = 3600
DEFAULT_NODE_ARTIFACT_RETENTION_MAX_COUNT = 25

FLOWCHART_NODE_UTILITY_COMPATIBILITY = {
    FLOWCHART_NODE_TYPE_START: {"model": False, "mcp": False, "scripts": False, "skills": False},
    FLOWCHART_NODE_TYPE_TASK: {"model": True, "mcp": True, "scripts": True, "skills": True},
    FLOWCHART_NODE_TYPE_PLAN: {"model": True, "mcp": True, "scripts": True, "skills": True},
    FLOWCHART_NODE_TYPE_MILESTONE: {"model": True, "mcp": True, "scripts": True, "skills": True},
    FLOWCHART_NODE_TYPE_MEMORY: {"model": True, "mcp": True, "scripts": True, "skills": True},
    FLOWCHART_NODE_TYPE_DECISION: {"model": False, "mcp": False, "scripts": False, "skills": False},
}
FLOWCHART_DEFAULT_MAX_OUTGOING_EDGES = 1
FLOWCHART_DECISION_MAX_OUTGOING_EDGES = 3


def _coerce_optional_int(
    value: Any,
    *,
    field_name: str,
    minimum: int | None = None,
) -> int | None:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return None
        value = cleaned
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer.") from exc
    if minimum is not None and parsed < minimum:
        raise ValueError(f"{field_name} must be >= {minimum}.")
    return parsed


def _coerce_float(value: Any, *, field_name: str, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return default
        value = cleaned
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a number.") from exc


def _coerce_optional_handle_id(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip().lower()
    if not cleaned:
        return None
    if not re.fullmatch(r"[a-z][0-9]+", cleaned):
        raise ValueError(f"{field_name} is invalid.")
    return cleaned


def _parse_json_dict(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _normalize_milestone_node_action(value: Any, *, field_name: str) -> str:
    cleaned = str(value or "").strip().lower()
    if cleaned in {"update", "checkpoint", "read", "create", "create_or_update", "create/update"}:
        return MILESTONE_NODE_ACTION_CREATE_OR_UPDATE
    if cleaned in {"complete", "mark_complete", "mark milestone complete"}:
        return MILESTONE_NODE_ACTION_MARK_COMPLETE
    raise ValueError(
        f"{field_name} must be one of: "
        f"{MILESTONE_NODE_ACTION_CREATE_OR_UPDATE}, {MILESTONE_NODE_ACTION_MARK_COMPLETE}."
    )


def _normalize_node_artifact_retention_mode(value: Any, *, field_name: str) -> str:
    cleaned = str(value or "").strip().lower()
    if cleaned in {"forever", "none", "disabled"}:
        return NODE_ARTIFACT_RETENTION_FOREVER
    if cleaned in {"max", "max_count"}:
        return NODE_ARTIFACT_RETENTION_MAX_COUNT
    if cleaned in {"ttl_max", "ttl+max", "ttl_max_count"}:
        return NODE_ARTIFACT_RETENTION_TTL_MAX_COUNT
    if cleaned in {"ttl", ""}:
        return NODE_ARTIFACT_RETENTION_TTL
    raise ValueError(
        f"{field_name} must be one of: "
        f"{NODE_ARTIFACT_RETENTION_FOREVER}, {NODE_ARTIFACT_RETENTION_TTL}, "
        f"{NODE_ARTIFACT_RETENTION_MAX_COUNT}, {NODE_ARTIFACT_RETENTION_TTL_MAX_COUNT}."
    )


def _sanitize_milestone_node_config(
    config_payload: Any,
    *,
    field_prefix: str,
) -> dict[str, Any]:
    if not isinstance(config_payload, dict):
        raise ValueError(f"{field_prefix} must be an object.")
    if "action" not in config_payload:
        raise ValueError(f"{field_prefix}.action is required for milestone nodes.")
    action = _normalize_milestone_node_action(
        config_payload.get("action"),
        field_name=f"{field_prefix}.action",
    )
    retention_mode = _normalize_node_artifact_retention_mode(
        config_payload.get("retention_mode"),
        field_name=f"{field_prefix}.retention_mode",
    )
    retention_ttl_seconds = _coerce_optional_int(
        config_payload.get("retention_ttl_seconds"),
        field_name=f"{field_prefix}.retention_ttl_seconds",
        minimum=1,
    )
    retention_max_count = _coerce_optional_int(
        config_payload.get("retention_max_count"),
        field_name=f"{field_prefix}.retention_max_count",
        minimum=1,
    )
    sanitized: dict[str, Any] = {
        "action": action,
        "additive_prompt": str(config_payload.get("additive_prompt") or "").strip(),
        "retention_mode": retention_mode,
        "retention_ttl_seconds": (
            retention_ttl_seconds
            if retention_ttl_seconds is not None
            else DEFAULT_NODE_ARTIFACT_RETENTION_TTL_SECONDS
        ),
        "retention_max_count": (
            retention_max_count
            if retention_max_count is not None
            else DEFAULT_NODE_ARTIFACT_RETENTION_MAX_COUNT
        ),
    }
    patch = config_payload.get("patch")
    if isinstance(patch, dict):
        sanitized["patch"] = patch
    completion_source_path = str(config_payload.get("completion_source_path") or "").strip()
    if completion_source_path:
        sanitized["completion_source_path"] = completion_source_path
    for key in ("route_key", "route_key_on_terminate"):
        value = str(config_payload.get(key) or "").strip()
        if value:
            sanitized[key] = value
    for key in ("terminate_on_complete", "terminate_on_checkpoint", "terminate_always"):
        if key in config_payload:
            sanitized[key] = _coerce_bool(config_payload.get(key))
    for key in ("loop_checkpoint_every", "loop_exit_after_runs"):
        if key in config_payload:
            coerced = _coerce_optional_int(
                config_payload.get(key),
                field_name=f"{field_prefix}.{key}",
                minimum=0,
            )
            if coerced is not None:
                sanitized[key] = coerced
    return sanitized


def _normalize_plan_node_action(value: Any, *, field_name: str) -> str:
    cleaned = str(value or "").strip().lower()
    if cleaned in {
        "create",
        "update",
        "read",
        "create_or_update",
        "create_or_update_plan",
        "create/update",
        "create or update plan",
        "update_completion",
        "complete",
    }:
        return PLAN_NODE_ACTION_CREATE_OR_UPDATE
    if cleaned in {
        "complete_plan_item",
        "complete plan item",
        "mark_plan_item_complete",
        "mark_task_complete",
    }:
        return PLAN_NODE_ACTION_COMPLETE_PLAN_ITEM
    raise ValueError(
        f"{field_name} must be one of: "
        f"{PLAN_NODE_ACTION_CREATE_OR_UPDATE}, {PLAN_NODE_ACTION_COMPLETE_PLAN_ITEM}."
    )


def _sanitize_plan_node_config(
    config_payload: Any,
    *,
    field_prefix: str,
) -> dict[str, Any]:
    if not isinstance(config_payload, dict):
        raise ValueError(f"{field_prefix} must be an object.")
    if "action" not in config_payload:
        raise ValueError(f"{field_prefix}.action is required for plan nodes.")
    action = _normalize_plan_node_action(
        config_payload.get("action"),
        field_name=f"{field_prefix}.action",
    )
    retention_mode = _normalize_node_artifact_retention_mode(
        config_payload.get("retention_mode"),
        field_name=f"{field_prefix}.retention_mode",
    )
    retention_ttl_seconds = _coerce_optional_int(
        config_payload.get("retention_ttl_seconds"),
        field_name=f"{field_prefix}.retention_ttl_seconds",
        minimum=1,
    )
    retention_max_count = _coerce_optional_int(
        config_payload.get("retention_max_count"),
        field_name=f"{field_prefix}.retention_max_count",
        minimum=1,
    )
    sanitized: dict[str, Any] = {
        "action": action,
        "additive_prompt": str(config_payload.get("additive_prompt") or "").strip(),
        "retention_mode": retention_mode,
        "retention_ttl_seconds": (
            retention_ttl_seconds
            if retention_ttl_seconds is not None
            else DEFAULT_NODE_ARTIFACT_RETENTION_TTL_SECONDS
        ),
        "retention_max_count": (
            retention_max_count
            if retention_max_count is not None
            else DEFAULT_NODE_ARTIFACT_RETENTION_MAX_COUNT
        ),
    }
    completion_source_path = str(config_payload.get("completion_source_path") or "").strip()
    if completion_source_path:
        sanitized["completion_source_path"] = completion_source_path
    if action == PLAN_NODE_ACTION_COMPLETE_PLAN_ITEM:
        plan_item_id = _coerce_optional_int(
            config_payload.get("plan_item_id"),
            field_name=f"{field_prefix}.plan_item_id",
            minimum=1,
        )
        stage_key = str(config_payload.get("stage_key") or "").strip()
        task_key = str(config_payload.get("task_key") or "").strip()
        if plan_item_id is not None:
            sanitized["plan_item_id"] = plan_item_id
        if stage_key:
            sanitized["stage_key"] = stage_key
        if task_key:
            sanitized["task_key"] = task_key
        if plan_item_id is None and not (stage_key and task_key) and not completion_source_path:
            raise ValueError(
                f"{field_prefix} requires plan_item_id, or stage_key + task_key, "
                "or completion_source_path when action is complete_plan_item."
            )
    else:
        patch = config_payload.get("patch")
        if isinstance(patch, dict):
            sanitized["patch"] = patch
    for key in ("route_key", "route_key_on_complete"):
        value = str(config_payload.get(key) or "").strip()
        if value:
            sanitized[key] = value
    return sanitized


def _serialize_node_artifact_item(item: NodeArtifact) -> dict[str, Any]:
    payload = _serialize_model(item, include_relationships=False)
    payload["payload"] = _parse_json_dict(item.payload_json)
    payload["payload_version"] = int(item.payload_version or 1)
    return payload


def _node_artifact_history_for_run_nodes(
    session,
    *,
    flowchart_run_id: int | None = None,
    node_run_ids: list[int] | None = None,
) -> dict[int, list[dict[str, Any]]]:
    stmt = select(NodeArtifact)
    if flowchart_run_id is not None:
        stmt = stmt.where(NodeArtifact.flowchart_run_id == flowchart_run_id)
    if node_run_ids is not None:
        cleaned = [node_run_id for node_run_id in node_run_ids if node_run_id > 0]
        if not cleaned:
            return {}
        stmt = stmt.where(NodeArtifact.flowchart_run_node_id.in_(cleaned))
    rows = (
        session.execute(
            stmt.order_by(NodeArtifact.created_at.desc(), NodeArtifact.id.desc())
        )
        .scalars()
        .all()
    )
    by_node_run: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        node_run_id = int(row.flowchart_run_node_id or 0)
        if node_run_id <= 0:
            continue
        by_node_run.setdefault(node_run_id, []).append(_serialize_node_artifact_item(row))
    return by_node_run


def _flowchart_node_compatibility(node_type: str) -> dict[str, bool]:
    return FLOWCHART_NODE_UTILITY_COMPATIBILITY.get(
        node_type,
        {"model": False, "mcp": False, "scripts": False, "skills": False},
    )


def _validate_flowchart_utility_compatibility(
    node_type: str,
    *,
    model_id: int | None = None,
    mcp_server_ids: list[int] | None = None,
    script_ids: list[int] | None = None,
    skill_ids: list[int] | None = None,
) -> list[str]:
    compatibility = _flowchart_node_compatibility(node_type)
    errors: list[str] = []
    if model_id is not None and not compatibility["model"]:
        errors.append(f"Node type '{node_type}' does not support models.")
    if mcp_server_ids and not compatibility["mcp"]:
        errors.append(f"Node type '{node_type}' does not support MCP servers.")
    if script_ids and not compatibility["scripts"]:
        errors.append(f"Node type '{node_type}' does not support scripts.")
    if skill_ids and not compatibility["skills"]:
        errors.append(f"Node type '{node_type}' does not support skills.")
    return errors


def _flowchart_ref_exists(
    session,
    *,
    node_type: str,
    ref_id: int | None,
) -> bool:
    if ref_id is None:
        return False
    if node_type == FLOWCHART_NODE_TYPE_PLAN:
        return session.get(Plan, ref_id) is not None
    if node_type == FLOWCHART_NODE_TYPE_MILESTONE:
        return session.get(Milestone, ref_id) is not None
    if node_type == FLOWCHART_NODE_TYPE_MEMORY:
        return session.get(Memory, ref_id) is not None
    return True


def _task_node_has_prompt(config: Any) -> bool:
    if not isinstance(config, dict):
        return False
    prompt = config.get("task_prompt")
    return isinstance(prompt, str) and bool(prompt.strip())


def _set_flowchart_node_scripts(
    session,
    node_id: int,
    script_ids: list[int],
) -> None:
    session.execute(
        delete(flowchart_node_scripts).where(
            flowchart_node_scripts.c.flowchart_node_id == node_id
        )
    )
    if not script_ids:
        return
    rows = [
        {
            "flowchart_node_id": node_id,
            "script_id": script_id,
            "position": position,
        }
        for position, script_id in enumerate(script_ids, start=1)
    ]
    session.execute(flowchart_node_scripts.insert(), rows)


def _serialize_flowchart_item(flowchart: Flowchart) -> dict[str, Any]:
    return _serialize_model(flowchart, include_relationships=False)


def _serialize_flowchart_node_item(node: FlowchartNode) -> dict[str, Any]:
    payload = _serialize_model(node, include_relationships=False)
    payload["config"] = _parse_json_dict(node.config_json)
    payload["mcp_server_ids"] = [server.id for server in node.mcp_servers]
    payload["script_ids"] = [script.id for script in node.scripts]
    payload["skill_ids"] = [skill.id for skill in node.skills]
    payload["compatibility"] = _flowchart_node_compatibility(node.node_type)
    return payload


def _serialize_flowchart_edge_item(edge: FlowchartEdge) -> dict[str, Any]:
    return _serialize_model(edge, include_relationships=False)


def _serialize_flowchart_run_item(run: FlowchartRun) -> dict[str, Any]:
    return _serialize_model(run, include_relationships=False)


def _serialize_flowchart_run_node_item(
    node_run: FlowchartRunNode,
    *,
    artifact_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload = _serialize_model(node_run, include_relationships=False)
    payload["input_context"] = _parse_json_dict(node_run.input_context_json)
    payload["output_state"] = _parse_json_dict(node_run.output_state_json)
    payload["routing_state"] = _parse_json_dict(node_run.routing_state_json)
    payload["artifact_history"] = artifact_history or []
    return payload


def _latest_skill_version(skill: Skill) -> SkillVersion | None:
    versions = sorted(list(skill.versions or []), key=lambda item: item.id or 0, reverse=True)
    return versions[0] if versions else None


def _default_skill_markdown(
    *,
    name: str,
    display_name: str,
    description: str,
    version: str,
    status: str,
) -> str:
    title = display_name or name or "Skill"
    return (
        "---\n"
        f"name: {name}\n"
        f"display_name: {display_name}\n"
        f"description: {description}\n"
        f"version: {version}\n"
        f"status: {status}\n"
        "---\n\n"
        f"# {title}\n"
    )


def _flowchart_graph_state(
    flowchart_nodes: list[FlowchartNode],
    flowchart_edges: list[FlowchartEdge],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = [
        {
            "id": node.id,
            "node_type": node.node_type,
            "ref_id": node.ref_id,
            "config": _parse_json_dict(node.config_json),
            "model_id": node.model_id,
            "mcp_server_ids": [server.id for server in node.mcp_servers],
            "script_ids": [script.id for script in node.scripts],
            "skill_ids": [skill.id for skill in node.skills],
        }
        for node in flowchart_nodes
    ]
    edges = [
        {
            "id": edge.id,
            "source_node_id": edge.source_node_id,
            "target_node_id": edge.target_node_id,
            "source_handle_id": edge.source_handle_id,
            "target_handle_id": edge.target_handle_id,
            "condition_key": edge.condition_key,
            "label": edge.label,
        }
        for edge in flowchart_edges
    ]
    return nodes, edges


def _validate_flowchart_graph_snapshot(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    node_ids: set[int] = set()
    node_type_by_id: dict[int, str] = {}
    incoming: dict[int, int] = {}
    outgoing: dict[int, int] = {}

    for node in nodes:
        node_id = int(node["id"])
        node_ids.add(node_id)
        node_type = str(node.get("node_type") or "")
        node_type_by_id[node_id] = node_type
        incoming.setdefault(node_id, 0)
        outgoing.setdefault(node_id, 0)
        if node_type not in FLOWCHART_NODE_TYPE_CHOICES:
            errors.append(f"Node {node_id} has unknown node_type '{node_type}'.")
            continue
        ref_id = node.get("ref_id")
        if node_type in FLOWCHART_NODE_TYPE_REQUIRES_REF and ref_id is None:
            errors.append(f"Node {node_id} ({node_type}) requires ref_id.")
        if node_type not in FLOWCHART_NODE_TYPE_WITH_REF and ref_id is not None:
            errors.append(f"Node {node_id} ({node_type}) does not allow ref_id.")
        if node_type == FLOWCHART_NODE_TYPE_TASK and not _task_node_has_prompt(
            node.get("config")
        ):
            errors.append(
                f"Node {node_id} ({node_type}) requires config.task_prompt."
            )
        if node_type == FLOWCHART_NODE_TYPE_MILESTONE:
            try:
                _sanitize_milestone_node_config(
                    node.get("config") or {},
                    field_prefix=f"nodes[{node_id}].config",
                )
            except ValueError as exc:
                errors.append(f"Node {node_id} ({node_type}) {exc}")
        if node_type == FLOWCHART_NODE_TYPE_PLAN:
            try:
                _sanitize_plan_node_config(
                    node.get("config") or {},
                    field_prefix=f"nodes[{node_id}].config",
                )
            except ValueError as exc:
                errors.append(f"Node {node_id} ({node_type}) {exc}")

        compatibility = _flowchart_node_compatibility(node_type)
        if node.get("model_id") is not None and not compatibility["model"]:
            errors.append(f"Node {node_id} ({node_type}) does not support models.")
        mcp_server_ids = node.get("mcp_server_ids") or []
        if mcp_server_ids and not compatibility["mcp"]:
            errors.append(f"Node {node_id} ({node_type}) does not support MCP servers.")
        script_ids = node.get("script_ids") or []
        if script_ids and not compatibility["scripts"]:
            errors.append(f"Node {node_id} ({node_type}) does not support scripts.")
        skill_ids = node.get("skill_ids") or []
        if skill_ids and not compatibility["skills"]:
            errors.append(f"Node {node_id} ({node_type}) does not support skills.")

    start_nodes = [node for node in nodes if node.get("node_type") == FLOWCHART_NODE_TYPE_START]
    if len(start_nodes) != 1:
        errors.append(
            f"Flowchart must contain exactly one start node; found {len(start_nodes)}."
        )

    decision_outgoing_keys: dict[int, list[str]] = {}
    for edge in edges:
        source_node_id = int(edge["source_node_id"])
        target_node_id = int(edge["target_node_id"])
        if source_node_id not in node_ids:
            errors.append(f"Edge source node {source_node_id} does not exist.")
            continue
        if target_node_id not in node_ids:
            errors.append(f"Edge target node {target_node_id} does not exist.")
            continue
        outgoing[source_node_id] = outgoing.get(source_node_id, 0) + 1
        incoming[target_node_id] = incoming.get(target_node_id, 0) + 1
        node_type = node_type_by_id.get(source_node_id)
        condition_key = (str(edge.get("condition_key") or "")).strip()
        if node_type == FLOWCHART_NODE_TYPE_DECISION:
            if not condition_key:
                errors.append(
                    f"Decision node {source_node_id} requires condition_key on each outgoing edge."
                )
            decision_outgoing_keys.setdefault(source_node_id, []).append(condition_key)
        elif condition_key:
            errors.append(
                f"Only decision nodes may define condition_key (source node {source_node_id})."
            )

    for node in nodes:
        node_id = int(node["id"])
        node_type = str(node.get("node_type") or "")
        if node_type not in FLOWCHART_NODE_TYPE_CHOICES:
            continue
        outgoing_count = outgoing.get(node_id, 0)
        if node_type == FLOWCHART_NODE_TYPE_DECISION:
            if outgoing_count > FLOWCHART_DECISION_MAX_OUTGOING_EDGES:
                errors.append(
                    f"Decision node {node_id} supports at most {FLOWCHART_DECISION_MAX_OUTGOING_EDGES} outgoing edges."
                )
        elif outgoing_count > FLOWCHART_DEFAULT_MAX_OUTGOING_EDGES:
            errors.append(
                f"Node {node_id} ({node_type}) supports at most {FLOWCHART_DEFAULT_MAX_OUTGOING_EDGES} outgoing edge."
            )
        if node.get("node_type") != FLOWCHART_NODE_TYPE_DECISION:
            continue
        if outgoing_count == 0:
            errors.append(f"Decision node {node_id} must have at least one outgoing edge.")
        keys = [key for key in decision_outgoing_keys.get(node_id, []) if key]
        if len(keys) != len(set(keys)):
            errors.append(f"Decision node {node_id} has duplicate condition_key values.")

    if len(start_nodes) == 1:
        start_id = int(start_nodes[0]["id"])
        visited: set[int] = set()
        frontier = [start_id]
        adjacency: dict[int, list[int]] = {}
        for edge in edges:
            source_node_id = int(edge["source_node_id"])
            target_node_id = int(edge["target_node_id"])
            adjacency.setdefault(source_node_id, []).append(target_node_id)
        while frontier:
            current = frontier.pop()
            if current in visited:
                continue
            visited.add(current)
            for target_id in adjacency.get(current, []):
                if target_id not in visited:
                    frontier.append(target_id)
        disconnected = sorted(node_ids.difference(visited))
        if disconnected:
            errors.append(
                "Disconnected required nodes found: "
                + ", ".join(str(node_id) for node_id in disconnected)
            )

    seen_errors: set[str] = set()
    deduped_errors: list[str] = []
    for error in errors:
        if error in seen_errors:
            continue
        seen_errors.add(error)
        deduped_errors.append(error)
    return deduped_errors


def _validate_flowchart_graph(
    flowchart_nodes: list[FlowchartNode],
    flowchart_edges: list[FlowchartEdge],
) -> list[str]:
    nodes, edges = _flowchart_graph_state(flowchart_nodes, flowchart_edges)
    return _validate_flowchart_graph_snapshot(nodes, edges)


def _serialize_plan_item(
    plan: Plan,
    *,
    include_stages: bool = False,
    include_tasks: bool = False,
) -> dict[str, Any]:
    data = _serialize_model(plan, include_relationships=False)
    stages = sorted(
        list(plan.stages or []),
        key=lambda item: (item.position or 0, item.id or 0),
    )
    data["stage_count"] = len(stages)
    data["task_count"] = sum(len(stage.tasks or []) for stage in stages)
    if include_stages:
        stage_items: list[dict[str, Any]] = []
        for stage in stages:
            stage_payload = _serialize_model(stage, include_relationships=False)
            tasks = sorted(
                list(stage.tasks or []),
                key=lambda item: (item.position or 0, item.id or 0),
            )
            stage_payload["task_count"] = len(tasks)
            if include_tasks:
                stage_payload["tasks"] = [
                    _serialize_model(task, include_relationships=False) for task in tasks
                ]
            stage_items.append(stage_payload)
        data["stages"] = stage_items
    return data


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def llmctl_get_model() -> dict[str, Any]:
        """Read/list all LLMCTL Studio data models available for MCP queries.

        Use this to discover valid model names before calling llmctl_get_model_schema
        or other model-specific tools. Prefer this over guessing model names.
        For row-level access, use llmctl_get_model_rows once you have the model name.
        Synonyms: read, list.
        Keywords: models list, model names, available tables, database models.
        """
        models = sorted({cls.__name__ for cls in MODEL_REGISTRY.values()})
        return {"ok": True, "models": models}

    @mcp.tool()
    def llmctl_get_model_schema(model: str) -> dict[str, Any]:
        """Read/list a model's schema, columns, and relationships.

        Use this to confirm field names for filtering/ordering and to see related
        models. Do not infer schema from code or files; ask this tool instead.
        For actual records, use llmctl_get_model_rows with the model name.
        Synonyms: read, list.
        Keywords: schema, fields, columns, relationships, attributes.
        """
        model_cls = _resolve_model(model)
        mapper = sa_inspect(model_cls)
        columns = []
        for column in mapper.columns:
            columns.append(
                {
                    "name": column.key,
                    "type": str(column.type),
                    "nullable": bool(column.nullable),
                    "primary_key": bool(column.primary_key),
                }
            )
        relationships = []
        for rel in mapper.relationships:
            relationships.append(
                {
                    "name": rel.key,
                    "target": rel.mapper.class_.__name__,
                    "uselist": bool(rel.uselist),
                }
            )
        return {
            "ok": True,
            "model": model_cls.__name__,
            "table": model_cls.__tablename__,
            "columns": columns,
            "relationships": relationships,
        }

    @mcp.tool()
    def llmctl_get_model_rows(
        model: str,
        filters: dict[str, Any] | None = None,
        limit: int | None = None,
        offset: int = 0,
        order_by: str | None = "id",
        descending: bool = False,
        include_relationships: bool = False,
    ) -> dict[str, Any]:
        """Read/list rows from any LLMCTL Studio model.

        Use this when you need records for a specific model without a bespoke tool.
        Prefer llmctl_get_model_schema first if you are unsure of fields/filters.
        Filters are column-based and support simple operators:
        - value: equals
        - {"op": "in", "value": [..]}
        - {"op": "lt|lte|gt|gte|ne|like|ilike", "value": ...}
        Synonyms: read, list, query.
        Keywords: generic model query, rows, records.
        """
        model_cls = _resolve_model(model)
        columns = _column_map(model_cls)
        stmt = select(model_cls)
        if filters:
            if not isinstance(filters, dict):
                return {"ok": False, "error": "filters must be an object."}
            for key, raw in filters.items():
                if key not in columns:
                    return {"ok": False, "error": f"Unknown filter column '{key}'."}
                col = columns[key]
                if isinstance(raw, dict) and "op" in raw:
                    op = str(raw.get("op", "")).strip().lower()
                    value = raw.get("value")
                    if op == "in":
                        if not isinstance(value, list):
                            return {
                                "ok": False,
                                "error": f"Filter '{key}' op 'in' expects a list.",
                            }
                        coerced = [_coerce_value(col, item) for item in value]
                        stmt = stmt.where(col.in_(coerced))
                    elif op in {"lt", "lte", "gt", "gte", "ne", "like", "ilike", "eq"}:
                        coerced = _coerce_value(col, value)
                        if op == "eq":
                            stmt = (
                                stmt.where(col.is_(None))
                                if coerced is None
                                else stmt.where(col == coerced)
                            )
                        elif op == "ne":
                            stmt = (
                                stmt.where(col.is_not(None))
                                if coerced is None
                                else stmt.where(col != coerced)
                            )
                        elif op == "lt":
                            stmt = stmt.where(col < coerced)
                        elif op == "lte":
                            stmt = stmt.where(col <= coerced)
                        elif op == "gt":
                            stmt = stmt.where(col > coerced)
                        elif op == "gte":
                            stmt = stmt.where(col >= coerced)
                        elif op == "like":
                            stmt = stmt.where(col.like(coerced))
                        elif op == "ilike":
                            stmt = stmt.where(col.ilike(coerced))
                    else:
                        return {
                            "ok": False,
                            "error": f"Unsupported filter op '{op}' for '{key}'.",
                        }
                else:
                    coerced = _coerce_value(col, raw)
                    if coerced is None:
                        stmt = stmt.where(col.is_(None))
                    else:
                        stmt = stmt.where(col == coerced)
        if order_by:
            if order_by not in columns:
                raise ValueError(f"Unknown order_by column '{order_by}'.")
            order_col = columns[order_by]
            stmt = stmt.order_by(order_col.desc() if descending else order_col.asc())
        limit = _clamp_limit(DEFAULT_LIMIT if limit is None else limit, MAX_LIMIT)
        if limit is not None:
            stmt = stmt.limit(limit)
        if offset:
            stmt = stmt.offset(max(0, int(offset)))
        with session_scope() as session:
            items = session.execute(stmt).scalars().all()
            payload = [_serialize_model(item, include_relationships) for item in items]
            return {"ok": True, "count": len(payload), "items": payload}

    @mcp.tool()
    def llmctl_get_flowchart(
        limit: int | None = None,
        offset: int = 0,
        order_by: str | None = "id",
        descending: bool = False,
        flowchart_id: int | None = None,
        include_graph: bool = False,
        include_validation: bool = False,
    ) -> dict[str, Any]:
        """Read/list flowcharts and optional graph data."""
        if flowchart_id is not None:
            with session_scope() as session:
                stmt = select(Flowchart).where(Flowchart.id == flowchart_id)
                if include_graph or include_validation:
                    stmt = stmt.options(
                        selectinload(Flowchart.nodes).selectinload(FlowchartNode.mcp_servers),
                        selectinload(Flowchart.nodes).selectinload(FlowchartNode.scripts),
                        selectinload(Flowchart.nodes).selectinload(FlowchartNode.skills),
                        selectinload(Flowchart.edges),
                    )
                flowchart = session.execute(stmt).scalars().first()
                if flowchart is None:
                    return {"ok": False, "error": f"Flowchart {flowchart_id} not found."}
                payload: dict[str, Any] = {
                    "ok": True,
                    "item": _serialize_flowchart_item(flowchart),
                }
                if include_graph or include_validation:
                    payload["nodes"] = [
                        _serialize_flowchart_node_item(node)
                        for node in sorted(
                            flowchart.nodes,
                            key=lambda item: (item.id or 0),
                        )
                    ]
                    payload["edges"] = [
                        _serialize_flowchart_edge_item(edge)
                        for edge in sorted(
                            flowchart.edges,
                            key=lambda item: (item.id or 0),
                        )
                    ]
                if include_validation:
                    errors = _validate_flowchart_graph(flowchart.nodes, flowchart.edges)
                    for node in flowchart.nodes:
                        if (
                            node.node_type in FLOWCHART_NODE_TYPE_WITH_REF
                            and node.ref_id is not None
                            and not _flowchart_ref_exists(
                                session,
                                node_type=node.node_type,
                                ref_id=node.ref_id,
                            )
                        ):
                            errors.append(
                                f"Node {node.id} ({node.node_type}) ref_id {node.ref_id} does not exist."
                            )
                    payload["validation"] = {"valid": len(errors) == 0, "errors": errors}
                return payload

        columns = _column_map(Flowchart)
        stmt = select(Flowchart)
        if order_by:
            if order_by not in columns:
                raise ValueError(f"Unknown order_by column '{order_by}'.")
            order_col = columns[order_by]
            stmt = stmt.order_by(order_col.desc() if descending else order_col.asc())
        limit = _clamp_limit(DEFAULT_LIMIT if limit is None else limit, MAX_LIMIT)
        if limit is not None:
            stmt = stmt.limit(limit)
        if offset:
            stmt = stmt.offset(max(0, int(offset)))
        with session_scope() as session:
            items = session.execute(stmt).scalars().all()
            payload = [_serialize_flowchart_item(item) for item in items]
            return {"ok": True, "count": len(payload), "items": payload}

    @mcp.tool()
    def llmctl_create_flowchart(
        name: str,
        description: str | None = None,
        max_node_executions: int | None = None,
        max_runtime_minutes: int | None = None,
        max_parallel_nodes: int | None = 1,
    ) -> dict[str, Any]:
        """Create a flowchart."""
        cleaned_name = (name or "").strip()
        if not cleaned_name:
            return {"ok": False, "error": "name is required."}
        try:
            max_exec = _coerce_optional_int(
                max_node_executions,
                field_name="max_node_executions",
                minimum=1,
            )
            max_runtime = _coerce_optional_int(
                max_runtime_minutes,
                field_name="max_runtime_minutes",
                minimum=1,
            )
            max_parallel = _coerce_optional_int(
                max_parallel_nodes,
                field_name="max_parallel_nodes",
                minimum=1,
            )
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        with session_scope() as session:
            item = Flowchart.create(
                session,
                name=cleaned_name,
                description=(description or "").strip() or None,
                max_node_executions=max_exec,
                max_runtime_minutes=max_runtime,
                max_parallel_nodes=max_parallel or 1,
            )
            return {"ok": True, "item": _serialize_flowchart_item(item)}

    @mcp.tool()
    def llmctl_update_flowchart(
        flowchart_id: int,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        """Update a flowchart by id."""
        if not isinstance(patch, dict) or not patch:
            return {"ok": False, "error": "patch must be a non-empty object."}
        allowed = {
            "name",
            "description",
            "max_node_executions",
            "max_runtime_minutes",
            "max_parallel_nodes",
        }
        unknown = sorted(set(patch).difference(allowed))
        if unknown:
            return {"ok": False, "error": f"Unknown fields: {', '.join(unknown)}"}
        with session_scope() as session:
            item = session.get(Flowchart, flowchart_id)
            if item is None:
                return {"ok": False, "error": f"Flowchart {flowchart_id} not found."}
            if "name" in patch:
                cleaned = str(patch.get("name") or "").strip()
                if not cleaned:
                    return {"ok": False, "error": "name cannot be empty."}
                item.name = cleaned
            if "description" in patch:
                item.description = str(patch.get("description") or "").strip() or None
            if "max_node_executions" in patch:
                try:
                    item.max_node_executions = _coerce_optional_int(
                        patch.get("max_node_executions"),
                        field_name="max_node_executions",
                        minimum=1,
                    )
                except ValueError as exc:
                    return {"ok": False, "error": str(exc)}
            if "max_runtime_minutes" in patch:
                try:
                    item.max_runtime_minutes = _coerce_optional_int(
                        patch.get("max_runtime_minutes"),
                        field_name="max_runtime_minutes",
                        minimum=1,
                    )
                except ValueError as exc:
                    return {"ok": False, "error": str(exc)}
            if "max_parallel_nodes" in patch:
                try:
                    parsed = _coerce_optional_int(
                        patch.get("max_parallel_nodes"),
                        field_name="max_parallel_nodes",
                        minimum=1,
                    )
                except ValueError as exc:
                    return {"ok": False, "error": str(exc)}
                if parsed is None:
                    return {"ok": False, "error": "max_parallel_nodes cannot be null."}
                item.max_parallel_nodes = parsed
            return {"ok": True, "item": _serialize_flowchart_item(item)}

    @mcp.tool()
    def llmctl_delete_flowchart(flowchart_id: int) -> dict[str, Any]:
        """Delete a flowchart and related graph/run records."""
        revoke_ids: list[str] = []
        with session_scope() as session:
            flowchart = session.get(Flowchart, flowchart_id)
            if flowchart is None:
                return {"ok": False, "error": f"Flowchart {flowchart_id} not found."}

            node_ids = (
                session.execute(
                    select(FlowchartNode.id).where(FlowchartNode.flowchart_id == flowchart_id)
                )
                .scalars()
                .all()
            )
            runs = (
                session.execute(
                    select(FlowchartRun).where(FlowchartRun.flowchart_id == flowchart_id)
                )
                .scalars()
                .all()
            )
            run_ids = [run.id for run in runs]
            for run in runs:
                if run.celery_task_id:
                    revoke_ids.append(run.celery_task_id)

            task_ids = set(
                session.execute(
                    select(AgentTask.id).where(AgentTask.flowchart_id == flowchart_id)
                )
                .scalars()
                .all()
            )
            if run_ids:
                task_ids.update(
                    session.execute(
                        select(AgentTask.id).where(AgentTask.flowchart_run_id.in_(run_ids))
                    )
                    .scalars()
                    .all()
                )
                session.execute(
                    delete(FlowchartRunNode).where(FlowchartRunNode.flowchart_run_id.in_(run_ids))
                )
            if node_ids:
                task_ids.update(
                    session.execute(
                        select(AgentTask.id).where(AgentTask.flowchart_node_id.in_(node_ids))
                    )
                    .scalars()
                    .all()
                )
                session.execute(
                    delete(flowchart_node_mcp_servers).where(
                        flowchart_node_mcp_servers.c.flowchart_node_id.in_(node_ids)
                    )
                )
                session.execute(
                    delete(flowchart_node_scripts).where(
                        flowchart_node_scripts.c.flowchart_node_id.in_(node_ids)
                    )
                )
                session.execute(
                    delete(flowchart_node_skills).where(
                        flowchart_node_skills.c.flowchart_node_id.in_(node_ids)
                    )
                )

            if task_ids:
                tasks = (
                    session.execute(select(AgentTask).where(AgentTask.id.in_(task_ids)))
                    .scalars()
                    .all()
                )
                for task in tasks:
                    if task.celery_task_id:
                        revoke_ids.append(task.celery_task_id)
                    session.delete(task)

            session.execute(delete(FlowchartEdge).where(FlowchartEdge.flowchart_id == flowchart_id))
            if node_ids:
                session.execute(delete(FlowchartNode).where(FlowchartNode.id.in_(node_ids)))
            if run_ids:
                session.execute(delete(FlowchartRun).where(FlowchartRun.id.in_(run_ids)))
            session.delete(flowchart)

        for task_id in revoke_ids:
            try:
                celery_app.control.revoke(task_id, terminate=True, signal="SIGTERM")
            except Exception:
                pass
        return {"ok": True, "flowchart_id": flowchart_id, "deleted": True}

    @mcp.tool()
    def llmctl_get_flowchart_graph(flowchart_id: int) -> dict[str, Any]:
        """Read flowchart graph nodes/edges with validation results."""
        with session_scope() as session:
            flowchart = (
                session.execute(
                    select(Flowchart)
                    .options(
                        selectinload(Flowchart.nodes).selectinload(FlowchartNode.mcp_servers),
                        selectinload(Flowchart.nodes).selectinload(FlowchartNode.scripts),
                        selectinload(Flowchart.nodes).selectinload(FlowchartNode.skills),
                        selectinload(Flowchart.edges),
                    )
                    .where(Flowchart.id == flowchart_id)
                )
                .scalars()
                .first()
            )
            if flowchart is None:
                return {"ok": False, "error": f"Flowchart {flowchart_id} not found."}
            errors = _validate_flowchart_graph(flowchart.nodes, flowchart.edges)
            for node in flowchart.nodes:
                if (
                    node.node_type in FLOWCHART_NODE_TYPE_WITH_REF
                    and node.ref_id is not None
                    and not _flowchart_ref_exists(
                        session,
                        node_type=node.node_type,
                        ref_id=node.ref_id,
                    )
                ):
                    errors.append(
                        f"Node {node.id} ({node.node_type}) ref_id {node.ref_id} does not exist."
                    )
            return {
                "ok": True,
                "flowchart_id": flowchart_id,
                "nodes": [_serialize_flowchart_node_item(node) for node in flowchart.nodes],
                "edges": [_serialize_flowchart_edge_item(edge) for edge in flowchart.edges],
                "validation": {"valid": len(errors) == 0, "errors": errors},
            }

    @mcp.tool()
    def llmctl_update_flowchart_graph(
        flowchart_id: int,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Atomic upsert for flowchart graph (nodes + edges)."""
        if not isinstance(nodes, list) or not isinstance(edges, list):
            return {"ok": False, "error": "nodes and edges must be arrays."}

        validation_errors: list[str] = []
        try:
            with session_scope() as session:
                flowchart = session.get(Flowchart, flowchart_id)
                if flowchart is None:
                    return {"ok": False, "error": f"Flowchart {flowchart_id} not found."}

                existing_nodes = (
                    session.execute(
                        select(FlowchartNode)
                        .options(
                            selectinload(FlowchartNode.mcp_servers),
                            selectinload(FlowchartNode.scripts),
                            selectinload(FlowchartNode.skills),
                        )
                        .where(FlowchartNode.flowchart_id == flowchart_id)
                    )
                    .scalars()
                    .all()
                )
                existing_nodes_by_id = {node.id: node for node in existing_nodes}
                keep_node_ids: set[int] = set()
                token_to_node_id: dict[str, int] = {}

                for index, raw_node in enumerate(nodes):
                    if not isinstance(raw_node, dict):
                        raise ValueError(f"nodes[{index}] must be an object.")
                    node_type = str(raw_node.get("node_type") or "").strip().lower()
                    if node_type not in FLOWCHART_NODE_TYPE_CHOICES:
                        raise ValueError(f"nodes[{index}] has invalid node_type '{node_type}'.")

                    node_id_raw = raw_node.get("id")
                    node_id = _coerce_optional_int(node_id_raw, field_name=f"nodes[{index}].id")
                    ref_id = _coerce_optional_int(
                        raw_node.get("ref_id"),
                        field_name=f"nodes[{index}].ref_id",
                    )
                    model_field_present = "model_id" in raw_node
                    model_id = _coerce_optional_int(
                        raw_node.get("model_id"),
                        field_name=f"nodes[{index}].model_id",
                        minimum=1,
                    )
                    x = _coerce_float(raw_node.get("x"), field_name=f"nodes[{index}].x")
                    y = _coerce_float(raw_node.get("y"), field_name=f"nodes[{index}].y")
                    title = str(raw_node.get("title") or "").strip() or None
                    config = raw_node.get("config")
                    if config is None and "config_json" in raw_node:
                        config = raw_node.get("config_json")
                    if config is None:
                        config_payload: dict[str, Any] = {}
                    elif isinstance(config, dict):
                        config_payload = config
                    else:
                        raise ValueError(f"nodes[{index}].config must be an object.")

                    if node_type in FLOWCHART_NODE_TYPE_REQUIRES_REF and ref_id is None:
                        raise ValueError(
                            f"nodes[{index}] requires ref_id for node_type '{node_type}'."
                        )
                    if node_type not in FLOWCHART_NODE_TYPE_WITH_REF and ref_id is not None:
                        raise ValueError(
                            f"nodes[{index}] node_type '{node_type}' does not allow ref_id."
                        )
                    if (
                        node_type == FLOWCHART_NODE_TYPE_TASK
                        and not _task_node_has_prompt(config_payload)
                    ):
                        raise ValueError(
                            f"nodes[{index}] task node requires config.task_prompt."
                        )
                    if node_type == FLOWCHART_NODE_TYPE_MILESTONE:
                        config_payload = _sanitize_milestone_node_config(
                            config_payload,
                            field_prefix=f"nodes[{index}].config",
                        )
                    if node_type == FLOWCHART_NODE_TYPE_PLAN:
                        config_payload = _sanitize_plan_node_config(
                            config_payload,
                            field_prefix=f"nodes[{index}].config",
                        )
                    compatibility_errors = _validate_flowchart_utility_compatibility(
                        node_type,
                        model_id=model_id if model_field_present else None,
                    )
                    if compatibility_errors:
                        raise ValueError(compatibility_errors[0])

                    flowchart_node = (
                        existing_nodes_by_id.get(node_id) if node_id is not None else None
                    )
                    if flowchart_node is None:
                        flowchart_node = FlowchartNode.create(
                            session,
                            flowchart_id=flowchart_id,
                            node_type=node_type,
                            ref_id=ref_id,
                            title=title,
                            x=x,
                            y=y,
                            config_json=json.dumps(config_payload, sort_keys=True),
                        )
                    else:
                        flowchart_node.node_type = node_type
                        flowchart_node.ref_id = ref_id
                        flowchart_node.title = title
                        flowchart_node.x = x
                        flowchart_node.y = y
                        flowchart_node.config_json = json.dumps(config_payload, sort_keys=True)

                    if model_field_present:
                        if model_id is not None and session.get(LLMModel, model_id) is None:
                            raise ValueError(f"nodes[{index}].model_id {model_id} was not found.")
                        flowchart_node.model_id = model_id

                    if (
                        node_type in FLOWCHART_NODE_TYPE_WITH_REF
                        and flowchart_node.ref_id is not None
                        and not _flowchart_ref_exists(
                            session,
                            node_type=node_type,
                            ref_id=flowchart_node.ref_id,
                        )
                    ):
                        raise ValueError(
                            f"nodes[{index}] references missing ref_id {flowchart_node.ref_id}."
                        )

                    if "mcp_server_ids" in raw_node:
                        mcp_server_ids_raw = raw_node.get("mcp_server_ids")
                        if not isinstance(mcp_server_ids_raw, list):
                            raise ValueError(f"nodes[{index}].mcp_server_ids must be an array.")
                        mcp_server_ids: list[int] = []
                        for mcp_index, mcp_id_raw in enumerate(mcp_server_ids_raw):
                            mcp_id = _coerce_optional_int(
                                mcp_id_raw,
                                field_name=f"nodes[{index}].mcp_server_ids[{mcp_index}]",
                                minimum=1,
                            )
                            if mcp_id is None:
                                raise ValueError(
                                    f"nodes[{index}].mcp_server_ids[{mcp_index}] is invalid."
                                )
                            mcp_server_ids.append(mcp_id)
                        if len(mcp_server_ids) != len(set(mcp_server_ids)):
                            raise ValueError(f"nodes[{index}] has duplicate mcp_server_ids.")
                        compatibility_errors = _validate_flowchart_utility_compatibility(
                            node_type,
                            mcp_server_ids=mcp_server_ids,
                        )
                        if compatibility_errors:
                            raise ValueError(compatibility_errors[0])
                        selected_servers = (
                            session.execute(select(MCPServer).where(MCPServer.id.in_(mcp_server_ids)))
                            .scalars()
                            .all()
                        )
                        if len(selected_servers) != len(set(mcp_server_ids)):
                            raise ValueError(f"nodes[{index}] contains unknown MCP server IDs.")
                        flowchart_node.mcp_servers = selected_servers

                    if "script_ids" in raw_node:
                        script_ids_raw = raw_node.get("script_ids")
                        if not isinstance(script_ids_raw, list):
                            raise ValueError(f"nodes[{index}].script_ids must be an array.")
                        script_ids: list[int] = []
                        for script_index, script_id_raw in enumerate(script_ids_raw):
                            script_id = _coerce_optional_int(
                                script_id_raw,
                                field_name=f"nodes[{index}].script_ids[{script_index}]",
                                minimum=1,
                            )
                            if script_id is None:
                                raise ValueError(
                                    f"nodes[{index}].script_ids[{script_index}] is invalid."
                                )
                            script_ids.append(script_id)
                        if len(script_ids) != len(set(script_ids)):
                            raise ValueError(f"nodes[{index}] has duplicate script_ids.")
                        compatibility_errors = _validate_flowchart_utility_compatibility(
                            node_type,
                            script_ids=script_ids,
                        )
                        if compatibility_errors:
                            raise ValueError(compatibility_errors[0])
                        selected_scripts = (
                            session.execute(select(Script).where(Script.id.in_(script_ids)))
                            .scalars()
                            .all()
                        )
                        if len(selected_scripts) != len(set(script_ids)):
                            raise ValueError(f"nodes[{index}] contains unknown script IDs.")
                        if any(
                            is_legacy_skill_script_type(item.script_type)
                            for item in selected_scripts
                        ):
                            raise ValueError(
                                f"nodes[{index}] cannot attach legacy script_type=skill records; assign skills on the Agent."
                            )
                        _set_flowchart_node_scripts(session, flowchart_node.id, script_ids)

                    if "skill_ids" in raw_node:
                        raise ValueError(
                            f"nodes[{index}].skill_ids is no longer writable; assign skills on the Agent."
                        )

                    keep_node_ids.add(flowchart_node.id)
                    if node_id_raw is not None:
                        token_to_node_id[str(node_id_raw)] = flowchart_node.id
                    if raw_node.get("client_id") is not None:
                        token_to_node_id[str(raw_node["client_id"])] = flowchart_node.id
                    token_to_node_id[str(flowchart_node.id)] = flowchart_node.id

                session.execute(delete(FlowchartEdge).where(FlowchartEdge.flowchart_id == flowchart_id))

                for index, raw_edge in enumerate(edges):
                    if not isinstance(raw_edge, dict):
                        raise ValueError(f"edges[{index}] must be an object.")
                    source_raw = raw_edge.get("source_node_id")
                    target_raw = raw_edge.get("target_node_id")
                    if source_raw is None and "source" in raw_edge:
                        source_raw = raw_edge.get("source")
                    if target_raw is None and "target" in raw_edge:
                        target_raw = raw_edge.get("target")
                    source_node_id = token_to_node_id.get(str(source_raw))
                    target_node_id = token_to_node_id.get(str(target_raw))
                    if source_node_id is None:
                        raise ValueError(f"edges[{index}].source_node_id is invalid.")
                    if target_node_id is None:
                        raise ValueError(f"edges[{index}].target_node_id is invalid.")
                    source_handle_id = _coerce_optional_handle_id(
                        raw_edge.get("source_handle_id"),
                        field_name=f"edges[{index}].source_handle_id",
                    )
                    target_handle_id = _coerce_optional_handle_id(
                        raw_edge.get("target_handle_id"),
                        field_name=f"edges[{index}].target_handle_id",
                    )
                    condition_key = str(raw_edge.get("condition_key") or "").strip() or None
                    label = str(raw_edge.get("label") or "").strip() or None
                    FlowchartEdge.create(
                        session,
                        flowchart_id=flowchart_id,
                        source_node_id=source_node_id,
                        target_node_id=target_node_id,
                        source_handle_id=source_handle_id,
                        target_handle_id=target_handle_id,
                        condition_key=condition_key,
                        label=label,
                    )

                removed_node_ids = set(existing_nodes_by_id).difference(keep_node_ids)
                if removed_node_ids:
                    session.execute(
                        delete(flowchart_node_mcp_servers).where(
                            flowchart_node_mcp_servers.c.flowchart_node_id.in_(removed_node_ids)
                        )
                    )
                    session.execute(
                        delete(flowchart_node_scripts).where(
                            flowchart_node_scripts.c.flowchart_node_id.in_(removed_node_ids)
                        )
                    )
                    session.execute(
                        delete(flowchart_node_skills).where(
                            flowchart_node_skills.c.flowchart_node_id.in_(removed_node_ids)
                        )
                    )
                    session.execute(delete(FlowchartNode).where(FlowchartNode.id.in_(removed_node_ids)))

                updated_nodes = (
                    session.execute(
                        select(FlowchartNode)
                        .options(
                            selectinload(FlowchartNode.mcp_servers),
                            selectinload(FlowchartNode.scripts),
                            selectinload(FlowchartNode.skills),
                        )
                        .where(FlowchartNode.flowchart_id == flowchart_id)
                        .order_by(FlowchartNode.id.asc())
                    )
                    .scalars()
                    .all()
                )
                updated_edges = (
                    session.execute(
                        select(FlowchartEdge)
                        .where(FlowchartEdge.flowchart_id == flowchart_id)
                        .order_by(FlowchartEdge.id.asc())
                    )
                    .scalars()
                    .all()
                )
                validation_errors = _validate_flowchart_graph(updated_nodes, updated_edges)
                for node in updated_nodes:
                    if (
                        node.node_type in FLOWCHART_NODE_TYPE_WITH_REF
                        and node.ref_id is not None
                        and not _flowchart_ref_exists(
                            session,
                            node_type=node.node_type,
                            ref_id=node.ref_id,
                        )
                    ):
                        validation_errors.append(
                            f"Node {node.id} ({node.node_type}) ref_id {node.ref_id} does not exist."
                        )
                if validation_errors:
                    raise ValueError("Flowchart graph validation failed.")
        except ValueError as exc:
            if validation_errors:
                return {
                    "ok": False,
                    "error": str(exc),
                    "validation": {"valid": False, "errors": validation_errors},
                }
            return {"ok": False, "error": str(exc)}
        return llmctl_get_flowchart_graph(flowchart_id)

    @mcp.tool()
    def start_flowchart(flowchart_id: int) -> dict[str, Any]:
        """Queue a new flowchart run after validating the graph."""
        validation_errors: list[str] = []
        with session_scope() as session:
            flowchart = (
                session.execute(
                    select(Flowchart)
                    .options(
                        selectinload(Flowchart.nodes).selectinload(FlowchartNode.mcp_servers),
                        selectinload(Flowchart.nodes).selectinload(FlowchartNode.scripts),
                        selectinload(Flowchart.nodes).selectinload(FlowchartNode.skills),
                        selectinload(Flowchart.edges),
                    )
                    .where(Flowchart.id == flowchart_id)
                )
                .scalars()
                .first()
            )
            if flowchart is None:
                return {"ok": False, "error": f"Flowchart {flowchart_id} not found."}
            validation_errors = _validate_flowchart_graph(flowchart.nodes, flowchart.edges)
            for node in flowchart.nodes:
                if (
                    node.node_type in FLOWCHART_NODE_TYPE_WITH_REF
                    and node.ref_id is not None
                    and not _flowchart_ref_exists(
                        session,
                        node_type=node.node_type,
                        ref_id=node.ref_id,
                    )
                ):
                    validation_errors.append(
                        f"Node {node.id} ({node.node_type}) ref_id {node.ref_id} does not exist."
                    )
            if validation_errors:
                return {
                    "ok": False,
                    "error": "Flowchart graph validation failed.",
                    "validation": {"valid": False, "errors": validation_errors},
                }
            flowchart_run = FlowchartRun.create(
                session,
                flowchart_id=flowchart_id,
                status="queued",
            )
            run_id = flowchart_run.id

        async_result = run_flowchart.delay(flowchart_id, run_id)
        with session_scope() as session:
            flowchart_run = session.get(FlowchartRun, run_id)
            if flowchart_run is None:
                return {"ok": False, "error": f"Flowchart run {run_id} not found after enqueue."}
            flowchart_run.celery_task_id = async_result.id
            payload = _serialize_flowchart_run_item(flowchart_run)
        return {
            "ok": True,
            "flowchart_run": {**payload, "validation": {"valid": True, "errors": []}},
        }

    @mcp.tool()
    def cancel_flowchart_run(run_id: int) -> dict[str, Any]:
        """Cancel an active flowchart run."""
        revoke_ids: list[str] = []
        with session_scope() as session:
            flowchart_run = session.get(FlowchartRun, run_id)
            if flowchart_run is None:
                return {"ok": False, "error": f"Flowchart run {run_id} not found."}
            if flowchart_run.status not in {"queued", "running"}:
                return {
                    "ok": True,
                    "flowchart_run": _serialize_flowchart_run_item(flowchart_run),
                    "canceled": False,
                }

            now = utcnow()
            flowchart_run.status = "canceled"
            flowchart_run.finished_at = now
            if flowchart_run.celery_task_id:
                revoke_ids.append(flowchart_run.celery_task_id)

            node_runs = (
                session.execute(
                    select(FlowchartRunNode).where(FlowchartRunNode.flowchart_run_id == run_id)
                )
                .scalars()
                .all()
            )
            for node_run in node_runs:
                if node_run.status in {"queued", "running", "pending"}:
                    node_run.status = "canceled"
                    node_run.finished_at = now

            tasks = (
                session.execute(select(AgentTask).where(AgentTask.flowchart_run_id == run_id))
                .scalars()
                .all()
            )
            for task in tasks:
                if task.status in {"pending", "queued", "running"}:
                    task.status = "canceled"
                    task.finished_at = now
                    if not task.error:
                        task.error = "Canceled by user."
                if task.celery_task_id:
                    revoke_ids.append(task.celery_task_id)

        for task_id in revoke_ids:
            try:
                celery_app.control.revoke(task_id, terminate=True, signal="SIGTERM")
            except Exception:
                pass

        with session_scope() as session:
            flowchart_run = session.get(FlowchartRun, run_id)
            if flowchart_run is None:
                return {"ok": False, "error": f"Flowchart run {run_id} not found after cancel."}
            return {
                "ok": True,
                "flowchart_run": _serialize_flowchart_run_item(flowchart_run),
                "canceled": True,
            }

    @mcp.tool()
    def llmctl_get_flowchart_run(
        run_id: int,
        include_node_runs: bool = True,
    ) -> dict[str, Any]:
        """Read a flowchart run and optional node-run details."""
        with session_scope() as session:
            flowchart_run = session.get(FlowchartRun, run_id)
            if flowchart_run is None:
                return {"ok": False, "error": f"Flowchart run {run_id} not found."}
            rows = session.execute(
                select(FlowchartRunNode.status, func.count(FlowchartRunNode.id))
                .where(FlowchartRunNode.flowchart_run_id == run_id)
                .group_by(FlowchartRunNode.status)
            ).all()
            counts = {str(status): int(count or 0) for status, count in rows}
            payload: dict[str, Any] = {
                "ok": True,
                "flowchart_run": _serialize_flowchart_run_item(flowchart_run),
                "counts": counts,
            }
            if include_node_runs:
                node_runs = (
                    session.execute(
                        select(FlowchartRunNode)
                        .where(FlowchartRunNode.flowchart_run_id == run_id)
                        .order_by(
                            FlowchartRunNode.execution_index.asc(),
                            FlowchartRunNode.created_at.asc(),
                            FlowchartRunNode.id.asc(),
                        )
                    )
                    .scalars()
                    .all()
                )
                artifact_history_by_node_run = _node_artifact_history_for_run_nodes(
                    session,
                    flowchart_run_id=run_id,
                )
                payload["node_runs"] = [
                    _serialize_flowchart_run_node_item(
                        node_run,
                        artifact_history=artifact_history_by_node_run.get(node_run.id, []),
                    )
                    for node_run in node_runs
                ]
            return payload

    @mcp.tool()
    def llmctl_get_node_run(
        limit: int | None = None,
        offset: int = 0,
        order_by: str | None = "id",
        descending: bool = False,
        node_run_id: int | None = None,
        flowchart_run_id: int | None = None,
        flowchart_node_id: int | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """Read/list node runs (flowchart_run_nodes)."""
        if node_run_id is not None:
            with session_scope() as session:
                item = session.get(FlowchartRunNode, node_run_id)
                if item is None:
                    return {"ok": False, "error": f"Node run {node_run_id} not found."}
                artifact_history_by_node_run = _node_artifact_history_for_run_nodes(
                    session,
                    node_run_ids=[item.id],
                )
                return {
                    "ok": True,
                    "item": _serialize_flowchart_run_node_item(
                        item,
                        artifact_history=artifact_history_by_node_run.get(item.id, []),
                    ),
                }

        columns = _column_map(FlowchartRunNode)
        stmt = select(FlowchartRunNode)
        if flowchart_run_id is not None:
            stmt = stmt.where(FlowchartRunNode.flowchart_run_id == flowchart_run_id)
        if flowchart_node_id is not None:
            stmt = stmt.where(FlowchartRunNode.flowchart_node_id == flowchart_node_id)
        if status:
            stmt = stmt.where(FlowchartRunNode.status == str(status).strip())
        if order_by:
            if order_by not in columns:
                raise ValueError(f"Unknown order_by column '{order_by}'.")
            order_col = columns[order_by]
            stmt = stmt.order_by(order_col.desc() if descending else order_col.asc())
        limit = _clamp_limit(DEFAULT_LIMIT if limit is None else limit, MAX_LIMIT)
        if limit is not None:
            stmt = stmt.limit(limit)
        if offset:
            stmt = stmt.offset(max(0, int(offset)))
        with session_scope() as session:
            items = session.execute(stmt).scalars().all()
            artifact_history_by_node_run = _node_artifact_history_for_run_nodes(
                session,
                node_run_ids=[int(item.id) for item in items],
            )
            payload = [
                _serialize_flowchart_run_node_item(
                    item,
                    artifact_history=artifact_history_by_node_run.get(item.id, []),
                )
                for item in items
            ]
            return {"ok": True, "count": len(payload), "items": payload}

    @mcp.tool()
    def llmctl_get_node_artifact(
        limit: int | None = None,
        offset: int = 0,
        order_by: str | None = "id",
        descending: bool = False,
        artifact_id: int | None = None,
        flowchart_id: int | None = None,
        flowchart_node_id: int | None = None,
        flowchart_run_id: int | None = None,
        flowchart_run_node_id: int | None = None,
        artifact_type: str | None = None,
        ref_id: int | None = None,
    ) -> dict[str, Any]:
        """Read/list node artifacts (node_artifacts)."""
        if artifact_id is not None:
            with session_scope() as session:
                item = session.get(NodeArtifact, artifact_id)
                if item is None:
                    return {"ok": False, "error": f"Node artifact {artifact_id} not found."}
                return {"ok": True, "item": _serialize_node_artifact_item(item)}

        columns = _column_map(NodeArtifact)
        stmt = select(NodeArtifact)
        if flowchart_id is not None:
            stmt = stmt.where(NodeArtifact.flowchart_id == flowchart_id)
        if flowchart_node_id is not None:
            stmt = stmt.where(NodeArtifact.flowchart_node_id == flowchart_node_id)
        if flowchart_run_id is not None:
            stmt = stmt.where(NodeArtifact.flowchart_run_id == flowchart_run_id)
        if flowchart_run_node_id is not None:
            stmt = stmt.where(NodeArtifact.flowchart_run_node_id == flowchart_run_node_id)
        if artifact_type:
            stmt = stmt.where(NodeArtifact.artifact_type == str(artifact_type).strip())
        if ref_id is not None:
            stmt = stmt.where(NodeArtifact.ref_id == ref_id)
        if order_by:
            if order_by not in columns:
                raise ValueError(f"Unknown order_by column '{order_by}'.")
            order_col = columns[order_by]
            stmt = stmt.order_by(order_col.desc() if descending else order_col.asc())
        limit = _clamp_limit(DEFAULT_LIMIT if limit is None else limit, MAX_LIMIT)
        if limit is not None:
            stmt = stmt.limit(limit)
        if offset:
            stmt = stmt.offset(max(0, int(offset)))
        with session_scope() as session:
            items = session.execute(stmt).scalars().all()
            payload = [_serialize_node_artifact_item(item) for item in items]
            return {"ok": True, "count": len(payload), "items": payload}

    @mcp.tool()
    def llmctl_set_flowchart_node_model(
        flowchart_id: int,
        node_id: int,
        model_id: int | None = None,
    ) -> dict[str, Any]:
        """Set or clear the model bound to a flowchart node."""
        try:
            parsed_model_id = _coerce_optional_int(model_id, field_name="model_id", minimum=1)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        with session_scope() as session:
            node = session.get(FlowchartNode, node_id)
            if node is None or node.flowchart_id != flowchart_id:
                return {
                    "ok": False,
                    "error": f"Flowchart node {node_id} was not found in flowchart {flowchart_id}.",
                }
            errors = _validate_flowchart_utility_compatibility(
                node.node_type,
                model_id=parsed_model_id,
            )
            if errors:
                return {"ok": False, "error": errors[0]}
            if parsed_model_id is not None and session.get(LLMModel, parsed_model_id) is None:
                return {"ok": False, "error": f"Model {parsed_model_id} was not found."}
            node.model_id = parsed_model_id
            session.flush()
            refreshed = (
                session.execute(
                    select(FlowchartNode)
                    .options(
                        selectinload(FlowchartNode.mcp_servers),
                        selectinload(FlowchartNode.scripts),
                    )
                    .where(FlowchartNode.id == node_id)
                )
                .scalars()
                .first()
            )
            if refreshed is None:
                return {"ok": False, "error": f"Flowchart node {node_id} was not found."}
            return {"ok": True, "node": _serialize_flowchart_node_item(refreshed)}

    @mcp.tool()
    def llmctl_bind_flowchart_node_mcp(
        flowchart_id: int,
        node_id: int,
        mcp_server_id: int,
    ) -> dict[str, Any]:
        """Bind an MCP server to a flowchart node."""
        with session_scope() as session:
            node = (
                session.execute(
                    select(FlowchartNode)
                    .options(selectinload(FlowchartNode.mcp_servers))
                    .where(FlowchartNode.id == node_id)
                )
                .scalars()
                .first()
            )
            if node is None or node.flowchart_id != flowchart_id:
                return {
                    "ok": False,
                    "error": f"Flowchart node {node_id} was not found in flowchart {flowchart_id}.",
                }
            errors = _validate_flowchart_utility_compatibility(
                node.node_type,
                mcp_server_ids=[mcp_server_id],
            )
            if errors:
                return {"ok": False, "error": errors[0]}
            server = session.get(MCPServer, mcp_server_id)
            if server is None:
                return {"ok": False, "error": f"MCP server {mcp_server_id} was not found."}
            existing = {item.id for item in node.mcp_servers}
            if server.id not in existing:
                node.mcp_servers.append(server)
            session.flush()
            return {"ok": True, "node": _serialize_flowchart_node_item(node)}

    @mcp.tool()
    def llmctl_unbind_flowchart_node_mcp(
        flowchart_id: int,
        node_id: int,
        mcp_server_id: int,
    ) -> dict[str, Any]:
        """Unbind an MCP server from a flowchart node."""
        with session_scope() as session:
            node = (
                session.execute(
                    select(FlowchartNode)
                    .options(selectinload(FlowchartNode.mcp_servers))
                    .where(FlowchartNode.id == node_id)
                )
                .scalars()
                .first()
            )
            if node is None or node.flowchart_id != flowchart_id:
                return {
                    "ok": False,
                    "error": f"Flowchart node {node_id} was not found in flowchart {flowchart_id}.",
                }
            for server in list(node.mcp_servers):
                if server.id == mcp_server_id:
                    node.mcp_servers.remove(server)
            session.flush()
            return {"ok": True, "node": _serialize_flowchart_node_item(node)}

    @mcp.tool()
    def llmctl_bind_flowchart_node_script(
        flowchart_id: int,
        node_id: int,
        script_id: int,
    ) -> dict[str, Any]:
        """Bind a script to a flowchart node."""
        with session_scope() as session:
            node = (
                session.execute(
                    select(FlowchartNode)
                    .options(
                        selectinload(FlowchartNode.scripts),
                        selectinload(FlowchartNode.skills),
                    )
                    .where(FlowchartNode.id == node_id)
                )
                .scalars()
                .first()
            )
            if node is None or node.flowchart_id != flowchart_id:
                return {
                    "ok": False,
                    "error": f"Flowchart node {node_id} was not found in flowchart {flowchart_id}.",
                }
            errors = _validate_flowchart_utility_compatibility(
                node.node_type,
                script_ids=[script_id],
            )
            if errors:
                return {"ok": False, "error": errors[0]}
            script = session.get(Script, script_id)
            if script is None:
                return {"ok": False, "error": f"Script {script_id} was not found."}
            if is_legacy_skill_script_type(script.script_type):
                return {
                    "ok": False,
                    "error": "Legacy script_type=skill records cannot be attached. Use node skills instead.",
                }
            ordered_ids = [item.id for item in node.scripts]
            if script_id not in ordered_ids:
                ordered_ids.append(script_id)
                _set_flowchart_node_scripts(session, node.id, ordered_ids)
            refreshed = (
                session.execute(
                    select(FlowchartNode)
                    .options(
                        selectinload(FlowchartNode.scripts),
                        selectinload(FlowchartNode.skills),
                    )
                    .where(FlowchartNode.id == node_id)
                )
                .scalars()
                .first()
            )
            if refreshed is None:
                return {"ok": False, "error": f"Flowchart node {node_id} was not found."}
            return {"ok": True, "node": _serialize_flowchart_node_item(refreshed)}

    @mcp.tool()
    def llmctl_unbind_flowchart_node_script(
        flowchart_id: int,
        node_id: int,
        script_id: int,
    ) -> dict[str, Any]:
        """Unbind a script from a flowchart node."""
        with session_scope() as session:
            node = (
                session.execute(
                    select(FlowchartNode)
                    .options(
                        selectinload(FlowchartNode.scripts),
                        selectinload(FlowchartNode.skills),
                    )
                    .where(FlowchartNode.id == node_id)
                )
                .scalars()
                .first()
            )
            if node is None or node.flowchart_id != flowchart_id:
                return {
                    "ok": False,
                    "error": f"Flowchart node {node_id} was not found in flowchart {flowchart_id}.",
                }
            ordered_ids = [item.id for item in node.scripts if item.id != script_id]
            _set_flowchart_node_scripts(session, node.id, ordered_ids)
            refreshed = (
                session.execute(
                    select(FlowchartNode)
                    .options(
                        selectinload(FlowchartNode.scripts),
                        selectinload(FlowchartNode.skills),
                    )
                    .where(FlowchartNode.id == node_id)
                )
                .scalars()
                .first()
            )
            if refreshed is None:
                return {"ok": False, "error": f"Flowchart node {node_id} was not found."}
            return {"ok": True, "node": _serialize_flowchart_node_item(refreshed)}

    @mcp.tool()
    def llmctl_reorder_flowchart_node_scripts(
        flowchart_id: int,
        node_id: int,
        script_ids: list[int],
    ) -> dict[str, Any]:
        """Reorder all scripts attached to a flowchart node."""
        if not isinstance(script_ids, list):
            return {"ok": False, "error": "script_ids must be an array."}
        parsed_script_ids: list[int] = []
        for index, script_id in enumerate(script_ids):
            try:
                parsed = _coerce_optional_int(
                    script_id,
                    field_name=f"script_ids[{index}]",
                    minimum=1,
                )
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}
            if parsed is None:
                return {"ok": False, "error": f"script_ids[{index}] is invalid."}
            parsed_script_ids.append(parsed)
        if len(parsed_script_ids) != len(set(parsed_script_ids)):
            return {"ok": False, "error": "script_ids cannot contain duplicates."}

        with session_scope() as session:
            node = (
                session.execute(
                    select(FlowchartNode)
                    .options(
                        selectinload(FlowchartNode.scripts),
                        selectinload(FlowchartNode.skills),
                    )
                    .where(FlowchartNode.id == node_id)
                )
                .scalars()
                .first()
            )
            if node is None or node.flowchart_id != flowchart_id:
                return {
                    "ok": False,
                    "error": f"Flowchart node {node_id} was not found in flowchart {flowchart_id}.",
                }
            errors = _validate_flowchart_utility_compatibility(
                node.node_type,
                script_ids=parsed_script_ids,
            )
            if errors:
                return {"ok": False, "error": errors[0]}
            if any(is_legacy_skill_script_type(script.script_type) for script in node.scripts):
                return {
                    "ok": False,
                    "error": (
                        "Legacy script_type=skill records cannot be reordered; "
                        "migrate to node skills."
                    ),
                }
            existing_ids = {script.id for script in node.scripts}
            if set(parsed_script_ids) != existing_ids:
                return {
                    "ok": False,
                    "error": "script_ids must include each attached script exactly once.",
                }
            _set_flowchart_node_scripts(session, node.id, parsed_script_ids)
            refreshed = (
                session.execute(
                    select(FlowchartNode)
                    .options(
                        selectinload(FlowchartNode.scripts),
                        selectinload(FlowchartNode.skills),
                    )
                    .where(FlowchartNode.id == node_id)
                )
                .scalars()
                .first()
            )
            if refreshed is None:
                return {"ok": False, "error": f"Flowchart node {node_id} was not found."}
            return {"ok": True, "node": _serialize_flowchart_node_item(refreshed)}

    @mcp.tool()
    def llmctl_get_skill(
        limit: int | None = None,
        offset: int = 0,
        order_by: str | None = "id",
        descending: bool = False,
        skill_id: int | None = None,
        name: str | None = None,
        include_versions: bool = False,
    ) -> dict[str, Any]:
        """Read/list skills and optional immutable versions."""
        if skill_id is not None and name:
            return {"ok": False, "error": "Provide only one selector: skill_id or name."}
        if skill_id is not None or name:
            with session_scope() as session:
                stmt = select(Skill).options(selectinload(Skill.versions))
                if skill_id is not None:
                    stmt = stmt.where(Skill.id == skill_id)
                else:
                    stmt = stmt.where(Skill.name == str(name or "").strip())
                skill = session.execute(stmt).scalars().first()
                if skill is None:
                    selector = f"id {skill_id}" if skill_id is not None else f"name '{name}'"
                    return {"ok": False, "error": f"Skill {selector} not found."}
                payload: dict[str, Any] = {
                    "ok": True,
                    "item": _serialize_model(skill, include_relationships=False),
                }
                latest = _latest_skill_version(skill)
                if latest is not None:
                    payload["latest_version"] = _serialize_model(
                        latest,
                        include_relationships=False,
                    )
                if include_versions:
                    payload["versions"] = [
                        _serialize_model(version, include_relationships=False)
                        for version in sorted(
                            list(skill.versions or []),
                            key=lambda item: item.id or 0,
                            reverse=True,
                        )
                    ]
                return payload

        columns = _column_map(Skill)
        stmt = select(Skill).options(selectinload(Skill.versions))
        if order_by:
            if order_by not in columns:
                raise ValueError(f"Unknown order_by column '{order_by}'.")
            order_col = columns[order_by]
            stmt = stmt.order_by(order_col.desc() if descending else order_col.asc())
        limit = _clamp_limit(DEFAULT_LIMIT if limit is None else limit, MAX_LIMIT)
        if limit is not None:
            stmt = stmt.limit(limit)
        if offset:
            stmt = stmt.offset(max(0, int(offset)))
        with session_scope() as session:
            skills = session.execute(stmt).scalars().all()
            items: list[dict[str, Any]] = []
            for skill in skills:
                latest = _latest_skill_version(skill)
                payload = _serialize_model(skill, include_relationships=False)
                payload["latest_version"] = latest.version if latest is not None else None
                payload["version_count"] = len(skill.versions or [])
                items.append(payload)
            return {"ok": True, "count": len(items), "items": items}

    @mcp.tool()
    def llmctl_create_skill(
        name: str,
        display_name: str,
        description: str,
        version: str,
        status: str = "active",
        skill_md: str | None = None,
        extra_files: list[dict[str, Any]] | None = None,
        source_ref: str | None = None,
        actor: str | None = None,
    ) -> dict[str, Any]:
        """Create/import a skill package and its first immutable version."""
        cleaned_name = str(name or "").strip()
        cleaned_display_name = str(display_name or "").strip()
        cleaned_description = str(description or "").strip()
        cleaned_version = str(version or "").strip()
        cleaned_status = str(status or "").strip().lower() or "active"

        if not cleaned_name:
            return {"ok": False, "error": "name is required."}
        if not cleaned_display_name:
            return {"ok": False, "error": "display_name is required."}
        if not cleaned_description:
            return {"ok": False, "error": "description is required."}
        if not cleaned_version:
            return {"ok": False, "error": "version is required."}
        if cleaned_status not in SKILL_STATUS_CHOICES:
            return {"ok": False, "error": "status is invalid."}

        files: list[tuple[str, str]] = []
        skill_md_content = str(skill_md or "")
        if not skill_md_content.strip():
            skill_md_content = _default_skill_markdown(
                name=cleaned_name,
                display_name=cleaned_display_name,
                description=cleaned_description,
                version=cleaned_version,
                status=cleaned_status,
            )
        files.append(("SKILL.md", skill_md_content))
        for index, entry in enumerate(extra_files or []):
            if not isinstance(entry, dict):
                return {"ok": False, "error": f"extra_files[{index}] must be an object."}
            path = entry.get("path")
            content = entry.get("content")
            if not isinstance(path, str) or not path.strip():
                return {"ok": False, "error": f"extra_files[{index}].path is required."}
            if not isinstance(content, str):
                return {"ok": False, "error": f"extra_files[{index}].content must be a string."}
            files.append((path.strip(), content))

        try:
            package = build_skill_package(
                files,
                metadata_overrides={
                    "name": cleaned_name,
                    "display_name": cleaned_display_name,
                    "description": cleaned_description,
                    "version": cleaned_version,
                    "status": cleaned_status,
                },
            )
        except SkillPackageValidationError as exc:
            return {"ok": False, "errors": format_validation_errors(exc.errors)}

        with session_scope() as session:
            try:
                result = import_skill_package_to_db(
                    session,
                    package,
                    source_type="ui",
                    source_ref=(source_ref or "").strip() or "mcp:create",
                    actor=(actor or "").strip() or None,
                )
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}
            return {
                "ok": True,
                "skill_id": result.skill_id,
                "skill_name": result.skill_name,
                "version_id": result.version_id,
                "version": result.version,
                "file_count": result.file_count,
            }

    @mcp.tool()
    def llmctl_update_skill(
        skill_id: int,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        """Update mutable skill metadata fields by id."""
        if not isinstance(patch, dict) or not patch:
            return {"ok": False, "error": "patch must be a non-empty object."}
        allowed = {"display_name", "description", "status", "source_ref", "actor"}
        unknown = sorted(set(patch).difference(allowed))
        if unknown:
            return {"ok": False, "error": f"Unknown fields: {', '.join(unknown)}"}

        with session_scope() as session:
            skill = session.get(Skill, skill_id)
            if skill is None:
                return {"ok": False, "error": f"Skill {skill_id} not found."}
            if "display_name" in patch:
                cleaned = str(patch.get("display_name") or "").strip()
                if not cleaned:
                    return {"ok": False, "error": "display_name cannot be empty."}
                skill.display_name = cleaned
            if "description" in patch:
                cleaned = str(patch.get("description") or "").strip()
                if not cleaned:
                    return {"ok": False, "error": "description cannot be empty."}
                skill.description = cleaned
            if "status" in patch:
                cleaned = str(patch.get("status") or "").strip().lower()
                if cleaned not in SKILL_STATUS_CHOICES:
                    return {"ok": False, "error": "status is invalid."}
                skill.status = cleaned
            if "source_ref" in patch:
                skill.source_ref = str(patch.get("source_ref") or "").strip() or None
            if "actor" in patch:
                skill.updated_by = str(patch.get("actor") or "").strip() or None
            return {"ok": True, "item": _serialize_model(skill, include_relationships=False)}

    @mcp.tool()
    def llmctl_archive_skill(
        skill_id: int,
    ) -> dict[str, Any]:
        """Archive a skill (metadata-only state change)."""
        with session_scope() as session:
            skill = session.get(Skill, skill_id)
            if skill is None:
                return {"ok": False, "error": f"Skill {skill_id} not found."}
            skill.status = SKILL_STATUS_ARCHIVED
            return {"ok": True, "item": _serialize_model(skill, include_relationships=False)}

    @mcp.tool()
    def llmctl_get_memory(
        limit: int | None = None,
        offset: int = 0,
        order_by: str | None = "id",
        descending: bool = False,
        memory_id: int | None = None,
    ) -> dict[str, Any]:
        """Read/list LLMCTL Studio memories.

        Use this for memory lookups by id or for listing all saved memory notes.
        """
        if memory_id is not None:
            with session_scope() as session:
                item = session.get(Memory, memory_id)
                if item is None:
                    return {"ok": False, "error": f"Memory {memory_id} not found."}
                return {"ok": True, "item": _serialize_model(item, include_relationships=False)}
        columns = _column_map(Memory)
        stmt = select(Memory)
        if order_by:
            if order_by not in columns:
                raise ValueError(f"Unknown order_by column '{order_by}'.")
            order_col = columns[order_by]
            stmt = stmt.order_by(order_col.desc() if descending else order_col.asc())
        limit = _clamp_limit(DEFAULT_LIMIT if limit is None else limit, MAX_LIMIT)
        if limit is not None:
            stmt = stmt.limit(limit)
        if offset:
            stmt = stmt.offset(max(0, int(offset)))
        with session_scope() as session:
            items = session.execute(stmt).scalars().all()
            payload = [_serialize_model(item, include_relationships=False) for item in items]
            return {"ok": True, "count": len(payload), "items": payload}

    @mcp.tool()
    def llmctl_create_memory(description: str) -> dict[str, Any]:
        """Create a memory record."""
        cleaned = (description or "").strip()
        if not cleaned:
            return {"ok": False, "error": "description is required."}
        with session_scope() as session:
            item = Memory.create(session, description=cleaned)
            return {"ok": True, "item": _serialize_model(item, include_relationships=False)}

    @mcp.tool()
    def llmctl_update_memory(memory_id: int, description: str) -> dict[str, Any]:
        """Update a memory record by id."""
        cleaned = (description or "").strip()
        if not cleaned:
            return {"ok": False, "error": "description is required."}
        with session_scope() as session:
            item = session.get(Memory, memory_id)
            if item is None:
                return {"ok": False, "error": f"Memory {memory_id} not found."}
            item.description = cleaned
            return {"ok": True, "item": _serialize_model(item, include_relationships=False)}

    @mcp.tool()
    def llmctl_delete_memory(memory_id: int) -> dict[str, Any]:
        """Delete a memory record by id."""
        with session_scope() as session:
            item = session.get(Memory, memory_id)
            if item is None:
                return {"ok": False, "error": f"Memory {memory_id} not found."}
            session.delete(item)
        return {"ok": True, "memory_id": memory_id}

    @mcp.tool()
    def llmctl_get_milestone(
        limit: int | None = None,
        offset: int = 0,
        order_by: str | None = "id",
        descending: bool = False,
        milestone_id: int | None = None,
        include_artifacts: bool = True,
        artifact_limit: int | None = 50,
    ) -> dict[str, Any]:
        """Read/list LLMCTL Studio milestones."""
        resolved_artifact_limit = _clamp_limit(
            DEFAULT_LIMIT if artifact_limit is None else artifact_limit,
            MAX_LIMIT,
        )
        if milestone_id is not None:
            with session_scope() as session:
                item = session.get(Milestone, milestone_id)
                if item is None:
                    return {"ok": False, "error": f"Milestone {milestone_id} not found."}
                payload = _serialize_model(item, include_relationships=False)
                artifact_history: list[dict[str, Any]] = []
                if include_artifacts:
                    artifact_rows = (
                        session.execute(
                            select(NodeArtifact)
                            .where(
                                NodeArtifact.artifact_type == NODE_ARTIFACT_TYPE_MILESTONE,
                                NodeArtifact.ref_id == milestone_id,
                            )
                            .order_by(NodeArtifact.created_at.desc(), NodeArtifact.id.desc())
                            .limit(resolved_artifact_limit)
                        )
                        .scalars()
                        .all()
                    )
                    artifact_history = [
                        _serialize_node_artifact_item(row) for row in artifact_rows
                    ]
                return {"ok": True, "item": payload, "artifact_history": artifact_history}
        columns = _column_map(Milestone)
        stmt = select(Milestone)
        if order_by:
            if order_by not in columns:
                raise ValueError(f"Unknown order_by column '{order_by}'.")
            order_col = columns[order_by]
            stmt = stmt.order_by(order_col.desc() if descending else order_col.asc())
        limit = _clamp_limit(DEFAULT_LIMIT if limit is None else limit, MAX_LIMIT)
        if limit is not None:
            stmt = stmt.limit(limit)
        if offset:
            stmt = stmt.offset(max(0, int(offset)))
        with session_scope() as session:
            items = session.execute(stmt).scalars().all()
            payload = [_serialize_model(item, include_relationships=False) for item in items]
            response: dict[str, Any] = {"ok": True, "count": len(payload), "items": payload}
            if include_artifacts and payload:
                milestone_ids = [
                    int(item.get("id") or 0)
                    for item in payload
                    if isinstance(item, dict) and int(item.get("id") or 0) > 0
                ]
                if milestone_ids:
                    artifact_rows = (
                        session.execute(
                            select(NodeArtifact)
                            .where(
                                NodeArtifact.artifact_type == NODE_ARTIFACT_TYPE_MILESTONE,
                                NodeArtifact.ref_id.in_(milestone_ids),
                            )
                            .order_by(NodeArtifact.created_at.desc(), NodeArtifact.id.desc())
                        )
                        .scalars()
                        .all()
                    )
                    by_ref_id: dict[int, list[dict[str, Any]]] = {}
                    for row in artifact_rows:
                        ref_id = int(row.ref_id or 0)
                        if ref_id <= 0:
                            continue
                        bucket = by_ref_id.setdefault(ref_id, [])
                        if resolved_artifact_limit is not None and len(bucket) >= resolved_artifact_limit:
                            continue
                        bucket.append(_serialize_node_artifact_item(row))
                    response["artifact_history"] = {
                        str(ref_id): items
                        for ref_id, items in by_ref_id.items()
                    }
            return response

    @mcp.tool()
    def llmctl_create_milestone(
        name: str,
        description: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        owner: str | None = None,
        start_date: str | None = None,
        due_date: str | None = None,
        progress_percent: int | None = None,
        health: str | None = None,
        success_criteria: str | None = None,
        dependencies: str | None = None,
        links: str | None = None,
        latest_update: str | None = None,
        completed: bool | None = None,
    ) -> dict[str, Any]:
        """Create a milestone record."""
        cleaned_name = (name or "").strip()
        if not cleaned_name:
            return {"ok": False, "error": "name is required."}
        status_value = _normalize_choice(
            status,
            choices=MILESTONE_STATUS_CHOICES,
            fallback=MILESTONE_STATUS_PLANNED,
        )
        priority_value = _normalize_choice(
            priority,
            choices=MILESTONE_PRIORITY_CHOICES,
            fallback=MILESTONE_PRIORITY_MEDIUM,
        )
        health_value = _normalize_choice(
            health,
            choices=MILESTONE_HEALTH_CHOICES,
            fallback=MILESTONE_HEALTH_GREEN,
        )
        try:
            start_value = _parse_optional_datetime(start_date, "start_date")
            due_value = _parse_optional_datetime(due_date, "due_date")
            progress_value = _parse_milestone_progress(progress_percent)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        if start_value and due_value and due_value < start_value:
            return {"ok": False, "error": "due_date must be on or after start_date."}
        completed_value = (
            _coerce_bool(completed)
            if completed is not None
            else status_value == MILESTONE_STATUS_DONE
        )
        if status_value == MILESTONE_STATUS_DONE:
            completed_value = True
        if completed_value:
            progress_value = max(progress_value, 100)
        with session_scope() as session:
            item = Milestone.create(
                session,
                name=cleaned_name,
                description=(description or "").strip() or None,
                status=status_value,
                priority=priority_value,
                owner=(owner or "").strip() or None,
                completed=completed_value,
                start_date=start_value,
                due_date=due_value,
                progress_percent=progress_value,
                health=health_value,
                success_criteria=(success_criteria or "").strip() or None,
                dependencies=(dependencies or "").strip() or None,
                links=(links or "").strip() or None,
                latest_update=(latest_update or "").strip() or None,
            )
            return {"ok": True, "item": _serialize_model(item, include_relationships=False)}

    @mcp.tool()
    def llmctl_update_milestone(
        milestone_id: int,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        """Update milestone fields by id using a partial patch object."""
        if not isinstance(patch, dict) or not patch:
            return {"ok": False, "error": "patch must be a non-empty object."}
        allowed = {
            "name",
            "description",
            "status",
            "priority",
            "owner",
            "completed",
            "start_date",
            "due_date",
            "progress_percent",
            "health",
            "success_criteria",
            "dependencies",
            "links",
            "latest_update",
        }
        unknown = sorted(set(patch.keys()) - allowed)
        if unknown:
            return {"ok": False, "error": f"Unknown fields: {', '.join(unknown)}"}
        with session_scope() as session:
            item = session.get(Milestone, milestone_id)
            if item is None:
                return {"ok": False, "error": f"Milestone {milestone_id} not found."}

            if "name" in patch:
                cleaned_name = str(patch.get("name") or "").strip()
                if not cleaned_name:
                    return {"ok": False, "error": "name cannot be empty."}
                item.name = cleaned_name
            if "description" in patch:
                item.description = str(patch.get("description") or "").strip() or None
            if "status" in patch:
                item.status = _normalize_choice(
                    patch.get("status"),
                    choices=MILESTONE_STATUS_CHOICES,
                    fallback=MILESTONE_STATUS_PLANNED,
                )
            if "priority" in patch:
                item.priority = _normalize_choice(
                    patch.get("priority"),
                    choices=MILESTONE_PRIORITY_CHOICES,
                    fallback=MILESTONE_PRIORITY_MEDIUM,
                )
            if "owner" in patch:
                item.owner = str(patch.get("owner") or "").strip() or None
            if "health" in patch:
                item.health = _normalize_choice(
                    patch.get("health"),
                    choices=MILESTONE_HEALTH_CHOICES,
                    fallback=MILESTONE_HEALTH_GREEN,
                )
            if "success_criteria" in patch:
                item.success_criteria = str(patch.get("success_criteria") or "").strip() or None
            if "dependencies" in patch:
                item.dependencies = str(patch.get("dependencies") or "").strip() or None
            if "links" in patch:
                item.links = str(patch.get("links") or "").strip() or None
            if "latest_update" in patch:
                item.latest_update = str(patch.get("latest_update") or "").strip() or None
            try:
                if "start_date" in patch:
                    item.start_date = _parse_optional_datetime(
                        patch.get("start_date"), "start_date"
                    )
                if "due_date" in patch:
                    item.due_date = _parse_optional_datetime(
                        patch.get("due_date"), "due_date"
                    )
                if "progress_percent" in patch:
                    item.progress_percent = _parse_milestone_progress(
                        patch.get("progress_percent")
                    )
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}

            if item.start_date and item.due_date and item.due_date < item.start_date:
                return {"ok": False, "error": "due_date must be on or after start_date."}

            if "completed" in patch:
                item.completed = _coerce_bool(patch.get("completed"))
            if item.status == MILESTONE_STATUS_DONE:
                item.completed = True
            if item.completed:
                item.progress_percent = max(item.progress_percent, 100)

            return {"ok": True, "item": _serialize_model(item, include_relationships=False)}

    @mcp.tool()
    def llmctl_delete_milestone(milestone_id: int) -> dict[str, Any]:
        """Delete a milestone record by id."""
        with session_scope() as session:
            item = session.get(Milestone, milestone_id)
            if item is None:
                return {"ok": False, "error": f"Milestone {milestone_id} not found."}
            session.delete(item)
        return {"ok": True, "milestone_id": milestone_id}

    @mcp.tool()
    def llmctl_get_plan(
        limit: int | None = None,
        offset: int = 0,
        order_by: str | None = "id",
        descending: bool = False,
        include_stages: bool = True,
        include_tasks: bool = True,
        plan_id: int | None = None,
    ) -> dict[str, Any]:
        """Read/list plans, including stage/task hierarchy when requested."""
        if plan_id is not None:
            with session_scope() as session:
                stmt = select(Plan).where(Plan.id == plan_id)
                if include_stages and include_tasks:
                    stmt = stmt.options(selectinload(Plan.stages).selectinload(PlanStage.tasks))
                elif include_stages:
                    stmt = stmt.options(selectinload(Plan.stages))
                item = session.execute(stmt).scalars().first()
                if item is None:
                    return {"ok": False, "error": f"Plan {plan_id} not found."}
                payload = _serialize_plan_item(
                    item,
                    include_stages=include_stages,
                    include_tasks=include_tasks,
                )
                return {"ok": True, "item": payload}
        columns = _column_map(Plan)
        stmt = select(Plan)
        if include_stages and include_tasks:
            stmt = stmt.options(selectinload(Plan.stages).selectinload(PlanStage.tasks))
        elif include_stages:
            stmt = stmt.options(selectinload(Plan.stages))
        if order_by:
            if order_by not in columns:
                raise ValueError(f"Unknown order_by column '{order_by}'.")
            order_col = columns[order_by]
            stmt = stmt.order_by(order_col.desc() if descending else order_col.asc())
        limit = _clamp_limit(DEFAULT_LIMIT if limit is None else limit, MAX_LIMIT)
        if limit is not None:
            stmt = stmt.limit(limit)
        if offset:
            stmt = stmt.offset(max(0, int(offset)))
        with session_scope() as session:
            items = session.execute(stmt).scalars().all()
            payload = [
                _serialize_plan_item(
                    item,
                    include_stages=include_stages,
                    include_tasks=include_tasks,
                )
                for item in items
            ]
            return {"ok": True, "count": len(payload), "items": payload}

    @mcp.tool()
    def llmctl_create_plan(
        name: str,
        description: str | None = None,
        completed_at: str | None = None,
    ) -> dict[str, Any]:
        """Create a plan record."""
        cleaned_name = (name or "").strip()
        if not cleaned_name:
            return {"ok": False, "error": "name is required."}
        try:
            completed_value = _parse_optional_datetime(completed_at, "completed_at")
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        with session_scope() as session:
            item = Plan.create(
                session,
                name=cleaned_name,
                description=(description or "").strip() or None,
                completed_at=completed_value,
            )
            payload = _serialize_plan_item(item, include_stages=True, include_tasks=True)
            return {"ok": True, "item": payload}

    @mcp.tool()
    def llmctl_update_plan(plan_id: int, patch: dict[str, Any]) -> dict[str, Any]:
        """Update a plan by id using a partial patch object."""
        if not isinstance(patch, dict) or not patch:
            return {"ok": False, "error": "patch must be a non-empty object."}
        allowed = {"name", "description", "completed_at"}
        unknown = sorted(set(patch.keys()) - allowed)
        if unknown:
            return {"ok": False, "error": f"Unknown fields: {', '.join(unknown)}"}
        with session_scope() as session:
            item = session.get(Plan, plan_id)
            if item is None:
                return {"ok": False, "error": f"Plan {plan_id} not found."}
            if "name" in patch:
                cleaned_name = str(patch.get("name") or "").strip()
                if not cleaned_name:
                    return {"ok": False, "error": "name cannot be empty."}
                item.name = cleaned_name
            if "description" in patch:
                item.description = str(patch.get("description") or "").strip() or None
            if "completed_at" in patch:
                try:
                    item.completed_at = _parse_optional_datetime(
                        patch.get("completed_at"),
                        "completed_at",
                    )
                except ValueError as exc:
                    return {"ok": False, "error": str(exc)}
            payload = _serialize_plan_item(item, include_stages=True, include_tasks=True)
            return {"ok": True, "item": payload}

    @mcp.tool()
    def llmctl_delete_plan(plan_id: int) -> dict[str, Any]:
        """Delete a plan and its child stages/tasks."""
        with session_scope() as session:
            item = session.get(Plan, plan_id)
            if item is None:
                return {"ok": False, "error": f"Plan {plan_id} not found."}
            stage_ids = (
                session.execute(select(PlanStage.id).where(PlanStage.plan_id == plan_id))
                .scalars()
                .all()
            )
            if stage_ids:
                session.execute(delete(PlanTask).where(PlanTask.plan_stage_id.in_(stage_ids)))
            session.execute(delete(PlanStage).where(PlanStage.plan_id == plan_id))
            session.delete(item)
        return {"ok": True, "plan_id": plan_id}

    @mcp.tool()
    def llmctl_create_plan_stage(
        plan_id: int,
        name: str,
        description: str | None = None,
        completed_at: str | None = None,
        position: int | None = None,
    ) -> dict[str, Any]:
        """Create a plan stage under a plan."""
        cleaned_name = (name or "").strip()
        if not cleaned_name:
            return {"ok": False, "error": "name is required."}
        try:
            completed_value = _parse_optional_datetime(completed_at, "completed_at")
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        with session_scope() as session:
            plan = session.get(Plan, plan_id)
            if plan is None:
                return {"ok": False, "error": f"Plan {plan_id} not found."}
            if position is None:
                max_position = session.execute(
                    select(func.max(PlanStage.position)).where(PlanStage.plan_id == plan_id)
                ).scalar_one()
                next_position = int(max_position or 0) + 1
            else:
                next_position = max(1, int(position))
            item = PlanStage.create(
                session,
                plan_id=plan_id,
                name=cleaned_name,
                description=(description or "").strip() or None,
                completed_at=completed_value,
                position=next_position,
            )
            return {"ok": True, "item": _serialize_model(item, include_relationships=False)}

    @mcp.tool()
    def llmctl_update_plan_stage(
        stage_id: int,
        patch: dict[str, Any],
        plan_id: int | None = None,
    ) -> dict[str, Any]:
        """Update a plan stage by id using a partial patch object."""
        if not isinstance(patch, dict) or not patch:
            return {"ok": False, "error": "patch must be a non-empty object."}
        allowed = {"name", "description", "completed_at", "position"}
        unknown = sorted(set(patch.keys()) - allowed)
        if unknown:
            return {"ok": False, "error": f"Unknown fields: {', '.join(unknown)}"}
        with session_scope() as session:
            item = session.get(PlanStage, stage_id)
            if item is None:
                return {"ok": False, "error": f"Plan stage {stage_id} not found."}
            if plan_id is not None and item.plan_id != plan_id:
                return {"ok": False, "error": f"Plan stage {stage_id} is not in plan {plan_id}."}
            if "name" in patch:
                cleaned_name = str(patch.get("name") or "").strip()
                if not cleaned_name:
                    return {"ok": False, "error": "name cannot be empty."}
                item.name = cleaned_name
            if "description" in patch:
                item.description = str(patch.get("description") or "").strip() or None
            if "completed_at" in patch:
                try:
                    item.completed_at = _parse_optional_datetime(
                        patch.get("completed_at"),
                        "completed_at",
                    )
                except ValueError as exc:
                    return {"ok": False, "error": str(exc)}
            if "position" in patch:
                try:
                    item.position = max(1, int(patch.get("position")))
                except (TypeError, ValueError):
                    return {"ok": False, "error": "position must be a positive integer."}
            return {"ok": True, "item": _serialize_model(item, include_relationships=False)}

    @mcp.tool()
    def llmctl_delete_plan_stage(
        stage_id: int,
        plan_id: int | None = None,
    ) -> dict[str, Any]:
        """Delete a plan stage and its child tasks."""
        with session_scope() as session:
            item = session.get(PlanStage, stage_id)
            if item is None:
                return {"ok": False, "error": f"Plan stage {stage_id} not found."}
            if plan_id is not None and item.plan_id != plan_id:
                return {"ok": False, "error": f"Plan stage {stage_id} is not in plan {plan_id}."}
            session.execute(delete(PlanTask).where(PlanTask.plan_stage_id == stage_id))
            session.delete(item)
        return {"ok": True, "stage_id": stage_id}

    @mcp.tool()
    def llmctl_create_plan_task(
        stage_id: int,
        name: str,
        description: str | None = None,
        completed_at: str | None = None,
        position: int | None = None,
    ) -> dict[str, Any]:
        """Create a plan task under a stage."""
        cleaned_name = (name or "").strip()
        if not cleaned_name:
            return {"ok": False, "error": "name is required."}
        try:
            completed_value = _parse_optional_datetime(completed_at, "completed_at")
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        with session_scope() as session:
            stage = session.get(PlanStage, stage_id)
            if stage is None:
                return {"ok": False, "error": f"Plan stage {stage_id} not found."}
            if position is None:
                max_position = session.execute(
                    select(func.max(PlanTask.position)).where(PlanTask.plan_stage_id == stage_id)
                ).scalar_one()
                next_position = int(max_position or 0) + 1
            else:
                next_position = max(1, int(position))
            item = PlanTask.create(
                session,
                plan_stage_id=stage_id,
                name=cleaned_name,
                description=(description or "").strip() or None,
                completed_at=completed_value,
                position=next_position,
            )
            return {"ok": True, "item": _serialize_model(item, include_relationships=False)}

    @mcp.tool()
    def llmctl_update_plan_task(
        task_id: int,
        patch: dict[str, Any],
        stage_id: int | None = None,
    ) -> dict[str, Any]:
        """Update a plan task by id using a partial patch object."""
        if not isinstance(patch, dict) or not patch:
            return {"ok": False, "error": "patch must be a non-empty object."}
        allowed = {"name", "description", "completed_at", "position"}
        unknown = sorted(set(patch.keys()) - allowed)
        if unknown:
            return {"ok": False, "error": f"Unknown fields: {', '.join(unknown)}"}
        with session_scope() as session:
            item = session.get(PlanTask, task_id)
            if item is None:
                return {"ok": False, "error": f"Plan task {task_id} not found."}
            if stage_id is not None and item.plan_stage_id != stage_id:
                return {"ok": False, "error": f"Plan task {task_id} is not in stage {stage_id}."}
            if "name" in patch:
                cleaned_name = str(patch.get("name") or "").strip()
                if not cleaned_name:
                    return {"ok": False, "error": "name cannot be empty."}
                item.name = cleaned_name
            if "description" in patch:
                item.description = str(patch.get("description") or "").strip() or None
            if "completed_at" in patch:
                try:
                    item.completed_at = _parse_optional_datetime(
                        patch.get("completed_at"),
                        "completed_at",
                    )
                except ValueError as exc:
                    return {"ok": False, "error": str(exc)}
            if "position" in patch:
                try:
                    item.position = max(1, int(patch.get("position")))
                except (TypeError, ValueError):
                    return {"ok": False, "error": "position must be a positive integer."}
            return {"ok": True, "item": _serialize_model(item, include_relationships=False)}

    @mcp.tool()
    def llmctl_delete_plan_task(
        task_id: int,
        stage_id: int | None = None,
    ) -> dict[str, Any]:
        """Delete a plan task by id."""
        with session_scope() as session:
            item = session.get(PlanTask, task_id)
            if item is None:
                return {"ok": False, "error": f"Plan task {task_id} not found."}
            if stage_id is not None and item.plan_stage_id != stage_id:
                return {"ok": False, "error": f"Plan task {task_id} is not in stage {stage_id}."}
            session.delete(item)
        return {"ok": True, "task_id": task_id}

    @mcp.tool()
    def llmctl_get_agent_task(
        hours: int = 24,
        limit: int | None = None,
        offset: int = 0,
        order_by: str | None = "finished_at",
        descending: bool = True,
    ) -> dict[str, Any]:
        """Read/list LLMCTL Studio tasks completed in the last N hours.

        Use this for "recent tasks", "what ran", "completed tasks", or time-window
        activity questions. Set hours to control the lookback window.
        For additional fields or related records, use llmctl_get_model_rows.
        Synonyms: read, list.
        Keywords: recent tasks, completed tasks, task history, activity log.
        """
        if hours <= 0:
            return {"ok": False, "error": "hours must be greater than 0."}
        columns = _column_map(AgentTask)
        cutoff = utcnow() - timedelta(hours=hours)
        stmt = select(AgentTask).where(
            AgentTask.status == "succeeded",
            AgentTask.finished_at.is_not(None),
            AgentTask.finished_at >= cutoff,
        )
        if order_by:
            if order_by not in columns:
                raise ValueError(f"Unknown order_by column '{order_by}'.")
            order_col = columns[order_by]
            stmt = stmt.order_by(order_col.desc() if descending else order_col.asc())
        limit = _clamp_limit(DEFAULT_LIMIT if limit is None else limit, MAX_LIMIT)
        if limit is not None:
            stmt = stmt.limit(limit)
        if offset:
            stmt = stmt.offset(max(0, int(offset)))
        with session_scope() as session:
            items = session.execute(stmt).scalars().all()
            payload = [_serialize_model(item, include_relationships=False) for item in items]
            return {"ok": True, "count": len(payload), "items": payload}

    @mcp.tool()
    def set_task_scripts(
        task_id: int,
        script_ids_by_type: dict[str, list[int]] | None = None,
    ) -> dict[str, Any]:
        """Replace the scripts attached to a specific task by script type.

        Use script_ids_by_type to map stages (init, post_run, etc.) to script ids.
        This overwrites existing script links for the task.
        Keywords: task scripts, task workflow, init script, post_run script.

        IDs: task_id and script ids are numeric LLMCTL Studio IDs.
        """
        with session_scope() as session:
            task = session.get(AgentTask, task_id)
            if task is None:
                return {"ok": False, "error": f"Task {task_id} not found."}
            try:
                parsed = _parse_script_ids_by_type(script_ids_by_type)
                resolved = _resolve_script_ids_by_type(session, parsed)
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}
            _set_script_links(session, agent_task_scripts, "agent_task_id", task_id, resolved)
        return {"ok": True, "task_id": task_id}

    @mcp.tool()
    def create_attachment(
        file_name: str,
        content_base64: str | None = None,
        content_text: str | None = None,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        """Create an attachment stored in LLMCTL Studio.

        Use this to upload text or binary content before attaching it to a record.
        Follow up with attach_attachment to link it to a task or step.
        Keywords: upload file, create attachment, add file, store file.
        """
        if not file_name:
            return {"ok": False, "error": "file_name is required."}
        if content_base64:
            content = _decode_base64(content_base64)
        elif content_text is not None:
            content = content_text.encode("utf-8")
        else:
            return {"ok": False, "error": "content_base64 or content_text is required."}
        with session_scope() as session:
            attachment = _create_attachment_record(
                session,
                file_name=file_name,
                content=content,
                content_type=content_type,
            )
            return {"ok": True, "item": _serialize_model(attachment)}

    @mcp.tool()
    def attach_attachment(
        target: str,
        target_id: int,
        attachment_id: int,
    ) -> dict[str, Any]:
        """Attach an existing attachment to a target model record.

        Use this after create_attachment to link files to tasks.
        Target includes task.
        Keywords: link attachment, attach file, add attachment to record.

        IDs: target_id and attachment_id are numeric LLMCTL Studio IDs.
        """
        with session_scope() as session:
            try:
                record = _resolve_attachment_target(session, target, target_id)
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}
            if record is None:
                return {"ok": False, "error": f"{target} {target_id} not found."}
            attachment = session.get(Attachment, attachment_id)
            if attachment is None:
                return {"ok": False, "error": f"Attachment {attachment_id} not found."}
            _attach_attachments(record, [attachment])
        return {"ok": True, "attachment_id": attachment_id, "target_id": target_id}

    @mcp.tool()
    def detach_attachment(
        target: str,
        target_id: int,
        attachment_id: int,
        delete_if_unused: bool = True,
    ) -> dict[str, Any]:
        """Detach an attachment from a target; optionally delete if unused.

        Use this to remove files from records while keeping or cleaning up storage.
        Set delete_if_unused to remove orphaned attachments.
        Keywords: remove attachment, unlink file, delete attachment.

        IDs: target_id and attachment_id are numeric LLMCTL Studio IDs.
        """
        removed_path: str | None = None
        with session_scope() as session:
            try:
                record = _resolve_attachment_target(session, target, target_id)
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}
            if record is None:
                return {"ok": False, "error": f"{target} {target_id} not found."}
            attachment = session.get(Attachment, attachment_id)
            if attachment is None:
                return {"ok": False, "error": f"Attachment {attachment_id} not found."}
            if attachment not in getattr(record, "attachments", []):
                return {"ok": False, "error": "Attachment not linked to target."}
            record.attachments.remove(attachment)
            session.flush()
            if delete_if_unused:
                removed_path = _delete_attachment_if_unused(session, attachment)
        if removed_path:
            remove_attachment_file(removed_path)
        return {"ok": True, "attachment_id": attachment_id, "target_id": target_id}

    @mcp.tool()
    def enqueue_task(
        agent_id: int,
        prompt: str,
        kind: str | None = None,
        script_ids_by_type: dict[str, list[int]] | None = None,
        attachment_ids: list[int] | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Queue a task for an agent, optionally with scripts and attachments.

        Use this to start a standard task run.
        Prefer enqueue_quick_task for lightweight one-off prompts.
        Keywords: queue task, run task, start task, agent task.

        IDs: agent_id is a numeric LLMCTL Studio agent ID.
        """
        if not prompt or not prompt.strip():
            return {"ok": False, "error": "Prompt is required."}
        task_kind = (kind or "").strip() or None
        prepared_attachments: list[tuple[str, bytes, str | None]] = []
        if attachments:
            for payload in attachments:
                if not isinstance(payload, dict):
                    return {"ok": False, "error": "Attachment payloads must be objects."}
                file_name = str(payload.get("file_name") or "").strip()
                content_type = payload.get("content_type")
                content_base64 = payload.get("content_base64")
                content_text = payload.get("content_text")
                if not file_name:
                    return {"ok": False, "error": "Attachment file_name is required."}
                if content_base64:
                    content = _decode_base64(content_base64)
                elif content_text is not None:
                    content = str(content_text).encode("utf-8")
                else:
                    return {"ok": False, "error": "Attachment content is required."}
                prepared_attachments.append(
                    (
                        file_name,
                        content,
                        str(content_type).strip() if content_type else None,
                    )
                )
        with session_scope() as session:
            agent = session.get(Agent, agent_id)
            if agent is None:
                return {"ok": False, "error": f"Agent {agent_id} not found."}
            attachment_records: list[Attachment] = []
            if script_ids_by_type is not None:
                try:
                    parsed = _parse_script_ids_by_type(script_ids_by_type)
                    resolved = _resolve_script_ids_by_type(session, parsed)
                except ValueError as exc:
                    return {"ok": False, "error": str(exc)}
            else:
                resolved = None
            if attachment_ids:
                rows = (
                    session.execute(select(Attachment).where(Attachment.id.in_(attachment_ids)))
                    .scalars()
                    .all()
                )
                if len(rows) != len(set(attachment_ids)):
                    return {"ok": False, "error": "One or more attachments were not found."}
                attachment_records.extend(rows)
            task_prompt = prompt
            if is_quick_task_kind(task_kind):
                task_prompt = _build_quick_task_prompt(agent, prompt)
            task = AgentTask(
                agent_id=agent_id,
                status="queued",
                prompt=task_prompt,
                kind=task_kind,
            )
            session.add(task)
            session.flush()
            if resolved is not None:
                _set_script_links(session, agent_task_scripts, "agent_task_id", task.id, resolved)
            for file_name, content, content_type in prepared_attachments:
                attachment_records.append(
                    _create_attachment_record(
                        session,
                        file_name=file_name,
                        content=content,
                        content_type=content_type,
                    )
                )
            if attachment_records:
                _attach_attachments(task, attachment_records)
            task_id = task.id
        celery_task = run_agent_task.delay(task_id)
        with session_scope() as session:
            task = session.get(AgentTask, task_id)
            if task is not None:
                task.celery_task_id = celery_task.id
        return {"ok": True, "task_id": task_id, "celery_task_id": celery_task.id}

    @mcp.tool()
    def enqueue_quick_task(
        agent_id: int,
        prompt: str,
        attachment_ids: list[int] | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Queue a quick task for an agent.

        Use this for lightweight, single-shot tasks.
        Keywords: quick task, short task, one-off task.

        IDs: agent_id is a numeric LLMCTL Studio agent ID.
        """
        return enqueue_task(
            agent_id=agent_id,
            prompt=prompt,
            kind=QUICK_TASK_KIND,
            attachment_ids=attachment_ids,
            attachments=attachments,
        )

    @mcp.tool()
    def enqueue_github_code_review(
        pr_number: int,
        pr_title: str | None = None,
        pr_url: str | None = None,
    ) -> dict[str, Any]:
        """Queue a GitHub PR code review task using configured GitHub integration.

        Requires GitHub repo and PAT to be configured in integrations.
        Use this when the user asks for a PR review.
        Keywords: code review, PR review, GitHub review.

        IDs: pr_number is the GitHub PR number (not a Studio record ID).
        """
        settings = load_integration_settings("github")
        repo = (settings.get("repo") or "").strip()
        pat = (settings.get("pat") or "").strip()
        if not repo or not pat:
            return {
                "ok": False,
                "error": "GitHub repository and PAT are required to run code reviews.",
            }
        if not pr_url and repo:
            pr_url = f"https://github.com/{repo}/pull/{pr_number}"
        with session_scope() as session:
            role = ensure_code_reviewer_role(session)
            agent = ensure_code_reviewer_agent(session, role)
            prompt = _build_code_review_prompt(
                repo=repo,
                pr_number=pr_number,
                pr_title=pr_title,
                pr_url=pr_url,
                role_prompt=role.description if role is not None else None,
            )
            task = AgentTask(
                agent_id=agent.id,
                status="queued",
                prompt=prompt,
                kind=CODE_REVIEW_TASK_KIND,
            )
            session.add(task)
            session.flush()
            task_id = task.id
        celery_task = run_agent_task.delay(task_id)
        with session_scope() as session:
            task = session.get(AgentTask, task_id)
            if task is not None:
                task.celery_task_id = celery_task.id
        return {"ok": True, "task_id": task_id, "celery_task_id": celery_task.id}

    @mcp.tool()
    def start_agent(agent_id: int) -> dict[str, Any]:
        """Start an autorun for an agent.

        Use this to kick off the agent's background run loop.
        This creates a new autorun record and starts processing.
        Keywords: start agent, autorun start, run agent.

        IDs: agent_id is a numeric LLMCTL Studio agent ID.
        """
        with session_scope() as session:
            agent = session.get(Agent, agent_id)
            if agent is None:
                return {"ok": False, "error": f"Agent {agent_id} not found."}
            active_run_id = session.execute(
                select(Run.id)
                .where(
                    Run.agent_id == agent_id,
                    Run.status.in_(RUN_ACTIVE_STATUSES),
                )
                .order_by(Run.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            if active_run_id:
                return {
                    "ok": False,
                    "error": "Agent already has an active autorun.",
                    "active_run_id": active_run_id,
                }
            run = Run(
                agent_id=agent_id,
                run_max_loops=agent.run_max_loops,
                status="starting",
                last_started_at=utcnow(),
                run_end_requested=False,
            )
            session.add(run)
            agent.last_started_at = run.last_started_at
            agent.run_end_requested = False
            session.flush()
            run_id = run.id
        task = run_agent.delay(run_id)
        with session_scope() as session:
            run = session.get(Run, run_id)
            if run is not None:
                run.task_id = task.id
                agent = session.get(Agent, run.agent_id)
                if agent is not None:
                    agent.task_id = task.id
        return {"ok": True, "run_id": run_id, "autorun_id": run_id, "task_id": task.id}

    @mcp.tool()
    def stop_agent(agent_id: int) -> dict[str, Any]:
        """Request stop for the agent's active autorun.

        Use this to stop a running autorun without deleting the agent.
        Use end_run or cancel_run for specific autoruns if needed.
        Keywords: stop agent, stop autorun, halt agent.

        IDs: agent_id is a numeric LLMCTL Studio agent ID.
        """
        task_id = None
        run_id = None
        status = "stopped"
        with session_scope() as session:
            agent = session.get(Agent, agent_id)
            if agent is None:
                return {"ok": False, "error": f"Agent {agent_id} not found."}
            run = (
                session.execute(
                    select(Run)
                    .where(
                        Run.agent_id == agent_id,
                        Run.status.in_(RUN_ACTIVE_STATUSES),
                    )
                    .order_by(Run.created_at.desc())
                    .limit(1)
                )
                .scalars()
                .first()
            )
            if run is None:
                agent.run_end_requested = False
                return {"ok": True, "agent_id": agent_id, "status": "stopped"}
            if run.task_id:
                run.run_end_requested = True
                if run.status in {"starting", "running"}:
                    run.status = "stopping"
            else:
                run.status = "stopped"
                run.run_end_requested = False
            status = run.status
            if run.task_id:
                run.last_run_task_id = run.task_id
            task_id = run.task_id
            run_id = run.id
            agent.run_end_requested = run.run_end_requested
            if run.task_id:
                agent.last_run_task_id = run.task_id
        if task_id and Config.CELERY_REVOKE_ON_STOP:
            try:
                celery_app.control.revoke(task_id, terminate=True, signal="SIGTERM")
            except Exception:
                pass
        return {
            "ok": True,
            "agent_id": agent_id,
            "run_id": run_id,
            "autorun_id": run_id,
            "status": status,
            "task_id": task_id,
        }

    @mcp.tool()
    def cancel_task(task_id: int) -> dict[str, Any]:
        """Cancel a queued or running task.

        Use this to halt an in-progress task run and mark it canceled.
        Keywords: cancel task, stop task, abort task.

        IDs: task_id is a numeric LLMCTL Studio task ID.
        """
        revoked = False
        with session_scope() as session:
            task = session.get(AgentTask, task_id)
            if task is None:
                return {"ok": False, "error": f"Task {task_id} not found."}
            if task.status not in {"queued", "running"}:
                return {
                    "ok": False,
                    "error": "Task is not running.",
                    "status": task.status,
                }
            if task.celery_task_id and Config.CELERY_REVOKE_ON_STOP:
                celery_app.control.revoke(
                    task.celery_task_id, terminate=True, signal="SIGTERM"
                )
                revoked = True
            task.status = "canceled"
            task.error = "Canceled by user."
            task.finished_at = utcnow()
            return {
                "ok": True,
                "task_id": task_id,
                "status": task.status,
                "revoked": revoked,
            }

    @mcp.tool()
    def start_run(run_id: int) -> dict[str, Any]:
        """Start an existing autorun by id.

        Use this to resume or start a specific autorun record.
        Prefer start_agent when you do not have a run_id yet.
        Keywords: start run, autorun start, resume run.

        IDs: run_id is a numeric LLMCTL Studio autorun ID.
        """
        with session_scope() as session:
            run = session.get(Run, run_id)
            if run is None:
                return {"ok": False, "error": f"Autorun {run_id} not found."}
            if run.status in RUN_ACTIVE_STATUSES:
                return {
                    "ok": False,
                    "error": "Autorun already active.",
                    "status": run.status,
                }
            agent = session.get(Agent, run.agent_id)
            if agent is None:
                return {"ok": False, "error": f"Agent {run.agent_id} not found."}
            active_run_id = (
                session.execute(
                    select(Run.id).where(
                        Run.agent_id == agent.id,
                        Run.status.in_(RUN_ACTIVE_STATUSES),
                        Run.id != run_id,
                    )
                )
                .scalar_one_or_none()
            )
            if active_run_id:
                return {
                    "ok": False,
                    "error": "Agent already has an active autorun.",
                    "active_run_id": active_run_id,
                }
            run.status = "starting"
            run.last_started_at = utcnow()
            run.run_end_requested = False
            agent.last_started_at = run.last_started_at
            agent.run_end_requested = False
            session.flush()
            run_id = run.id

        task = run_agent.delay(run_id)

        with session_scope() as session:
            run = session.get(Run, run_id)
            if run is not None:
                run.task_id = task.id
                agent = session.get(Agent, run.agent_id)
                if agent is not None:
                    agent.task_id = task.id

        return {"ok": True, "run_id": run_id, "autorun_id": run_id, "task_id": task.id}

    @mcp.tool()
    def cancel_run(run_id: int) -> dict[str, Any]:
        """Cancel a running autorun.

        Use this to force stop an autorun run immediately and revoke tasks.
        Keywords: cancel run, stop run, abort run.

        IDs: run_id is a numeric LLMCTL Studio autorun ID.
        """
        task_id = None
        with session_scope() as session:
            run = session.get(Run, run_id)
            if run is None:
                return {"ok": False, "error": f"Autorun {run_id} not found."}
            if run.status not in RUN_ACTIVE_STATUSES:
                return {
                    "ok": False,
                    "error": "Autorun already stopped.",
                    "status": run.status,
                }
            stopped_at = utcnow()
            run.status = "stopped"
            run.run_end_requested = False
            task_id = run.task_id
            if task_id:
                run.last_run_task_id = task_id
                run.task_id = None
            run.last_stopped_at = stopped_at
            agent = session.get(Agent, run.agent_id)
            if agent is not None:
                agent.run_end_requested = False
                if task_id:
                    agent.last_run_task_id = task_id
                agent.task_id = None
                agent.last_stopped_at = stopped_at

        if task_id:
            try:
                celery_app.control.revoke(task_id, terminate=True, signal="SIGTERM")
            except Exception:
                pass

        return {
            "ok": True,
            "run_id": run_id,
            "autorun_id": run_id,
            "status": "stopped",
            "task_id": task_id,
        }

    @mcp.tool()
    def end_run(run_id: int) -> dict[str, Any]:
        """Request graceful stop for a running autorun.

        Use this to signal the autorun to finish current work and stop.
        This is gentler than cancel_run.
        Keywords: end run, graceful stop, stop after current.

        IDs: run_id is a numeric LLMCTL Studio autorun ID.
        """
        with session_scope() as session:
            run = session.get(Run, run_id)
            if run is None:
                return {"ok": False, "error": f"Autorun {run_id} not found."}
            if run.status not in RUN_ACTIVE_STATUSES:
                return {
                    "ok": False,
                    "error": "Autorun already stopped.",
                    "status": run.status,
                }
            run.run_end_requested = True
            if run.status in {"starting", "running"}:
                run.status = "stopping"
            agent = session.get(Agent, run.agent_id)
            if agent is not None:
                agent.run_end_requested = True
        return {"ok": True, "run_id": run_id, "autorun_id": run_id, "status": "stopping"}

    @mcp.tool()
    def set_run_active(run_id: int, enabled: bool) -> dict[str, Any]:
        """Start or cancel an autorun based on enabled flag.

        Use enabled=true to start; enabled=false to cancel.
        This is a convenience wrapper for start_run/cancel_run.
        Keywords: toggle run, enable run, disable run.

        IDs: run_id is a numeric LLMCTL Studio autorun ID.
        """
        if enabled:
            return start_run(run_id)
        return cancel_run(run_id)

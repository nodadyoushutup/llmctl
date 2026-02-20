from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from core.integrated_mcp import INTEGRATED_MCP_LLMCTL_KEY
from core.models import (
    FLOWCHART_EDGE_MODE_DOTTED,
    FLOWCHART_EDGE_MODE_SOLID,
    FLOWCHART_NODE_TYPE_CHOICES,
    FLOWCHART_NODE_TYPE_DECISION,
    FLOWCHART_NODE_TYPE_END,
    FLOWCHART_NODE_TYPE_FLOWCHART,
    FLOWCHART_NODE_TYPE_MEMORY,
    FLOWCHART_NODE_TYPE_MILESTONE,
    FLOWCHART_NODE_TYPE_PLAN,
    FLOWCHART_NODE_TYPE_RAG,
    FLOWCHART_NODE_TYPE_START,
    FLOWCHART_NODE_TYPE_TASK,
    Flowchart,
    FlowchartEdge,
    FlowchartNode,
    MCPServer,
)
from services import tasks as runtime_tasks


FLOW_MIGRATION_CONTRACT_VERSION = "v1"
FLOWCHART_FAN_IN_MODE_ALL = "all"
FLOWCHART_FAN_IN_MODE_ANY = "any"
FLOWCHART_FAN_IN_MODE_CUSTOM = "custom"
FLOWCHART_DECISION_NO_MATCH_POLICY_FAIL = "fail"
FLOWCHART_DECISION_NO_MATCH_POLICY_FALLBACK = "fallback"

FLOWCHART_NODE_TYPE_WITH_REF = {
    FLOWCHART_NODE_TYPE_FLOWCHART,
    FLOWCHART_NODE_TYPE_PLAN,
    FLOWCHART_NODE_TYPE_MILESTONE,
    FLOWCHART_NODE_TYPE_MEMORY,
}
FLOWCHART_NODE_TYPE_REQUIRES_REF = {
    FLOWCHART_NODE_TYPE_FLOWCHART,
    FLOWCHART_NODE_TYPE_PLAN,
    FLOWCHART_NODE_TYPE_MILESTONE,
}
FLOWCHART_NODE_UTILITY_COMPATIBILITY = {
    FLOWCHART_NODE_TYPE_START: {
        "model": False,
        "mcp": False,
        "scripts": False,
        "skills": False,
        "attachments": False,
    },
    FLOWCHART_NODE_TYPE_END: {
        "model": False,
        "mcp": False,
        "scripts": False,
        "skills": False,
        "attachments": False,
    },
    FLOWCHART_NODE_TYPE_FLOWCHART: {
        "model": False,
        "mcp": False,
        "scripts": False,
        "skills": False,
        "attachments": False,
    },
    FLOWCHART_NODE_TYPE_TASK: {
        "model": True,
        "mcp": True,
        "scripts": True,
        "skills": True,
        "attachments": True,
    },
    FLOWCHART_NODE_TYPE_PLAN: {
        "model": True,
        "mcp": True,
        "scripts": True,
        "skills": True,
        "attachments": True,
    },
    FLOWCHART_NODE_TYPE_MILESTONE: {
        "model": True,
        "mcp": True,
        "scripts": True,
        "skills": True,
        "attachments": True,
    },
    FLOWCHART_NODE_TYPE_MEMORY: {
        "model": True,
        "mcp": True,
        "scripts": True,
        "skills": True,
        "attachments": True,
    },
    FLOWCHART_NODE_TYPE_DECISION: {
        "model": False,
        "mcp": False,
        "scripts": False,
        "skills": False,
        "attachments": False,
    },
    FLOWCHART_NODE_TYPE_RAG: {
        "model": True,
        "mcp": False,
        "scripts": False,
        "skills": False,
        "attachments": False,
    },
}


@dataclass
class MigrationIssue:
    code: str
    message: str
    severity: str = "error"
    node_id: int | None = None
    edge_id: int | None = None

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
        }
        if self.node_id is not None:
            payload["node_id"] = self.node_id
        if self.edge_id is not None:
            payload["edge_id"] = self.edge_id
        return payload


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _snapshot_hash(snapshot: dict[str, Any]) -> str:
    return hashlib.sha256(_json_dumps(snapshot).encode("utf-8")).hexdigest()


def _parse_json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return dict(parsed)
    return {}


def _normalize_edge_mode(value: Any) -> str:
    cleaned = str(value or "").strip().lower()
    if cleaned == FLOWCHART_EDGE_MODE_DOTTED:
        return FLOWCHART_EDGE_MODE_DOTTED
    return FLOWCHART_EDGE_MODE_SOLID


def _coerce_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _node_supports(node_type: str, key: str) -> bool:
    compatibility = FLOWCHART_NODE_UTILITY_COMPATIBILITY.get(node_type)
    if compatibility is None:
        return False
    return bool(compatibility.get(key))


def _policy_severity(strict_policy: bool) -> str:
    return "error" if strict_policy else "warning"


def build_flowchart_migration_snapshot(flowchart: Flowchart) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    for node in sorted(list(flowchart.nodes), key=lambda item: int(item.id)):
        nodes.append(
            {
                "id": int(node.id),
                "node_type": str(node.node_type or "").strip().lower(),
                "ref_id": int(node.ref_id) if node.ref_id is not None else None,
                "title": node.title,
                "x": float(node.x),
                "y": float(node.y),
                "model_id": int(node.model_id) if node.model_id is not None else None,
                "config": _parse_json_dict(node.config_json),
                "mcp_server_ids": sorted(int(server.id) for server in list(node.mcp_servers)),
                "script_ids": sorted(int(script.id) for script in list(node.scripts)),
                "skill_ids": sorted(int(skill.id) for skill in list(node.skills)),
                "attachment_ids": sorted(
                    int(attachment.id) for attachment in list(node.attachments)
                ),
            }
        )

    edges: list[dict[str, Any]] = []
    for edge in sorted(list(flowchart.edges), key=lambda item: int(item.id)):
        edges.append(
            {
                "id": int(edge.id),
                "source_node_id": int(edge.source_node_id),
                "target_node_id": int(edge.target_node_id),
                "source_handle_id": edge.source_handle_id,
                "target_handle_id": edge.target_handle_id,
                "edge_mode": _normalize_edge_mode(edge.edge_mode),
                "condition_key": str(edge.condition_key or "").strip() or None,
                "label": edge.label,
            }
        )

    return {
        "flowchart": {
            "id": int(flowchart.id),
            "name": str(flowchart.name or "").strip() or f"Flowchart {flowchart.id}",
        },
        "nodes": nodes,
        "edges": edges,
    }


def _next_connector_id(used_ids: set[str]) -> str:
    index = 1
    while True:
        candidate = f"connector_{index}"
        if candidate not in used_ids:
            used_ids.add(candidate)
            return candidate
        index += 1


def _normalize_node_routing_config(
    node_id: int,
    node_type: str,
    config: dict[str, Any],
    issues: list[MigrationIssue],
) -> dict[str, Any]:
    payload = dict(config)

    fan_in_mode = str(payload.get("fan_in_mode") or "").strip().lower()
    if fan_in_mode in {"", FLOWCHART_FAN_IN_MODE_ALL}:
        payload.pop("fan_in_mode", None)
        payload.pop("fan_in_custom_count", None)
    elif fan_in_mode == FLOWCHART_FAN_IN_MODE_ANY:
        payload["fan_in_mode"] = FLOWCHART_FAN_IN_MODE_ANY
        payload.pop("fan_in_custom_count", None)
    elif fan_in_mode in {"custom_n", "custom-n", FLOWCHART_FAN_IN_MODE_CUSTOM}:
        fan_in_custom_count = _coerce_optional_int(payload.get("fan_in_custom_count"))
        if fan_in_custom_count is None or fan_in_custom_count <= 0:
            issues.append(
                MigrationIssue(
                    code="transform.invalid_fan_in_custom_count",
                    message=(
                        "fan_in_custom_count must be a positive integer when fan_in_mode is custom."
                    ),
                    severity="error",
                    node_id=node_id,
                )
            )
            fan_in_custom_count = 1
        payload["fan_in_mode"] = FLOWCHART_FAN_IN_MODE_CUSTOM
        payload["fan_in_custom_count"] = fan_in_custom_count
    else:
        issues.append(
            MigrationIssue(
                code="transform.invalid_fan_in_mode",
                message=f"Unsupported fan_in_mode '{fan_in_mode}'.",
                severity="error",
                node_id=node_id,
            )
        )

    fallback_condition_key = str(payload.get("fallback_condition_key") or "").strip()
    if fallback_condition_key:
        payload["fallback_condition_key"] = fallback_condition_key
    else:
        payload.pop("fallback_condition_key", None)

    raw_no_match_policy = str(payload.get("no_match_policy") or "").strip().lower()
    if not raw_no_match_policy:
        if fallback_condition_key:
            payload["no_match_policy"] = FLOWCHART_DECISION_NO_MATCH_POLICY_FALLBACK
            issues.append(
                MigrationIssue(
                    code="transform.inferred_no_match_policy",
                    message=(
                        "Inferred no_match_policy=fallback from fallback_condition_key."
                    ),
                    severity="warning",
                    node_id=node_id,
                )
            )
        else:
            payload.pop("no_match_policy", None)
    elif raw_no_match_policy in {
        FLOWCHART_DECISION_NO_MATCH_POLICY_FAIL,
        FLOWCHART_DECISION_NO_MATCH_POLICY_FALLBACK,
    }:
        payload["no_match_policy"] = raw_no_match_policy
    else:
        issues.append(
            MigrationIssue(
                code="transform.invalid_no_match_policy",
                message=f"Unsupported no_match_policy '{raw_no_match_policy}'.",
                severity="error",
                node_id=node_id,
            )
        )

    if node_type == FLOWCHART_NODE_TYPE_TASK and "route_key_path" in payload:
        payload.pop("route_key_path", None)
        issues.append(
            MigrationIssue(
                code="transform.removed_legacy_route_key_path",
                message="Removed legacy route_key_path from task node config.",
                severity="warning",
                node_id=node_id,
            )
        )

    if node_type == FLOWCHART_NODE_TYPE_DECISION and "route_field_path" in payload:
        payload.pop("route_field_path", None)
        issues.append(
            MigrationIssue(
                code="transform.removed_legacy_route_field_path",
                message="Removed legacy route_field_path from decision node config.",
                severity="warning",
                node_id=node_id,
            )
        )

    return payload


def _transform_snapshot(
    snapshot: dict[str, Any],
    *,
    strict_policy: bool,
) -> tuple[dict[str, Any], list[MigrationIssue]]:
    issues: list[MigrationIssue] = []
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    for node in list(snapshot.get("nodes") or []):
        node_payload = dict(node)
        node_id = int(node_payload["id"])
        node_type = str(node_payload.get("node_type") or "").strip().lower()
        config = _parse_json_dict(node_payload.get("config"))
        node_payload["config"] = _normalize_node_routing_config(
            node_id,
            node_type,
            config,
            issues,
        )
        nodes.append(node_payload)

    node_type_by_id = {
        int(node["id"]): str(node.get("node_type") or "").strip().lower() for node in nodes
    }

    for edge in list(snapshot.get("edges") or []):
        edge_payload = dict(edge)
        edge_id = int(edge_payload["id"])
        normalized_mode = _normalize_edge_mode(edge_payload.get("edge_mode"))
        original_mode = str(edge_payload.get("edge_mode") or "").strip().lower()
        if original_mode not in {FLOWCHART_EDGE_MODE_SOLID, FLOWCHART_EDGE_MODE_DOTTED}:
            issues.append(
                MigrationIssue(
                    code="transform.defaulted_edge_mode",
                    message="Edge mode defaulted to solid from invalid or missing value.",
                    severity="warning",
                    edge_id=edge_id,
                )
            )
        edge_payload["edge_mode"] = normalized_mode
        edge_payload["condition_key"] = str(edge_payload.get("condition_key") or "").strip() or None
        source_node_id = int(edge_payload["source_node_id"])
        source_node_type = node_type_by_id.get(source_node_id, "")
        if (
            source_node_type != FLOWCHART_NODE_TYPE_DECISION
            and edge_payload["condition_key"]
        ):
            issues.append(
                MigrationIssue(
                    code="policy.non_decision_condition_key",
                    message=(
                        "condition_key is only supported on decision solid outgoing edges."
                    ),
                    severity=_policy_severity(strict_policy),
                    edge_id=edge_id,
                    node_id=source_node_id,
                )
            )
        edges.append(edge_payload)

    decision_edges_by_source: dict[int, list[dict[str, Any]]] = {}
    for edge in edges:
        if edge.get("edge_mode") != FLOWCHART_EDGE_MODE_SOLID:
            continue
        source_node_id = int(edge["source_node_id"])
        if node_type_by_id.get(source_node_id) != FLOWCHART_NODE_TYPE_DECISION:
            continue
        decision_edges_by_source.setdefault(source_node_id, []).append(edge)

    node_payload_by_id = {int(node["id"]): node for node in nodes}
    for node_id, node_payload in node_payload_by_id.items():
        node_type = str(node_payload.get("node_type") or "")
        if node_type != FLOWCHART_NODE_TYPE_DECISION:
            continue
        solid_edges = decision_edges_by_source.get(node_id, [])
        used_connector_ids: set[str] = set()
        for edge in solid_edges:
            condition_key = str(edge.get("condition_key") or "").strip()
            if not condition_key:
                edge["condition_key"] = _next_connector_id(used_connector_ids)
                issues.append(
                    MigrationIssue(
                        code="transform.generated_decision_connector_id",
                        message=(
                            "Generated missing decision connector_id for solid outgoing edge."
                        ),
                        severity="warning",
                        edge_id=int(edge["id"]),
                        node_id=node_id,
                    )
                )
                continue
            if condition_key in used_connector_ids:
                edge["condition_key"] = _next_connector_id(used_connector_ids)
                issues.append(
                    MigrationIssue(
                        code="transform.deduped_decision_connector_id",
                        message=(
                            "Generated replacement connector_id for duplicate decision connector."
                        ),
                        severity="warning",
                        edge_id=int(edge["id"]),
                        node_id=node_id,
                    )
                )
                continue
            used_connector_ids.add(condition_key)

        connector_ids = [
            str(edge.get("condition_key") or "").strip()
            for edge in solid_edges
            if str(edge.get("condition_key") or "").strip()
        ]
        existing_entries = node_payload["config"].get("decision_conditions")
        existing_text_by_connector: dict[str, str] = {}
        if isinstance(existing_entries, list):
            for item in existing_entries:
                if not isinstance(item, dict):
                    continue
                connector_id = str(item.get("connector_id") or "").strip()
                if not connector_id:
                    continue
                existing_text_by_connector[connector_id] = str(
                    item.get("condition_text") or ""
                ).strip()
        node_payload["config"]["decision_conditions"] = [
            {
                "connector_id": connector_id,
                "condition_text": existing_text_by_connector.get(connector_id, ""),
            }
            for connector_id in connector_ids
        ]

    transformed_snapshot = {
        "flowchart": dict(snapshot.get("flowchart") or {}),
        "nodes": nodes,
        "edges": edges,
    }
    return transformed_snapshot, issues


def _validate_transformed_snapshot(
    transformed_snapshot: dict[str, Any],
    *,
    llmctl_mcp_server_id: int | None,
    strict_policy: bool,
) -> list[MigrationIssue]:
    issues: list[MigrationIssue] = []

    nodes = list(transformed_snapshot.get("nodes") or [])
    edges = list(transformed_snapshot.get("edges") or [])

    node_ids: set[int] = set()
    node_type_by_id: dict[int, str] = {}
    incoming_solid_count: dict[int, int] = {}
    outgoing_count: dict[int, int] = {}
    decision_solid_condition_keys: dict[int, list[str]] = {}

    for node in nodes:
        node_id = int(node["id"])
        node_ids.add(node_id)
        node_type = str(node.get("node_type") or "").strip().lower()
        node_type_by_id[node_id] = node_type
        incoming_solid_count.setdefault(node_id, 0)
        outgoing_count.setdefault(node_id, 0)

        if node_type not in FLOWCHART_NODE_TYPE_CHOICES:
            issues.append(
                MigrationIssue(
                    code="validation.unknown_node_type",
                    message=f"Unknown node_type '{node_type}'.",
                    node_id=node_id,
                )
            )
            continue

        ref_id = node.get("ref_id")
        if node_type in FLOWCHART_NODE_TYPE_REQUIRES_REF and ref_id is None:
            issues.append(
                MigrationIssue(
                    code="validation.missing_ref_id",
                    message="ref_id is required for this node type.",
                    node_id=node_id,
                )
            )
        if node_type not in FLOWCHART_NODE_TYPE_WITH_REF and ref_id is not None:
            issues.append(
                MigrationIssue(
                    code="validation.unexpected_ref_id",
                    message="ref_id is not supported for this node type.",
                    node_id=node_id,
                )
            )

        config_payload = _parse_json_dict(node.get("config"))
        if (
            node_type == FLOWCHART_NODE_TYPE_TASK
            and not str(config_payload.get("task_prompt") or "").strip()
        ):
            issues.append(
                MigrationIssue(
                    code="validation.task_prompt_required",
                    message="Task nodes require config.task_prompt.",
                    node_id=node_id,
                )
            )

        model_id = node.get("model_id")
        if model_id is not None and not _node_supports(node_type, "model"):
            issues.append(
                MigrationIssue(
                    code="policy.unsupported_model_binding",
                    message="Node type does not support model bindings.",
                    severity=_policy_severity(strict_policy),
                    node_id=node_id,
                )
            )
        mcp_server_ids = list(node.get("mcp_server_ids") or [])
        if mcp_server_ids and not _node_supports(node_type, "mcp"):
            issues.append(
                MigrationIssue(
                    code="policy.unsupported_mcp_binding",
                    message="Node type does not support MCP server bindings.",
                    severity=_policy_severity(strict_policy),
                    node_id=node_id,
                )
            )
        script_ids = list(node.get("script_ids") or [])
        if script_ids and not _node_supports(node_type, "scripts"):
            issues.append(
                MigrationIssue(
                    code="policy.unsupported_script_binding",
                    message="Node type does not support script bindings.",
                    severity=_policy_severity(strict_policy),
                    node_id=node_id,
                )
            )
        skill_ids = list(node.get("skill_ids") or [])
        if skill_ids and not _node_supports(node_type, "skills"):
            issues.append(
                MigrationIssue(
                    code="policy.unsupported_skill_binding",
                    message="Node type does not support skill bindings.",
                    severity=_policy_severity(strict_policy),
                    node_id=node_id,
                )
            )
        attachment_ids = list(node.get("attachment_ids") or [])
        if attachment_ids and not _node_supports(node_type, "attachments"):
            issues.append(
                MigrationIssue(
                    code="policy.unsupported_attachment_binding",
                    message="Node type does not support attachment bindings.",
                    severity=_policy_severity(strict_policy),
                    node_id=node_id,
                )
            )

        if node_type == FLOWCHART_NODE_TYPE_MEMORY:
            if not mcp_server_ids:
                issues.append(
                    MigrationIssue(
                        code="policy.memory_missing_llmctl_mcp",
                        message="Memory nodes require system-managed LLMCTL MCP binding.",
                        severity=_policy_severity(strict_policy),
                        node_id=node_id,
                    )
                )
            elif (
                llmctl_mcp_server_id is not None
                and int(llmctl_mcp_server_id) not in {int(item) for item in mcp_server_ids}
            ):
                issues.append(
                    MigrationIssue(
                        code="policy.memory_missing_llmctl_mcp",
                        message="Memory nodes must include system-managed LLMCTL MCP binding.",
                        severity=_policy_severity(strict_policy),
                        node_id=node_id,
                    )
                )

    start_node_ids = [
        int(node["id"])
        for node in nodes
        if str(node.get("node_type") or "").strip().lower() == FLOWCHART_NODE_TYPE_START
    ]
    if len(start_node_ids) != 1:
        issues.append(
            MigrationIssue(
                code="validation.start_node_count",
                message=f"Flowchart must have exactly one start node; found {len(start_node_ids)}.",
            )
        )

    for edge in edges:
        edge_id = int(edge["id"])
        source_node_id = int(edge["source_node_id"])
        target_node_id = int(edge["target_node_id"])
        edge_mode = _normalize_edge_mode(edge.get("edge_mode"))
        condition_key = str(edge.get("condition_key") or "").strip()

        if source_node_id not in node_ids:
            issues.append(
                MigrationIssue(
                    code="validation.edge_source_missing",
                    message=f"Edge source node {source_node_id} does not exist.",
                    edge_id=edge_id,
                )
            )
            continue
        if target_node_id not in node_ids:
            issues.append(
                MigrationIssue(
                    code="validation.edge_target_missing",
                    message=f"Edge target node {target_node_id} does not exist.",
                    edge_id=edge_id,
                )
            )
            continue

        outgoing_count[source_node_id] = outgoing_count.get(source_node_id, 0) + 1
        if edge_mode == FLOWCHART_EDGE_MODE_SOLID:
            incoming_solid_count[target_node_id] = incoming_solid_count.get(target_node_id, 0) + 1

        source_node_type = node_type_by_id.get(source_node_id, "")
        if source_node_type == FLOWCHART_NODE_TYPE_DECISION and edge_mode == FLOWCHART_EDGE_MODE_SOLID:
            if not condition_key:
                issues.append(
                    MigrationIssue(
                        code="validation.decision_condition_key_required",
                        message="Decision solid outgoing edges require condition_key.",
                        edge_id=edge_id,
                        node_id=source_node_id,
                    )
                )
            decision_solid_condition_keys.setdefault(source_node_id, []).append(condition_key)
        elif condition_key:
            issues.append(
                MigrationIssue(
                    code="policy.non_decision_condition_key",
                    message="Only decision solid outgoing edges may define condition_key.",
                    severity=_policy_severity(strict_policy),
                    edge_id=edge_id,
                    node_id=source_node_id,
                )
            )

    for node in nodes:
        node_id = int(node["id"])
        node_type = str(node.get("node_type") or "").strip().lower()
        config = _parse_json_dict(node.get("config"))

        fan_in_mode = str(config.get("fan_in_mode") or "").strip().lower()
        if fan_in_mode in {"custom_n", "custom-n"}:
            fan_in_mode = FLOWCHART_FAN_IN_MODE_CUSTOM
        if fan_in_mode == FLOWCHART_FAN_IN_MODE_CUSTOM:
            fan_in_custom_count = _coerce_optional_int(config.get("fan_in_custom_count"))
            if fan_in_custom_count is None or fan_in_custom_count <= 0:
                issues.append(
                    MigrationIssue(
                        code="validation.fan_in_custom_count_required",
                        message="fan_in_custom_count must be a positive integer when fan_in_mode=custom.",
                        node_id=node_id,
                    )
                )
            else:
                parent_count = incoming_solid_count.get(node_id, 0)
                if parent_count == 0 or fan_in_custom_count > parent_count:
                    issues.append(
                        MigrationIssue(
                            code="validation.fan_in_custom_count_range",
                            message=(
                                f"fan_in_custom_count ({fan_in_custom_count}) must be <= solid parent count ({parent_count})."
                            ),
                            node_id=node_id,
                        )
                    )

        if node_type == FLOWCHART_NODE_TYPE_END and outgoing_count.get(node_id, 0) > 0:
            issues.append(
                MigrationIssue(
                    code="validation.end_node_outgoing_edges",
                    message="End nodes cannot have outgoing edges.",
                    node_id=node_id,
                )
            )

        if node_type == FLOWCHART_NODE_TYPE_DECISION:
            outgoing_keys = [
                key
                for key in decision_solid_condition_keys.get(node_id, [])
                if str(key).strip()
            ]
            if not outgoing_keys:
                issues.append(
                    MigrationIssue(
                        code="validation.decision_missing_solid_outgoing",
                        message="Decision nodes require at least one solid outgoing edge.",
                        node_id=node_id,
                    )
                )
            if len(outgoing_keys) != len(set(outgoing_keys)):
                issues.append(
                    MigrationIssue(
                        code="validation.decision_duplicate_condition_keys",
                        message="Decision node has duplicate condition_key values.",
                        node_id=node_id,
                    )
                )
            fallback_condition_key = str(config.get("fallback_condition_key") or "").strip()
            if fallback_condition_key and fallback_condition_key not in set(outgoing_keys):
                issues.append(
                    MigrationIssue(
                        code="validation.decision_fallback_missing_connector",
                        message="fallback_condition_key does not match a solid outgoing connector.",
                        node_id=node_id,
                    )
                )
            no_match_policy = str(config.get("no_match_policy") or "").strip().lower()
            if (
                no_match_policy == FLOWCHART_DECISION_NO_MATCH_POLICY_FALLBACK
                and not fallback_condition_key
            ):
                issues.append(
                    MigrationIssue(
                        code="validation.decision_fallback_policy_requires_connector",
                        message="no_match_policy=fallback requires fallback_condition_key.",
                        node_id=node_id,
                    )
                )

    return issues


def _run_dry_execution_checks(
    transformed_snapshot: dict[str, Any],
) -> list[MigrationIssue]:
    issues: list[MigrationIssue] = []

    nodes = list(transformed_snapshot.get("nodes") or [])
    edges = list(transformed_snapshot.get("edges") or [])
    node_by_id = {int(node["id"]): node for node in nodes}

    solid_parent_ids_by_target: dict[int, list[int]] = {}
    outgoing_by_source: dict[int, list[dict[str, Any]]] = {}
    for edge in edges:
        source_node_id = int(edge["source_node_id"])
        target_node_id = int(edge["target_node_id"])
        outgoing_by_source.setdefault(source_node_id, []).append(edge)
        if _normalize_edge_mode(edge.get("edge_mode")) == FLOWCHART_EDGE_MODE_SOLID:
            solid_parent_ids_by_target.setdefault(target_node_id, []).append(source_node_id)

    for node_id, node in node_by_id.items():
        node_type = str(node.get("node_type") or "").strip().lower()
        node_config = _parse_json_dict(node.get("config"))
        outgoing_edges = list(outgoing_by_source.get(node_id, []))
        solid_parent_ids = list(solid_parent_ids_by_target.get(node_id, []))

        try:
            runtime_tasks._resolve_flowchart_fan_in_requirement(
                node_id=node_id,
                node_config=node_config,
                solid_parent_ids=solid_parent_ids,
            )
        except Exception as exc:  # pragma: no cover - defensive
            issues.append(
                MigrationIssue(
                    code="dry_run.fan_in_resolution_failed",
                    message=str(exc),
                    node_id=node_id,
                )
            )

        try:
            if node_type == FLOWCHART_NODE_TYPE_DECISION:
                decision_connectors = [
                    str(edge.get("condition_key") or "").strip()
                    for edge in outgoing_edges
                    if _normalize_edge_mode(edge.get("edge_mode")) == FLOWCHART_EDGE_MODE_SOLID
                    and str(edge.get("condition_key") or "").strip()
                ]
                if decision_connectors:
                    first_connector = decision_connectors[0]
                    runtime_tasks._resolve_flowchart_outgoing_edges(
                        node_type=node_type,
                        node_config=node_config,
                        outgoing_edges=outgoing_edges,
                        routing_state={
                            "matched_connector_ids": [first_connector],
                            "route_key": first_connector,
                            "no_match": False,
                        },
                    )
                if str(node_config.get("fallback_condition_key") or "").strip():
                    runtime_tasks._resolve_flowchart_outgoing_edges(
                        node_type=node_type,
                        node_config=node_config,
                        outgoing_edges=outgoing_edges,
                        routing_state={
                            "matched_connector_ids": [],
                            "no_match": True,
                        },
                    )
            else:
                route_key = str(node_config.get("route_key") or "").strip()
                if route_key:
                    runtime_tasks._resolve_flowchart_outgoing_edges(
                        node_type=node_type,
                        node_config=node_config,
                        outgoing_edges=outgoing_edges,
                        routing_state={"route_key": route_key},
                    )
        except Exception as exc:
            issues.append(
                MigrationIssue(
                    code="dry_run.route_resolution_failed",
                    message=str(exc),
                    node_id=node_id,
                )
            )

    return issues


def analyze_flowchart_migration_snapshot(
    snapshot: dict[str, Any],
    *,
    llmctl_mcp_server_id: int | None,
    strict_policy: bool = True,
) -> dict[str, Any]:
    before_snapshot = {
        "flowchart": dict(snapshot.get("flowchart") or {}),
        "nodes": [dict(item) for item in list(snapshot.get("nodes") or [])],
        "edges": [dict(item) for item in list(snapshot.get("edges") or [])],
    }
    before_hash = _snapshot_hash(before_snapshot)

    transformed_snapshot, transform_issues = _transform_snapshot(
        before_snapshot,
        strict_policy=strict_policy,
    )
    validation_issues = _validate_transformed_snapshot(
        transformed_snapshot,
        llmctl_mcp_server_id=llmctl_mcp_server_id,
        strict_policy=strict_policy,
    )
    dry_run_issues = _run_dry_execution_checks(transformed_snapshot)

    all_issues = [*transform_issues, *validation_issues, *dry_run_issues]
    error_codes = sorted(
        {
            issue.code
            for issue in all_issues
            if str(issue.severity).strip().lower() == "error"
        }
    )
    warning_codes = sorted(
        {
            issue.code
            for issue in all_issues
            if str(issue.severity).strip().lower() != "error"
        }
    )

    after_hash = _snapshot_hash(transformed_snapshot)
    changed = before_hash != after_hash
    gate_status = "ready" if not error_codes else "blocked"
    rollback_trigger_codes = []
    if gate_status != "ready":
        rollback_trigger_codes.append("compatibility_gate_blocked")
        rollback_trigger_codes.extend(error_codes)

    return {
        "contract_version": FLOW_MIGRATION_CONTRACT_VERSION,
        "generated_at": _utc_iso(),
        "flowchart": dict(before_snapshot.get("flowchart") or {}),
        "changed": changed,
        "before_hash": before_hash,
        "after_hash": after_hash,
        "compatibility_gate": {
            "status": gate_status,
            "blocking_issue_codes": error_codes,
            "warning_issue_codes": warning_codes,
            "error_count": len(error_codes),
            "warning_count": len(warning_codes),
        },
        "issues": [issue.to_payload() for issue in all_issues],
        "rollback": {
            "required": gate_status != "ready",
            "trigger_codes": rollback_trigger_codes,
            "pre_migration_hash": before_hash,
            "post_migration_hash": after_hash,
        },
        "pre_migration_snapshot": before_snapshot,
        "post_migration_snapshot": transformed_snapshot,
    }


def apply_flowchart_snapshot_migration(
    _session: Session,
    flowchart: Flowchart,
    transformed_snapshot: dict[str, Any],
) -> dict[str, int]:
    node_by_id = {int(node.id): node for node in list(flowchart.nodes)}
    edge_by_id = {int(edge.id): edge for edge in list(flowchart.edges)}

    updated_nodes = 0
    updated_edges = 0

    for node_payload in list(transformed_snapshot.get("nodes") or []):
        node_id = int(node_payload["id"])
        node = node_by_id.get(node_id)
        if node is None:
            continue
        config_json = json.dumps(
            _parse_json_dict(node_payload.get("config")),
            sort_keys=True,
        )
        if str(node.config_json or "") != config_json:
            node.config_json = config_json
            updated_nodes += 1

    for edge_payload in list(transformed_snapshot.get("edges") or []):
        edge_id = int(edge_payload["id"])
        edge = edge_by_id.get(edge_id)
        if edge is None:
            continue
        changed = False

        edge_mode = _normalize_edge_mode(edge_payload.get("edge_mode"))
        if str(edge.edge_mode or "") != edge_mode:
            edge.edge_mode = edge_mode
            changed = True

        condition_key = str(edge_payload.get("condition_key") or "").strip() or None
        if (str(edge.condition_key or "").strip() or None) != condition_key:
            edge.condition_key = condition_key
            changed = True

        if changed:
            updated_edges += 1

    return {
        "updated_nodes": updated_nodes,
        "updated_edges": updated_edges,
    }


def analyze_flowchart_migration(
    flowchart: Flowchart,
    *,
    llmctl_mcp_server_id: int | None,
    strict_policy: bool = True,
) -> dict[str, Any]:
    snapshot = build_flowchart_migration_snapshot(flowchart)
    return analyze_flowchart_migration_snapshot(
        snapshot,
        llmctl_mcp_server_id=llmctl_mcp_server_id,
        strict_policy=strict_policy,
    )


def run_flowchart_schema_migration(
    session: Session,
    *,
    flowchart_ids: list[int] | None = None,
    apply: bool = False,
    strict_policy: bool = True,
) -> dict[str, Any]:
    stmt = (
        select(Flowchart)
        .options(
            selectinload(Flowchart.nodes).selectinload(FlowchartNode.mcp_servers),
            selectinload(Flowchart.nodes).selectinload(FlowchartNode.scripts),
            selectinload(Flowchart.nodes).selectinload(FlowchartNode.skills),
            selectinload(Flowchart.nodes).selectinload(FlowchartNode.attachments),
            selectinload(Flowchart.edges),
        )
        .order_by(Flowchart.id.asc())
    )
    if flowchart_ids:
        normalized_ids = sorted({int(item) for item in flowchart_ids if int(item) > 0})
        stmt = stmt.where(Flowchart.id.in_(normalized_ids))

    flowcharts = list(session.execute(stmt).scalars().all())
    llmctl_mcp_server_id = session.execute(
        select(MCPServer.id).where(MCPServer.server_key == INTEGRATED_MCP_LLMCTL_KEY)
    ).scalar_one_or_none()

    reports: list[dict[str, Any]] = []
    applied_count = 0
    blocked_count = 0
    changed_count = 0

    for flowchart in flowcharts:
        report = analyze_flowchart_migration(
            flowchart,
            llmctl_mcp_server_id=llmctl_mcp_server_id,
            strict_policy=strict_policy,
        )

        if report.get("changed"):
            changed_count += 1

        gate_status = (
            report.get("compatibility_gate", {}).get("status") or "blocked"
        )
        if gate_status != "ready":
            blocked_count += 1

        if apply and gate_status == "ready" and report.get("changed"):
            updates = apply_flowchart_snapshot_migration(
                session,
                flowchart,
                report.get("post_migration_snapshot") or {},
            )
            report["apply"] = {
                "applied": True,
                "updates": updates,
                "applied_at": _utc_iso(),
            }
            applied_count += 1
        else:
            report["apply"] = {
                "applied": False,
                "updates": {"updated_nodes": 0, "updated_edges": 0},
                "applied_at": None,
            }
        reports.append(report)

    return {
        "contract_version": FLOW_MIGRATION_CONTRACT_VERSION,
        "generated_at": _utc_iso(),
        "apply_requested": bool(apply),
        "strict_policy": bool(strict_policy),
        "flowchart_count": len(flowcharts),
        "changed_count": changed_count,
        "blocked_count": blocked_count,
        "applied_count": applied_count,
        "reports": reports,
    }

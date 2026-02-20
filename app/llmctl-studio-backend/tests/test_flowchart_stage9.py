from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from unittest.mock import patch

from flask import Flask
import psycopg

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

os.environ.setdefault(
    "LLMCTL_STUDIO_DATABASE_URI",
    "postgresql+psycopg://llmctl:llmctl@127.0.0.1:15432/llmctl_studio",
)

import core.db as core_db
from core.config import Config
from core.db import session_scope
from core.models import (
    Agent,
    AgentTask,
    Attachment,
    FLOWCHART_NODE_TYPE_DECISION,
    FLOWCHART_NODE_TYPE_END,
    FLOWCHART_NODE_TYPE_FLOWCHART,
    FLOWCHART_NODE_TYPE_MEMORY,
    FLOWCHART_NODE_TYPE_MILESTONE,
    FLOWCHART_NODE_TYPE_PLAN,
    FLOWCHART_NODE_TYPE_START,
    FLOWCHART_NODE_TYPE_TASK,
    LLMModel,
    MCPServer,
    Milestone,
    Memory,
    NodeArtifact,
    NODE_ARTIFACT_TYPE_MEMORY,
    NODE_ARTIFACT_TYPE_DECISION,
    NODE_ARTIFACT_TYPE_MILESTONE,
    NODE_ARTIFACT_TYPE_PLAN,
    Plan,
    PlanStage,
    PlanTask,
    SCRIPT_TYPE_INIT,
    SCRIPT_TYPE_POST_INIT,
    SCRIPT_TYPE_POST_RUN,
    SCRIPT_TYPE_PRE_INIT,
    Script,
    Flowchart,
    FlowchartEdge,
    FlowchartNode,
    FlowchartRun,
    FlowchartRunNode,
)
from services import tasks as studio_tasks
import web.views as studio_views


class _LocalExecutionRouter:
    def __init__(self, *, runtime_settings=None, kubernetes_executor=None) -> None:
        del kubernetes_executor
        self.runtime_settings = runtime_settings or {}

    def route_request(self, request):
        workspace_identity = str(
            self.runtime_settings.get("workspace_identity_key") or "default"
        ).strip() or "default"
        return replace(
            request,
            selected_provider="kubernetes",
            final_provider="kubernetes",
            provider_dispatch_id=None,
            workspace_identity=workspace_identity,
            dispatch_status="dispatch_pending",
            fallback_attempted=False,
            fallback_reason=None,
            dispatch_uncertain=False,
            api_failure_category=None,
            cli_fallback_used=False,
            cli_preflight_passed=None,
        )

    def execute_routed(self, request, execute_callback):
        from services.execution.contracts import (
            EXECUTION_CONTRACT_VERSION,
            EXECUTION_STATUS_SUCCESS,
            ExecutionResult,
        )

        output_state, routing_state = execute_callback(request)
        now = datetime.now(timezone.utc)
        provider_dispatch_id = f"kubernetes:default/job-test-{request.execution_id}"
        run_metadata = request.run_metadata_payload()
        run_metadata.update(
            {
                "provider_dispatch_id": provider_dispatch_id,
                "k8s_job_name": f"job-test-{request.execution_id}",
                "k8s_pod_name": f"pod-test-{request.execution_id}",
                "k8s_terminal_reason": "complete",
                "dispatch_status": "dispatch_confirmed",
            }
        )
        return ExecutionResult(
            contract_version=EXECUTION_CONTRACT_VERSION,
            status=EXECUTION_STATUS_SUCCESS,
            exit_code=0,
            started_at=now,
            finished_at=now,
            stdout="",
            stderr="",
            error=None,
            provider_metadata={
                "provider_dispatch_id": provider_dispatch_id,
                "k8s_job_name": f"job-test-{request.execution_id}",
                "k8s_pod_name": f"pod-test-{request.execution_id}",
                "k8s_terminal_reason": "complete",
            },
            output_state=output_state,
            routing_state=routing_state,
            run_metadata=run_metadata,
        )

    def execute(self, request, execute_callback):
        routed = self.route_request(request)
        return self.execute_routed(routed, execute_callback)


class StudioDbTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp_dir = Path(self._tmp.name)
        self._base_db_uri = os.environ["LLMCTL_STUDIO_DATABASE_URI"]
        self._schema_name = f"flowchart_stage9_{uuid.uuid4().hex}"
        self._orig_db_uri = Config.SQLALCHEMY_DATABASE_URI
        self._orig_workspaces_dir = Config.WORKSPACES_DIR
        self._create_schema(self._schema_name)
        Config.SQLALCHEMY_DATABASE_URI = self._with_search_path(
            self._base_db_uri,
            self._schema_name,
        )
        Config.WORKSPACES_DIR = str(tmp_dir / "workspaces")
        Path(Config.WORKSPACES_DIR).mkdir(parents=True, exist_ok=True)
        self._execution_router_patcher = patch.object(
            studio_tasks,
            "ExecutionRouter",
            _LocalExecutionRouter,
        )
        self._execution_router_patcher.start()
        self._reset_engine()

    def tearDown(self) -> None:
        self._execution_router_patcher.stop()
        self._dispose_engine()
        self._drop_schema(self._schema_name)
        Config.SQLALCHEMY_DATABASE_URI = self._orig_db_uri
        Config.WORKSPACES_DIR = self._orig_workspaces_dir
        self._tmp.cleanup()

    def _dispose_engine(self) -> None:
        if core_db._engine is not None:
            core_db._engine.dispose()
        core_db._engine = None
        core_db.SessionLocal = None

    def _reset_engine(self) -> None:
        self._dispose_engine()
        core_db.init_engine(Config.SQLALCHEMY_DATABASE_URI)
        core_db.init_db()

    @staticmethod
    def _as_psycopg_uri(database_uri: str) -> str:
        if database_uri.startswith("postgresql+psycopg://"):
            return "postgresql://" + database_uri.split("://", 1)[1]
        return database_uri

    @staticmethod
    def _with_search_path(database_uri: str, schema_name: str) -> str:
        parts = urlsplit(database_uri)
        query_items = parse_qsl(parts.query, keep_blank_values=True)
        updated_items: list[tuple[str, str]] = []
        options_value = f"-csearch_path={schema_name}"
        options_updated = False
        for key, value in query_items:
            if key == "options":
                merged = value.strip()
                if options_value not in merged:
                    merged = f"{merged} {options_value}".strip()
                updated_items.append((key, merged))
                options_updated = True
            else:
                updated_items.append((key, value))
        if not options_updated:
            updated_items.append(("options", options_value))
        query = urlencode(updated_items, doseq=True)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))

    def _create_schema(self, schema_name: str) -> None:
        with psycopg.connect(self._as_psycopg_uri(self._base_db_uri), autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"')

    def _drop_schema(self, schema_name: str) -> None:
        with psycopg.connect(self._as_psycopg_uri(self._base_db_uri), autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')


class FlowchartStage9UnitTests(StudioDbTestCase):
    def _invoke_flowchart_run(
        self,
        flowchart_id: int,
        run_id: int,
        *,
        monotonic_values: list[float] | None = None,
    ) -> None:
        base_patches = [
            patch.object(studio_tasks, "load_integration_settings", return_value={}),
            patch.object(studio_tasks, "resolve_enabled_llm_providers", return_value=set()),
            patch.object(studio_tasks, "resolve_default_model_id", return_value=None),
        ]
        with base_patches[0], base_patches[1], base_patches[2]:
            if monotonic_values is None:
                studio_tasks.run_flowchart.run(flowchart_id, run_id)
                return
            with patch.object(
                studio_tasks.time, "monotonic", side_effect=monotonic_values
            ):
                studio_tasks.run_flowchart.run(flowchart_id, run_id)

    def test_decision_route_resolution_supports_multi_match(self) -> None:
        input_context = {
            "latest_upstream": {
                "output_state": {
                    "structured_output": {
                        "route_key": "approve",
                        "message": "Start node executed. urgent approval",
                    }
                },
                "routing_state": {},
            }
        }
        output_state, routing_state = studio_tasks._execute_flowchart_decision_node(
            node_config={
                "decision_conditions": [
                    {
                        "connector_id": "approve_path",
                        "condition_text": "latest_upstream.output_state.structured_output.route_key == approve",
                    },
                    {
                        "connector_id": "urgent_path",
                        "condition_text": "latest_upstream.output_state.structured_output.message contains urgent",
                    },
                    {
                        "connector_id": "reject_path",
                        "condition_text": "latest_upstream.output_state.structured_output.route_key == reject",
                    },
                ]
            },
            input_context=input_context,
            mcp_server_keys=["llmctl-mcp"],
        )
        self.assertEqual(
            ["approve_path", "urgent_path"], routing_state.get("matched_connector_ids")
        )
        self.assertFalse(output_state.get("no_match"))
        selected = studio_tasks._resolve_flowchart_outgoing_edges(
            node_type=FLOWCHART_NODE_TYPE_DECISION,
            node_config={},
            outgoing_edges=[
                {"id": 1, "edge_mode": "solid", "condition_key": "reject_path"},
                {"id": 2, "edge_mode": "solid", "condition_key": "approve_path"},
                {"id": 3, "edge_mode": "solid", "condition_key": "urgent_path"},
            ],
            routing_state=routing_state,
        )
        self.assertEqual([2, 3], [edge["id"] for edge in selected])

    def test_decision_route_resolution_ignores_dotted_edges(self) -> None:
        selected = studio_tasks._resolve_flowchart_outgoing_edges(
            node_type=FLOWCHART_NODE_TYPE_DECISION,
            node_config={},
            outgoing_edges=[
                {"id": 1, "edge_mode": "dotted", "condition_key": "approve"},
                {"id": 2, "edge_mode": "solid", "condition_key": "approve"},
            ],
            routing_state={"matched_connector_ids": ["approve"], "no_match": False},
        )
        self.assertEqual([2], [edge["id"] for edge in selected])

    def test_decision_route_resolution_no_match_uses_fallback(self) -> None:
        selected = studio_tasks._resolve_flowchart_outgoing_edges(
            node_type=FLOWCHART_NODE_TYPE_DECISION,
            node_config={"fallback_condition_key": "reject"},
            outgoing_edges=[
                {"id": 11, "edge_mode": "solid", "condition_key": "approve"},
                {"id": 12, "edge_mode": "solid", "condition_key": "reject"},
            ],
            routing_state={"matched_connector_ids": [], "no_match": True},
        )
        self.assertEqual([12], [edge["id"] for edge in selected])

    def test_decision_route_resolution_no_match_without_fallback_fails(self) -> None:
        with self.assertRaises(ValueError):
            studio_tasks._resolve_flowchart_outgoing_edges(
                node_type=FLOWCHART_NODE_TYPE_DECISION,
                node_config={},
                outgoing_edges=[
                    {"id": 11, "edge_mode": "solid", "condition_key": "approve"},
                    {"id": 12, "edge_mode": "solid", "condition_key": "reject"},
                ],
                routing_state={"matched_connector_ids": [], "no_match": True},
            )

    def test_decision_route_resolution_fails_for_unknown_connector_ids(self) -> None:
        with self.assertRaises(ValueError):
            studio_tasks._resolve_flowchart_outgoing_edges(
                node_type=FLOWCHART_NODE_TYPE_DECISION,
                node_config={},
                outgoing_edges=[
                    {"id": 11, "edge_mode": "solid", "condition_key": "approve"},
                    {"id": 12, "edge_mode": "solid", "condition_key": "reject"},
                ],
                routing_state={"matched_connector_ids": ["missing_connector"], "no_match": False},
            )

    def test_non_decision_route_resolution_emits_only_solid_edges(self) -> None:
        selected = studio_tasks._resolve_flowchart_outgoing_edges(
            node_type=FLOWCHART_NODE_TYPE_TASK,
            node_config={},
            outgoing_edges=[
                {"id": 1, "edge_mode": "solid", "condition_key": ""},
                {"id": 2, "edge_mode": "dotted", "condition_key": ""},
            ],
            routing_state={},
        )
        self.assertEqual([1], [edge["id"] for edge in selected])

    def test_non_decision_route_resolution_fails_for_unknown_route_key(self) -> None:
        with self.assertRaises(ValueError):
            studio_tasks._resolve_flowchart_outgoing_edges(
                node_type=FLOWCHART_NODE_TYPE_TASK,
                node_config={},
                outgoing_edges=[
                    {"id": 1, "edge_mode": "solid", "condition_key": "next"},
                    {"id": 2, "edge_mode": "solid", "condition_key": "retry"},
                ],
                routing_state={"route_key": "missing"},
            )

    def test_runtime_decision_multi_route_launches_all_matches(self) -> None:
        decision_config = {
            "decision_conditions": [
                {
                    "connector_id": "left_connector",
                    "condition_text": "Start node executed.",
                },
                {
                    "connector_id": "right_connector",
                    "condition_text": "Start node executed.",
                },
            ]
        }
        with session_scope() as session:
            flowchart = Flowchart.create(
                session, name="Stage 9 Decision Multi Route", max_parallel_nodes=2
            )
            start_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                x=0.0,
                y=0.0,
            )
            decision_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_DECISION,
                x=160.0,
                y=0.0,
                config_json=json.dumps(decision_config, sort_keys=True),
            )
            left_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_END,
                x=320.0,
                y=-70.0,
            )
            right_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_END,
                x=320.0,
                y=70.0,
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=decision_node.id,
                edge_mode="solid",
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=decision_node.id,
                target_node_id=left_node.id,
                edge_mode="solid",
                condition_key="left_connector",
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=decision_node.id,
                target_node_id=right_node.id,
                edge_mode="solid",
                condition_key="right_connector",
            )
            flowchart_run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="queued",
            )
            flowchart_id = flowchart.id
            run_id = flowchart_run.id
            start_node_id = start_node.id
            decision_node_id = decision_node.id
            left_node_id = left_node.id
            right_node_id = right_node.id

        self._invoke_flowchart_run(flowchart_id, run_id)

        with session_scope() as session:
            run = session.get(FlowchartRun, run_id)
            assert run is not None
            self.assertEqual("completed", run.status)
            node_runs = (
                session.query(FlowchartRunNode)
                .where(FlowchartRunNode.flowchart_run_id == run_id)
                .order_by(FlowchartRunNode.id.asc())
                .all()
            )
            self.assertEqual(
                [start_node_id, decision_node_id, left_node_id, right_node_id],
                [item.flowchart_node_id for item in node_runs],
            )
            decision_run = next(
                item for item in node_runs if item.flowchart_node_id == decision_node_id
            )
            decision_routing = json.loads(decision_run.routing_state_json or "{}")
            self.assertEqual(
                ["left_connector", "right_connector"],
                decision_routing.get("matched_connector_ids"),
            )
            self.assertFalse(decision_routing.get("no_match"))
            decision_artifacts = (
                session.query(NodeArtifact)
                .where(
                    NodeArtifact.flowchart_run_id == run_id,
                    NodeArtifact.artifact_type == NODE_ARTIFACT_TYPE_DECISION,
                )
                .order_by(NodeArtifact.id.asc())
                .all()
            )
            self.assertEqual(1, len(decision_artifacts))
            decision_artifact_payload = json.loads(decision_artifacts[0].payload_json or "{}")
            self.assertEqual(
                ["left_connector", "right_connector"],
                decision_artifact_payload.get("matched_connector_ids"),
            )
            self.assertFalse(decision_artifact_payload.get("no_match"))
            self.assertEqual(
                {"left_connector", "right_connector"},
                {
                    str(item.get("connector_id"))
                    for item in (decision_artifact_payload.get("evaluations") or [])
                    if isinstance(item, dict)
                },
            )

    def test_runtime_decision_no_match_without_fallback_fails_run(self) -> None:
        decision_config = {
            "decision_conditions": [
                {
                    "connector_id": "left_connector",
                    "condition_text": "no-such-signal",
                },
                {
                    "connector_id": "right_connector",
                    "condition_text": "still-no-signal",
                },
            ]
        }
        with session_scope() as session:
            flowchart = Flowchart.create(session, name="Stage 9 Decision No Match")
            start_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                x=0.0,
                y=0.0,
            )
            decision_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_DECISION,
                x=160.0,
                y=0.0,
                config_json=json.dumps(decision_config, sort_keys=True),
            )
            left_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_END,
                x=320.0,
                y=-70.0,
            )
            right_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_END,
                x=320.0,
                y=70.0,
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=decision_node.id,
                edge_mode="solid",
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=decision_node.id,
                target_node_id=left_node.id,
                edge_mode="solid",
                condition_key="left_connector",
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=decision_node.id,
                target_node_id=right_node.id,
                edge_mode="solid",
                condition_key="right_connector",
            )
            flowchart_run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="queued",
            )
            flowchart_id = flowchart.id
            run_id = flowchart_run.id
            start_node_id = start_node.id
            decision_node_id = decision_node.id

        self._invoke_flowchart_run(flowchart_id, run_id)

        with session_scope() as session:
            run = session.get(FlowchartRun, run_id)
            assert run is not None
            self.assertEqual("failed", run.status)
            node_runs = (
                session.query(FlowchartRunNode)
                .where(FlowchartRunNode.flowchart_run_id == run_id)
                .order_by(FlowchartRunNode.id.asc())
                .all()
            )
            self.assertEqual([start_node_id, decision_node_id], [item.flowchart_node_id for item in node_runs])
            decision_run = next(
                item for item in node_runs if item.flowchart_node_id == decision_node_id
            )
            self.assertEqual("failed", decision_run.status)
            self.assertIn("no matched_connector_ids", str(decision_run.error or ""))
            decision_routing = json.loads(decision_run.routing_state_json or "{}")
            self.assertEqual([], decision_routing.get("matched_connector_ids"))
            self.assertTrue(decision_routing.get("no_match"))
            decision_artifacts = (
                session.query(NodeArtifact)
                .where(
                    NodeArtifact.flowchart_run_id == run_id,
                    NodeArtifact.artifact_type == NODE_ARTIFACT_TYPE_DECISION,
                )
                .order_by(NodeArtifact.id.asc())
                .all()
            )
            self.assertEqual(1, len(decision_artifacts))
            decision_artifact_payload = json.loads(decision_artifacts[0].payload_json or "{}")
            self.assertEqual([], decision_artifact_payload.get("matched_connector_ids"))
            self.assertTrue(decision_artifact_payload.get("no_match"))

    def test_runtime_decision_no_match_uses_fallback_connector(self) -> None:
        decision_config = {
            "fallback_condition_key": "right_connector",
            "decision_conditions": [
                {
                    "connector_id": "left_connector",
                    "condition_text": "no-such-signal",
                },
                {
                    "connector_id": "right_connector",
                    "condition_text": "still-no-signal",
                },
            ],
        }
        with session_scope() as session:
            flowchart = Flowchart.create(session, name="Stage 9 Decision No Match Fallback")
            start_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                x=0.0,
                y=0.0,
            )
            decision_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_DECISION,
                x=160.0,
                y=0.0,
                config_json=json.dumps(decision_config, sort_keys=True),
            )
            left_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_END,
                x=320.0,
                y=-70.0,
            )
            right_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_END,
                x=320.0,
                y=70.0,
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=decision_node.id,
                edge_mode="solid",
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=decision_node.id,
                target_node_id=left_node.id,
                edge_mode="solid",
                condition_key="left_connector",
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=decision_node.id,
                target_node_id=right_node.id,
                edge_mode="solid",
                condition_key="right_connector",
            )
            flowchart_run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="queued",
            )
            flowchart_id = flowchart.id
            run_id = flowchart_run.id
            decision_node_id = decision_node.id
            left_node_id = left_node.id
            right_node_id = right_node.id

        self._invoke_flowchart_run(flowchart_id, run_id)

        with session_scope() as session:
            run = session.get(FlowchartRun, run_id)
            assert run is not None
            self.assertEqual("completed", run.status)
            node_runs = (
                session.query(FlowchartRunNode)
                .where(FlowchartRunNode.flowchart_run_id == run_id)
                .all()
            )
            self.assertFalse(any(item.flowchart_node_id == left_node_id for item in node_runs))
            self.assertTrue(any(item.flowchart_node_id == right_node_id for item in node_runs))
            decision_run = next(
                item for item in node_runs if item.flowchart_node_id == decision_node_id
            )
            decision_routing = json.loads(decision_run.routing_state_json or "{}")
            self.assertEqual([], decision_routing.get("matched_connector_ids"))
            self.assertTrue(decision_routing.get("no_match"))

    def test_runtime_emits_artifact_socket_event_with_request_and_correlation_ids(self) -> None:
        decision_config = {
            "request_id": "req-decision-socket-1",
            "correlation_id": "corr-decision-socket-1",
            "decision_conditions": [
                {
                    "connector_id": "approve_connector",
                    "condition_text": "Start node executed.",
                }
            ],
        }
        with session_scope() as session:
            flowchart = Flowchart.create(session, name="Stage 9 Decision Artifact Event")
            start_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                x=0.0,
                y=0.0,
            )
            decision_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_DECISION,
                x=160.0,
                y=0.0,
                config_json=json.dumps(decision_config, sort_keys=True),
            )
            end_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_END,
                x=320.0,
                y=0.0,
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=decision_node.id,
                edge_mode="solid",
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=decision_node.id,
                target_node_id=end_node.id,
                edge_mode="solid",
                condition_key="approve_connector",
            )
            flowchart_run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="queued",
            )
            flowchart_id = flowchart.id
            run_id = flowchart_run.id

        captured_events: list[dict[str, object]] = []
        artifact_visible_during_emit: list[bool] = []

        def _capture_emit(**kwargs):
            captured_events.append(dict(kwargs))
            if kwargs.get("event_type") == "flowchart:node_artifact:persisted":
                payload = kwargs.get("payload") if isinstance(kwargs.get("payload"), dict) else {}
                artifact_id = int(payload.get("artifact_id") or 0)
                with session_scope() as session:
                    artifact_visible_during_emit.append(
                        session.get(NodeArtifact, artifact_id) is not None
                    )
            return {
                "event_type": kwargs.get("event_type"),
                "payload": kwargs.get("payload") or {},
            }

        with patch.object(studio_tasks, "emit_contract_event", side_effect=_capture_emit):
            self._invoke_flowchart_run(flowchart_id, run_id)

        artifact_events = [
            item
            for item in captured_events
            if item.get("event_type") == "flowchart:node_artifact:persisted"
        ]
        self.assertEqual(1, len(artifact_events))
        event_payload = artifact_events[0].get("payload") or {}
        self.assertEqual(
            "req-decision-socket-1",
            event_payload.get("request_id"),
        )
        self.assertEqual(
            "corr-decision-socket-1",
            event_payload.get("correlation_id"),
        )
        self.assertEqual("decision", event_payload.get("artifact_type"))
        artifact_payload = (event_payload.get("artifact") or {}).get("payload") or {}
        self.assertEqual(
            ["approve_connector"],
            artifact_payload.get("matched_connector_ids") or [],
        )
        self.assertEqual([True], artifact_visible_during_emit)

    def test_input_context_includes_trigger_and_pulled_source_metadata(self) -> None:
        context = studio_tasks._build_flowchart_input_context(
            flowchart_id=10,
            run_id=22,
            node_id=7,
            node_type=FLOWCHART_NODE_TYPE_MEMORY,
            execution_index=3,
            total_execution_count=9,
            incoming_edges=[
                {
                    "id": 101,
                    "source_node_id": 1,
                    "target_node_id": 7,
                    "edge_mode": "solid",
                    "condition_key": "",
                },
                {
                    "id": 202,
                    "source_node_id": 2,
                    "target_node_id": 7,
                    "edge_mode": "dotted",
                    "condition_key": "",
                },
            ],
            latest_results={
                1: {
                    "node_type": FLOWCHART_NODE_TYPE_TASK,
                    "execution_index": 4,
                    "sequence": 6,
                    "output_state": {"value": "solid"},
                    "routing_state": {},
                },
                2: {
                    "node_type": FLOWCHART_NODE_TYPE_MEMORY,
                    "execution_index": 5,
                    "sequence": 8,
                    "output_state": {"value": "dotted"},
                    "routing_state": {},
                },
            },
            upstream_results=None,
        )
        trigger_sources = context.get("trigger_sources") or []
        pulled_sources = context.get("pulled_dotted_sources") or []
        self.assertEqual(1, len(trigger_sources))
        self.assertEqual(1, len(pulled_sources))
        self.assertEqual(101, trigger_sources[0].get("source_edge_id"))
        self.assertEqual(1, trigger_sources[0].get("source_node_id"))
        self.assertEqual("solid", trigger_sources[0].get("edge_mode"))
        self.assertEqual(202, pulled_sources[0].get("source_edge_id"))
        self.assertEqual(2, pulled_sources[0].get("source_node_id"))
        self.assertEqual("dotted", pulled_sources[0].get("edge_mode"))

    def test_memory_node_requires_system_llmctl_mcp(self) -> None:
        with session_scope() as session:
            flowchart = Flowchart.create(session, name="memory-mcp-required")
            memory_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=0.0,
                y=0.0,
            )
            memory_node_id = memory_node.id

        with self.assertRaisesRegex(
            ValueError,
            "system-managed LLMCTL MCP server",
        ):
            studio_tasks._execute_flowchart_memory_node(
                node_id=memory_node_id,
                node_ref_id=None,
                node_config={"action": "add", "additive_prompt": "persist this"},
                input_context={},
                mcp_server_keys=["custom-mcp"],
            )

    def test_memory_node_infers_prompt_from_upstream_context_when_additive_prompt_blank(self) -> None:
        with session_scope() as session:
            flowchart = Flowchart.create(session, name="memory-infer-prompt")
            memory = Memory.create(session, description="")
            memory_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                ref_id=memory.id,
                x=0.0,
                y=0.0,
            )
            memory_node_id = memory_node.id
            memory_id = memory.id

        output_state, routing_state = studio_tasks._execute_flowchart_memory_node(
            node_id=memory_node_id,
            node_ref_id=memory_id,
            node_config={"action": "add"},
            input_context={
                "node": {"execution_index": 2},
                "latest_upstream": {"output_state": {"message": "capture deployment readiness"}},
                "upstream_nodes": [
                    {"output_state": "capture deployment readiness and risks"},
                ],
            },
            mcp_server_keys=["llmctl-mcp"],
        )
        self.assertEqual({}, routing_state)
        self.assertEqual(FLOWCHART_NODE_TYPE_MEMORY, output_state.get("node_type"))
        self.assertEqual("add", output_state.get("action"))
        self.assertEqual("", output_state.get("additive_prompt"))
        self.assertTrue(str(output_state.get("inferred_prompt") or "").strip())
        self.assertEqual(
            output_state.get("inferred_prompt"),
            output_state.get("effective_prompt"),
        )
        self.assertEqual(["llmctl-mcp"], output_state.get("mcp_server_keys") or [])

        with session_scope() as session:
            updated_memory = session.get(Memory, memory_id)
            self.assertIsNotNone(updated_memory)
            assert updated_memory is not None
            self.assertIn(
                str(output_state.get("effective_prompt") or "").strip(),
                str(updated_memory.description or ""),
            )

    def test_memory_node_requires_explicit_action(self) -> None:
        with session_scope() as session:
            flowchart = Flowchart.create(session, name="memory-action-required")
            memory_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=0.0,
                y=0.0,
            )
            memory_node_id = memory_node.id

        with self.assertRaisesRegex(
            ValueError,
            "Memory node action is required: add or retrieve",
        ):
            studio_tasks._execute_flowchart_memory_node(
                node_id=memory_node_id,
                node_ref_id=None,
                node_config={},
                input_context={},
                mcp_server_keys=["llmctl-mcp"],
            )

    def test_memory_node_exposes_internal_action_prompt_template(self) -> None:
        with session_scope() as session:
            flowchart = Flowchart.create(session, name="memory-internal-prompt")
            memory_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=0.0,
                y=0.0,
            )
            memory_node_id = memory_node.id

        output_state, _routing_state = studio_tasks._execute_flowchart_memory_node(
            node_id=memory_node_id,
            node_ref_id=None,
            node_config={
                "action": "retrieve",
                "additive_prompt": "focus on deployment readiness",
            },
            input_context={},
            mcp_server_keys=["llmctl-mcp"],
        )
        self.assertEqual("retrieve", output_state.get("action"))
        self.assertIn(
            "Memory action: Retrieve memory",
            str(output_state.get("action_prompt_template") or ""),
        )
        self.assertIn(
            "focus on deployment readiness",
            str(output_state.get("internal_action_prompt") or ""),
        )

    def test_script_stage_split_preserves_order(self) -> None:
        scripts = [
            Script(id=1, file_name="a.sh", content="", script_type=SCRIPT_TYPE_INIT),
            Script(id=2, file_name="b.sh", content="", script_type=SCRIPT_TYPE_PRE_INIT),
            Script(id=3, file_name="c.sh", content="", script_type=SCRIPT_TYPE_INIT),
            Script(id=4, file_name="d.sh", content="", script_type=SCRIPT_TYPE_POST_RUN),
            Script(id=5, file_name="e.sh", content="", script_type=SCRIPT_TYPE_POST_INIT),
            Script(id=6, file_name="f.sh", content="", script_type="skill"),
        ]
        pre_init, init, post_init, post_run, unknown = studio_tasks._split_scripts_by_stage(scripts)
        self.assertEqual([2], [item.id for item in pre_init])
        self.assertEqual([1, 3], [item.id for item in init])
        self.assertEqual([5], [item.id for item in post_init])
        self.assertEqual([4], [item.id for item in post_run])
        self.assertEqual([6], [item.id for item in unknown])

    def test_node_model_resolver_precedence_and_override(self) -> None:
        with session_scope() as session:
            node_model = LLMModel.create(
                session,
                name="node-model",
                provider="codex",
                config_json="{}",
            )
            default_model = LLMModel.create(
                session,
                name="default-model",
                provider="codex",
                config_json="{}",
            )
            flowchart = Flowchart.create(session, name="resolver-flowchart")
            node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_TASK,
                model_id=node_model.id,
                x=0.0,
                y=0.0,
            )
            resolved = studio_tasks._resolve_node_model(session, node=node, default_model_id=default_model.id)
            self.assertEqual(node_model.id, resolved.id)

            node.model_id = None
            resolved = studio_tasks._resolve_node_model(session, node=node, default_model_id=default_model.id)
            self.assertEqual(default_model.id, resolved.id)

            with self.assertRaisesRegex(ValueError, "No model configured"):
                studio_tasks._resolve_node_model(
                    session,
                    node=node,
                    default_model_id=None,
                )

    def test_task_node_runs_without_template_when_inline_prompt_present(self) -> None:
        with session_scope() as session:
            model = LLMModel.create(
                session,
                name="inline-task-model",
                provider="codex",
                config_json="{}",
            )
            flowchart = Flowchart.create(session, name="inline-task-flowchart")
            start_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                x=0.0,
                y=0.0,
            )
            task_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_TASK,
                model_id=model.id,
                x=1.0,
                y=0.0,
                config_json=json.dumps(
                    {
                        "task_name": "ad-hoc task",
                        "task_prompt": "Return JSON with route_key=done",
                    },
                    sort_keys=True,
                ),
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=task_node.id,
            )
            flowchart_run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="queued",
            )
            run_id = flowchart_run.id
            task_node_id = task_node.id
            flowchart_id = flowchart.id

        with patch.object(
            studio_tasks,
            "_run_llm",
            return_value=SimpleNamespace(
                args=[],
                returncode=0,
                stdout=json.dumps({"route_key": "done"}),
                stderr="Reading prompt from stdin...\n",
            ),
        ), patch.object(studio_tasks, "load_integration_settings", return_value={}), patch.object(
            studio_tasks, "resolve_enabled_llm_providers", return_value={"codex"}
        ), patch.object(studio_tasks, "resolve_default_model_id", return_value=None):
            studio_tasks.run_flowchart.run(flowchart_id, run_id)

        with session_scope() as session:
            run = session.get(FlowchartRun, run_id)
            self.assertEqual("completed", run.status)
            task_run = (
                session.query(FlowchartRunNode)
                .where(
                    FlowchartRunNode.flowchart_run_id == run_id,
                    FlowchartRunNode.flowchart_node_id == task_node_id,
                )
                .first()
            )
            self.assertIsNotNone(task_run)
            output_state = json.loads(task_run.output_state_json or "{}")
            self.assertEqual("config", output_state.get("task_prompt_source"))
            self.assertEqual("ad-hoc task", output_state.get("task_name"))
            self.assertEqual("", output_state.get("raw_error"))
            self.assertEqual("post_run", output_state.get("task_current_stage"))
            output_stage_logs = output_state.get("task_stage_logs") or {}
            self.assertIn("llm_query", output_stage_logs)
            self.assertIn("Launching", output_stage_logs.get("llm_query", ""))
            self.assertIsNotNone(task_run.agent_task_id)
            task = session.get(AgentTask, task_run.agent_task_id)
            self.assertIsNotNone(task)
            assert task is not None
            self.assertEqual("succeeded", task.status)
            self.assertEqual(flowchart_id, task.flowchart_id)
            self.assertEqual(run_id, task.flowchart_run_id)
            self.assertEqual(task_node_id, task.flowchart_node_id)
            self.assertEqual(json.dumps({"route_key": "done"}), task.output)
            self.assertEqual("post_run", task.current_stage)
            task_stage_logs = json.loads(task.stage_logs or "{}")
            self.assertIn("llm_query", task_stage_logs)
            self.assertIn("Launching", task_stage_logs.get("llm_query", ""))

    def test_task_node_uses_selected_agent_from_config(self) -> None:
        with session_scope() as session:
            model = LLMModel.create(
                session,
                name="inline-agent-task-model",
                provider="codex",
                config_json="{}",
            )
            agent = Agent.create(
                session,
                name="Task Agent",
                prompt_json=json.dumps({"instruction": "Use task agent profile."}),
            )
            flowchart = Flowchart.create(session, name="inline-agent-task-flowchart")
            start_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                x=0.0,
                y=0.0,
            )
            task_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_TASK,
                model_id=model.id,
                x=1.0,
                y=0.0,
                config_json=json.dumps(
                    {
                        "task_prompt": "Return JSON with route_key=done",
                        "agent_id": agent.id,
                    },
                    sort_keys=True,
                ),
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=task_node.id,
            )
            flowchart_run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="queued",
            )
            run_id = flowchart_run.id
            task_node_id = task_node.id
            flowchart_id = flowchart.id
            agent_id = agent.id

        with patch.object(
            studio_tasks,
            "_run_llm",
            return_value=SimpleNamespace(
                args=[],
                returncode=0,
                stdout=json.dumps({"route_key": "done"}),
                stderr="",
            ),
        ) as llm_mock, patch.object(
            studio_tasks,
            "load_integration_settings",
            return_value={},
        ), patch.object(
            studio_tasks,
            "resolve_enabled_llm_providers",
            return_value={"codex"},
        ), patch.object(
            studio_tasks,
            "resolve_default_model_id",
            return_value=None,
        ):
            studio_tasks.run_flowchart.run(flowchart_id, run_id)

        llm_prompt = llm_mock.call_args.args[1]
        llm_payload = json.loads(llm_prompt)
        self.assertEqual(agent_id, ((llm_payload.get("agent_profile") or {}).get("id")))

        with session_scope() as session:
            run = session.get(FlowchartRun, run_id)
            self.assertEqual("completed", run.status)
            node_run = (
                session.query(FlowchartRunNode)
                .where(
                    FlowchartRunNode.flowchart_run_id == run_id,
                    FlowchartRunNode.flowchart_node_id == task_node_id,
                )
                .first()
            )
            self.assertIsNotNone(node_run)
            output_state = json.loads(node_run.output_state_json or "{}")
            self.assertEqual(agent_id, output_state.get("agent_id"))
            self.assertEqual("config", output_state.get("agent_source"))
            task = session.get(AgentTask, node_run.agent_task_id)
            self.assertIsNotNone(task)
            assert task is not None
            self.assertEqual(agent_id, task.agent_id)

    def test_flowchart_marks_failed_when_node_success_persistence_conflicts(self) -> None:
        conflict_dispatch_id = "kubernetes:default/job-test-conflict"

        class _ConflictDispatchRouter(_LocalExecutionRouter):
            def execute_routed(self, request, execute_callback):
                from services.execution.contracts import (
                    EXECUTION_CONTRACT_VERSION,
                    EXECUTION_STATUS_SUCCESS,
                    ExecutionResult,
                )

                output_state, routing_state = execute_callback(request)
                now = datetime.now(timezone.utc)
                run_metadata = request.run_metadata_payload()
                run_metadata.update(
                    {
                        "provider_dispatch_id": conflict_dispatch_id,
                        "k8s_job_name": "job-test-conflict",
                        "k8s_pod_name": "pod-test-conflict",
                        "k8s_terminal_reason": "complete",
                        "dispatch_status": "dispatch_confirmed",
                    }
                )
                return ExecutionResult(
                    contract_version=EXECUTION_CONTRACT_VERSION,
                    status=EXECUTION_STATUS_SUCCESS,
                    exit_code=0,
                    started_at=now,
                    finished_at=now,
                    stdout="",
                    stderr="",
                    error=None,
                    provider_metadata={
                        "provider_dispatch_id": conflict_dispatch_id,
                        "k8s_job_name": "job-test-conflict",
                        "k8s_pod_name": "pod-test-conflict",
                        "k8s_terminal_reason": "complete",
                    },
                    output_state=output_state,
                    routing_state=routing_state,
                    run_metadata=run_metadata,
                )

        with session_scope() as session:
            AgentTask.create(
                session,
                status="succeeded",
                kind="rag_quick_index",
                provider_dispatch_id=conflict_dispatch_id,
                dispatch_status="dispatch_confirmed",
            )
            flowchart = Flowchart.create(session, name="persistence-conflict-flowchart")
            FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                x=0.0,
                y=0.0,
            )
            flowchart_run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="queued",
            )
            flowchart_id = flowchart.id
            run_id = flowchart_run.id

        with patch.object(
            studio_tasks,
            "ExecutionRouter",
            _ConflictDispatchRouter,
        ), patch.object(
            studio_tasks,
            "load_integration_settings",
            return_value={},
        ), patch.object(
            studio_tasks,
            "resolve_enabled_llm_providers",
            return_value={"codex"},
        ), patch.object(
            studio_tasks,
            "resolve_default_model_id",
            return_value=None,
        ):
            studio_tasks.run_flowchart.run(flowchart_id, run_id)

        with session_scope() as session:
            run = session.get(FlowchartRun, run_id)
            self.assertIsNotNone(run)
            assert run is not None
            self.assertEqual("failed", run.status)
            self.assertIsNotNone(run.finished_at)
            node_run = (
                session.query(FlowchartRunNode)
                .where(FlowchartRunNode.flowchart_run_id == run_id)
                .order_by(FlowchartRunNode.id.asc())
                .first()
            )
            self.assertIsNotNone(node_run)
            assert node_run is not None
            self.assertEqual("failed", node_run.status)
            self.assertIn("persistence failed", str(node_run.error or "").lower())
            self.assertIsNotNone(node_run.finished_at)
            self.assertIsNotNone(node_run.agent_task_id)
            task = session.get(AgentTask, node_run.agent_task_id)
            self.assertIsNotNone(task)
            assert task is not None
            self.assertEqual("failed", task.status)
            self.assertEqual("dispatch_failed", task.dispatch_status)
            self.assertIn("persistence failed", str(task.error or "").lower())
            self.assertIsNotNone(task.finished_at)

    def test_task_node_uses_node_attachments(self) -> None:
        with session_scope() as session:
            model = LLMModel.create(
                session,
                name="attachment-task-model",
                provider="codex",
                config_json="{}",
            )
            node_attachment = Attachment.create(
                session,
                file_name="node.txt",
                file_path="/tmp/node.txt",
                content_type="text/plain",
                size_bytes=4,
            )
            flowchart = Flowchart.create(session, name="attachment-flowchart")
            start_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                x=0.0,
                y=0.0,
            )
            task_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_TASK,
                model_id=model.id,
                x=1.0,
                y=0.0,
                config_json=json.dumps(
                    {"task_prompt": "Return route_key=done"}, sort_keys=True
                ),
            )
            task_node.attachments.append(node_attachment)
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=task_node.id,
            )
            flowchart_run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="queued",
            )
            run_id = flowchart_run.id
            task_node_id = task_node.id
            flowchart_id = flowchart.id
            node_attachment_id = node_attachment.id

        with patch.object(
            studio_tasks,
            "_run_llm",
            return_value=SimpleNamespace(
                args=[],
                returncode=0,
                stdout=json.dumps({"route_key": "done"}),
                stderr="",
            ),
        ) as llm_mock, patch.object(
            studio_tasks,
            "load_integration_settings",
            return_value={},
        ), patch.object(
            studio_tasks,
            "resolve_enabled_llm_providers",
            return_value={"codex"},
        ), patch.object(
            studio_tasks,
            "resolve_default_model_id",
            return_value=None,
        ):
            studio_tasks.run_flowchart.run(flowchart_id, run_id)

        llm_prompt = llm_mock.call_args.args[1]
        llm_payload = json.loads(llm_prompt)
        attachment_entries = (
            (llm_payload.get("task_context") or {}).get("attachments") or []
        )
        attachment_ids = {int(entry.get("id")) for entry in attachment_entries if entry.get("id")}
        self.assertEqual({node_attachment_id}, attachment_ids)

        with session_scope() as session:
            run = session.get(FlowchartRun, run_id)
            self.assertIsNotNone(run)
            assert run is not None
            self.assertEqual("completed", run.status)
            node_run = (
                session.query(FlowchartRunNode)
                .where(
                    FlowchartRunNode.flowchart_run_id == run_id,
                    FlowchartRunNode.flowchart_node_id == task_node_id,
                )
                .first()
            )
            self.assertIsNotNone(node_run)
            assert node_run is not None
            output_state = json.loads(node_run.output_state_json or "{}")
            output_attachment_ids = {
                int(entry.get("id"))
                for entry in (output_state.get("attachments") or [])
                if entry.get("id")
            }
            self.assertEqual({node_attachment_id}, output_attachment_ids)
            task = session.get(AgentTask, node_run.agent_task_id)
            self.assertIsNotNone(task)
            assert task is not None
            task_attachment_ids = {attachment.id for attachment in list(task.attachments)}
            self.assertEqual({node_attachment_id}, task_attachment_ids)

    def test_flowchart_task_output_display_prefers_raw_output(self) -> None:
        output = studio_tasks._flowchart_task_output_display(
            {
                "node_type": FLOWCHART_NODE_TYPE_TASK,
                "raw_output": "Hello\n",
                "structured_output": {"text": "ignored"},
            }
        )
        self.assertEqual("Hello\n", output)

    def test_node_view_output_display_prefers_flowchart_task_raw_output(self) -> None:
        raw = json.dumps(
            {
                "node_type": FLOWCHART_NODE_TYPE_TASK,
                "raw_output": "Hello\n",
                "structured_output": {"text": "Hello"},
            }
        )
        display = studio_views._task_output_for_display(raw)
        self.assertEqual("Hello\n", display)

    def test_scheduler_merge_waits_for_all_upstream_parents(self) -> None:
        with session_scope() as session:
            flowchart = Flowchart.create(session, name="merge-flowchart", max_parallel_nodes=2)
            start_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                x=0.0,
                y=0.0,
            )
            left_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=1.0,
                y=1.0,
            )
            right_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=2.0,
                y=2.0,
            )
            join_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=3.0,
                y=3.0,
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=left_node.id,
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=right_node.id,
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=left_node.id,
                target_node_id=join_node.id,
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=right_node.id,
                target_node_id=join_node.id,
            )
            flowchart_run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="queued",
            )
            run_id = flowchart_run.id
            join_node_id = join_node.id
            left_node_id = left_node.id
            right_node_id = right_node.id

        self._invoke_flowchart_run(flowchart.id, run_id)

        with session_scope() as session:
            run = session.get(FlowchartRun, run_id)
            self.assertIsNotNone(run)
            self.assertEqual("completed", run.status)
            node_runs = (
                session.query(FlowchartRunNode)
                .where(FlowchartRunNode.flowchart_run_id == run_id)
                .order_by(FlowchartRunNode.id.asc())
                .all()
            )
            self.assertEqual(4, len(node_runs))
            join_run = (
                session.query(FlowchartRunNode)
                .where(
                    FlowchartRunNode.flowchart_run_id == run_id,
                    FlowchartRunNode.flowchart_node_id == join_node_id,
                )
                .first()
            )
            self.assertIsNotNone(join_run)
            input_context = json.loads(join_run.input_context_json or "{}")
            upstream_nodes = input_context.get("upstream_nodes") or []
            self.assertEqual(2, len(upstream_nodes))
            self.assertEqual(
                [left_node_id, right_node_id],
                sorted(node["node_id"] for node in upstream_nodes),
            )

    def test_scheduler_runs_solid_fanout_children_in_parallel(self) -> None:
        with session_scope() as session:
            flowchart = Flowchart.create(session, name="parallel-fanout", max_parallel_nodes=2)
            start_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                x=0.0,
                y=0.0,
            )
            left_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=1.0,
                y=1.0,
            )
            right_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=2.0,
                y=1.0,
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=left_node.id,
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=right_node.id,
            )
            flowchart_run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="queued",
            )
            flowchart_id = flowchart.id
            run_id = flowchart_run.id
            branch_node_ids = {left_node.id, right_node.id}

        call_starts: dict[int, float] = {}
        call_ends: dict[int, float] = {}
        call_lock = threading.Lock()

        class _ParallelProbeRouter(_LocalExecutionRouter):
            def execute_routed(self, request, execute_callback):
                if request.node_id in branch_node_ids:
                    with call_lock:
                        call_starts[request.node_id] = time.monotonic()
                    time.sleep(0.25)
                    result = super().execute_routed(request, execute_callback)
                    with call_lock:
                        call_ends[request.node_id] = time.monotonic()
                    return result
                return super().execute_routed(request, execute_callback)

        with patch.object(studio_tasks, "ExecutionRouter", _ParallelProbeRouter):
            self._invoke_flowchart_run(flowchart_id, run_id)

        with session_scope() as session:
            run = session.get(FlowchartRun, run_id)
            self.assertIsNotNone(run)
            assert run is not None
            self.assertEqual("completed", run.status)

        self.assertEqual(branch_node_ids, set(call_starts.keys()))
        self.assertEqual(branch_node_ids, set(call_ends.keys()))
        overlap_seconds = min(call_ends.values()) - max(call_starts.values())
        self.assertGreater(overlap_seconds, 0.05)

    def test_dotted_edges_do_not_trigger_downstream_execution(self) -> None:
        with session_scope() as session:
            flowchart = Flowchart.create(session, name="dotted-no-trigger")
            start_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                x=0.0,
                y=0.0,
            )
            source_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=1.0,
                y=0.0,
            )
            target_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=2.0,
                y=0.0,
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=source_node.id,
                edge_mode="solid",
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=source_node.id,
                target_node_id=target_node.id,
                edge_mode="dotted",
            )
            flowchart_run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="queued",
            )
            run_id = flowchart_run.id
            start_node_id = start_node.id
            source_node_id = source_node.id
            target_node_id = target_node.id

        self._invoke_flowchart_run(flowchart.id, run_id)

        with session_scope() as session:
            run = session.get(FlowchartRun, run_id)
            self.assertIsNotNone(run)
            assert run is not None
            self.assertEqual("completed", run.status)
            node_runs = (
                session.query(FlowchartRunNode)
                .where(FlowchartRunNode.flowchart_run_id == run_id)
                .order_by(FlowchartRunNode.id.asc())
                .all()
            )
            self.assertEqual(
                [start_node_id, source_node_id],
                [item.flowchart_node_id for item in node_runs],
            )
            self.assertFalse(
                any(item.flowchart_node_id == target_node_id for item in node_runs)
            )

    def test_dotted_context_is_pulled_without_gating_execution(self) -> None:
        with session_scope() as session:
            flowchart = Flowchart.create(session, name="dotted-context-pull")
            start_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                x=0.0,
                y=0.0,
            )
            dotted_source_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=1.0,
                y=-1.0,
            )
            trigger_source_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=1.0,
                y=1.0,
            )
            target_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=2.0,
                y=0.0,
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=dotted_source_node.id,
                edge_mode="solid",
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=trigger_source_node.id,
                edge_mode="solid",
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=dotted_source_node.id,
                target_node_id=target_node.id,
                edge_mode="dotted",
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=trigger_source_node.id,
                target_node_id=target_node.id,
                edge_mode="solid",
            )
            flowchart_run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="queued",
            )
            run_id = flowchart_run.id
            dotted_source_node_id = dotted_source_node.id
            trigger_source_node_id = trigger_source_node.id
            target_node_id = target_node.id

        self._invoke_flowchart_run(flowchart.id, run_id)

        with session_scope() as session:
            run = session.get(FlowchartRun, run_id)
            self.assertIsNotNone(run)
            assert run is not None
            self.assertEqual("completed", run.status)
            target_run = (
                session.query(FlowchartRunNode)
                .where(
                    FlowchartRunNode.flowchart_run_id == run_id,
                    FlowchartRunNode.flowchart_node_id == target_node_id,
                )
                .first()
            )
            self.assertIsNotNone(target_run)
            assert target_run is not None
            input_context = json.loads(target_run.input_context_json or "{}")
            upstream_nodes = input_context.get("upstream_nodes") or []
            dotted_upstream_nodes = input_context.get("dotted_upstream_nodes") or []
            self.assertEqual(1, len(upstream_nodes))
            self.assertEqual(trigger_source_node_id, upstream_nodes[0].get("node_id"))
            self.assertEqual("solid", upstream_nodes[0].get("edge_mode"))
            self.assertEqual(1, len(dotted_upstream_nodes))
            self.assertEqual(dotted_source_node_id, dotted_upstream_nodes[0].get("node_id"))
            self.assertEqual("dotted", dotted_upstream_nodes[0].get("edge_mode"))

    def test_reaching_start_queues_followup_run(self) -> None:
        with session_scope() as session:
            flowchart = Flowchart.create(session, name="start-handoff-flowchart")
            start_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                x=0.0,
                y=0.0,
            )
            task_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=1.0,
                y=0.0,
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=task_node.id,
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=task_node.id,
                target_node_id=start_node.id,
            )
            flowchart_run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="queued",
            )
            flowchart_id = flowchart.id
            run_id = flowchart_run.id
            start_node_id = start_node.id
            task_node_id = task_node.id

        with patch.object(
            studio_tasks.run_flowchart,
            "delay",
            return_value=SimpleNamespace(id="next-run-job"),
        ) as delay_mock:
            self._invoke_flowchart_run(flowchart_id, run_id)

        with session_scope() as session:
            run = session.get(FlowchartRun, run_id)
            self.assertIsNotNone(run)
            assert run is not None
            self.assertEqual("completed", run.status)

            runs = (
                session.query(FlowchartRun)
                .where(FlowchartRun.flowchart_id == flowchart_id)
                .order_by(FlowchartRun.id.asc())
                .all()
            )
            self.assertEqual(2, len(runs))
            next_run = runs[-1]
            self.assertEqual("queued", next_run.status)
            self.assertNotEqual(run_id, next_run.id)

            node_runs = (
                session.query(FlowchartRunNode)
                .where(FlowchartRunNode.flowchart_run_id == run_id)
                .order_by(FlowchartRunNode.id.asc())
                .all()
            )
            self.assertEqual(2, len(node_runs))
            self.assertEqual(
                [start_node_id, task_node_id],
                [item.flowchart_node_id for item in node_runs],
            )

        delay_mock.assert_called_once()
        called_flowchart_id, called_run_id = delay_mock.call_args.args
        self.assertEqual(flowchart_id, called_flowchart_id)
        self.assertGreater(int(called_run_id), run_id)

    def test_stop_request_finishes_current_node_then_stops(self) -> None:
        with session_scope() as session:
            flowchart = Flowchart.create(session, name="graceful-stop-flowchart")
            start_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                x=0.0,
                y=0.0,
            )
            next_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=1.0,
                y=0.0,
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=next_node.id,
            )
            flowchart_run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="queued",
            )
            flowchart_id = flowchart.id
            run_id = flowchart_run.id
            start_node_id = start_node.id
            next_node_id = next_node.id

        original_execute = studio_tasks._execute_flowchart_node

        def _execute_with_stop_request(*args, **kwargs):
            node_id = int(kwargs.get("node_id"))
            if node_id == start_node_id:
                with session_scope() as session:
                    run = session.get(FlowchartRun, run_id)
                    assert run is not None
                    run.status = "stopping"
            return original_execute(*args, **kwargs)

        with patch.object(
            studio_tasks,
            "_execute_flowchart_node",
            side_effect=_execute_with_stop_request,
        ):
            self._invoke_flowchart_run(flowchart_id, run_id)

        with session_scope() as session:
            run = session.get(FlowchartRun, run_id)
            self.assertIsNotNone(run)
            assert run is not None
            self.assertEqual("stopped", run.status)
            node_runs = (
                session.query(FlowchartRunNode)
                .where(FlowchartRunNode.flowchart_run_id == run_id)
                .order_by(FlowchartRunNode.id.asc())
                .all()
            )
            self.assertEqual(1, len(node_runs))
            self.assertEqual(start_node_id, node_runs[0].flowchart_node_id)
            self.assertEqual("succeeded", node_runs[0].status)
            self.assertFalse(
                any(item.flowchart_node_id == next_node_id for item in node_runs)
            )

    def test_stop_request_prevents_followup_run_when_reaching_start(self) -> None:
        with session_scope() as session:
            flowchart = Flowchart.create(session, name="graceful-stop-no-followup")
            start_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                x=0.0,
                y=0.0,
            )
            memory_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=1.0,
                y=0.0,
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=memory_node.id,
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=memory_node.id,
                target_node_id=start_node.id,
            )
            flowchart_run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="queued",
            )
            flowchart_id = flowchart.id
            run_id = flowchart_run.id
            memory_node_id = memory_node.id

        original_execute = studio_tasks._execute_flowchart_node

        def _execute_with_stop_request(*args, **kwargs):
            node_id = int(kwargs.get("node_id"))
            if node_id == memory_node_id:
                with session_scope() as session:
                    run = session.get(FlowchartRun, run_id)
                    assert run is not None
                    run.status = "stopping"
            return original_execute(*args, **kwargs)

        with patch.object(
            studio_tasks,
            "_execute_flowchart_node",
            side_effect=_execute_with_stop_request,
        ), patch.object(
            studio_tasks.run_flowchart,
            "delay",
            return_value=SimpleNamespace(id="next-run-job"),
        ) as delay_mock:
            self._invoke_flowchart_run(flowchart_id, run_id)

        with session_scope() as session:
            run = session.get(FlowchartRun, run_id)
            self.assertIsNotNone(run)
            assert run is not None
            self.assertEqual("stopped", run.status)
            runs = (
                session.query(FlowchartRun)
                .where(FlowchartRun.flowchart_id == flowchart_id)
                .order_by(FlowchartRun.id.asc())
                .all()
            )
            self.assertEqual(1, len(runs))

        delay_mock.assert_not_called()

    def test_end_node_terminates_run_even_with_outgoing_edges(self) -> None:
        with session_scope() as session:
            flowchart = Flowchart.create(session, name="end-terminates-run")
            start_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                x=0.0,
                y=0.0,
            )
            end_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_END,
                x=1.0,
                y=0.0,
            )
            memory_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=2.0,
                y=0.0,
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=end_node.id,
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=end_node.id,
                target_node_id=memory_node.id,
            )
            flowchart_run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="queued",
            )
            flowchart_id = flowchart.id
            run_id = flowchart_run.id
            start_node_id = start_node.id
            end_node_id = end_node.id
            memory_node_id = memory_node.id

        with patch.object(
            studio_tasks.run_flowchart,
            "delay",
            return_value=SimpleNamespace(id="unexpected-followup-run"),
        ) as delay_mock:
            self._invoke_flowchart_run(flowchart_id, run_id)

        with session_scope() as session:
            run = session.get(FlowchartRun, run_id)
            self.assertIsNotNone(run)
            assert run is not None
            self.assertEqual("completed", run.status)

            node_runs = (
                session.query(FlowchartRunNode)
                .where(FlowchartRunNode.flowchart_run_id == run_id)
                .order_by(FlowchartRunNode.id.asc())
                .all()
            )
            self.assertEqual(
                [start_node_id, end_node_id],
                [item.flowchart_node_id for item in node_runs],
            )
            self.assertFalse(
                any(item.flowchart_node_id == memory_node_id for item in node_runs)
            )

        delay_mock.assert_not_called()

    def test_guardrail_max_node_executions_records_failure(self) -> None:
        with session_scope() as session:
            flowchart = Flowchart.create(
                session,
                name="max-node-executions",
                max_node_executions=1,
            )
            start_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                x=0.0,
                y=0.0,
            )
            gated_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=1.0,
                y=1.0,
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=gated_node.id,
            )
            flowchart_run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="queued",
            )
            run_id = flowchart_run.id
            gated_node_id = gated_node.id

        self._invoke_flowchart_run(flowchart.id, run_id)

        with session_scope() as session:
            run = session.get(FlowchartRun, run_id)
            self.assertEqual("failed", run.status)
            failed = (
                session.query(FlowchartRunNode)
                .where(
                    FlowchartRunNode.flowchart_run_id == run_id,
                    FlowchartRunNode.flowchart_node_id == gated_node_id,
                )
                .first()
            )
            self.assertIsNotNone(failed)
            self.assertEqual("failed", failed.status)
            self.assertIn("max_node_executions", failed.error or "")

    def test_guardrail_max_runtime_minutes_records_failure(self) -> None:
        with session_scope() as session:
            flowchart = Flowchart.create(
                session,
                name="max-runtime-minutes",
                max_runtime_minutes=1,
            )
            start_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                x=0.0,
                y=0.0,
            )
            flowchart_run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="queued",
            )
            run_id = flowchart_run.id
            start_node_id = start_node.id

        self._invoke_flowchart_run(
            flowchart.id,
            run_id,
            monotonic_values=[0.0, 120.0, 120.0],
        )

        with session_scope() as session:
            run = session.get(FlowchartRun, run_id)
            self.assertEqual("failed", run.status)
            failed = (
                session.query(FlowchartRunNode)
                .where(
                    FlowchartRunNode.flowchart_run_id == run_id,
                    FlowchartRunNode.flowchart_node_id == start_node_id,
                )
                .first()
            )
            self.assertIsNotNone(failed)
            self.assertEqual("failed", failed.status)
            self.assertIn("max_runtime_minutes", failed.error or "")

    def test_flowchart_node_queues_new_target_run_on_every_execution(self) -> None:
        with session_scope() as session:
            target_flowchart = Flowchart.create(session, name="target-flowchart")
            target_flowchart_id = target_flowchart.id

        with patch.object(
            studio_tasks.run_flowchart,
            "delay",
            side_effect=[
                SimpleNamespace(id="target-run-job-1"),
                SimpleNamespace(id="target-run-job-2"),
            ],
        ) as delay_mock:
            first_output_state, first_routing_state = (
                studio_tasks._execute_flowchart_flowchart_node(
                    node_ref_id=target_flowchart_id,
                )
            )
            second_output_state, second_routing_state = (
                studio_tasks._execute_flowchart_flowchart_node(
                    node_ref_id=target_flowchart_id,
                )
            )

        self.assertEqual({}, first_routing_state)
        self.assertEqual({}, second_routing_state)
        self.assertEqual(
            FLOWCHART_NODE_TYPE_FLOWCHART,
            first_output_state.get("node_type"),
        )
        self.assertEqual(
            FLOWCHART_NODE_TYPE_FLOWCHART,
            second_output_state.get("node_type"),
        )
        self.assertEqual(
            target_flowchart_id,
            int(first_output_state.get("triggered_flowchart_id") or 0),
        )
        self.assertEqual(
            target_flowchart_id,
            int(second_output_state.get("triggered_flowchart_id") or 0),
        )
        first_run_id = int(first_output_state.get("triggered_flowchart_run_id") or 0)
        second_run_id = int(second_output_state.get("triggered_flowchart_run_id") or 0)
        self.assertGreater(first_run_id, 0)
        self.assertGreater(second_run_id, 0)
        self.assertNotEqual(first_run_id, second_run_id)
        self.assertEqual(2, delay_mock.call_count)

        with session_scope() as session:
            runs = (
                session.query(FlowchartRun)
                .where(FlowchartRun.flowchart_id == target_flowchart_id)
                .order_by(FlowchartRun.id.asc())
                .all()
            )
            self.assertEqual(2, len(runs))
            self.assertEqual(first_run_id, runs[0].id)
            self.assertEqual(second_run_id, runs[1].id)
            self.assertEqual("queued", runs[0].status)
            self.assertEqual("queued", runs[1].status)
            self.assertEqual("target-run-job-1", runs[0].celery_task_id)
            self.assertEqual("target-run-job-2", runs[1].celery_task_id)

    def test_plan_completion_target_resolution_prefers_plan_item_id(self) -> None:
        with session_scope() as session:
            plan = Plan.create(session, name="target-resolution")
            stage_alpha = PlanStage.create(
                session,
                plan_id=plan.id,
                name="Stage Alpha",
                position=1,
            )
            task_alpha = PlanTask.create(
                session,
                plan_stage_id=stage_alpha.id,
                name="Task Alpha",
                position=1,
            )
            stage_beta = PlanStage.create(
                session,
                plan_id=plan.id,
                name="Stage Beta",
                position=2,
            )
            task_beta = PlanTask.create(
                session,
                plan_stage_id=stage_beta.id,
                name="Task Beta",
                position=1,
            )
            persisted_plan = session.get(Plan, plan.id)
            assert persisted_plan is not None
            resolved = studio_tasks._resolve_plan_completion_target(
                plan=persisted_plan,
                plan_item_id=task_alpha.id,
                stage_key="stage_beta",
                task_key="task_beta",
            )
            stage, task, resolution, stage_key, task_key = resolved
            self.assertEqual(stage_alpha.id, stage.id)
            self.assertEqual(task_alpha.id, task.id)
            self.assertEqual("plan_item_id", resolution)
            self.assertEqual("stage_alpha", stage_key)
            self.assertEqual("task_alpha", task_key)
            self.assertNotEqual(task_beta.id, task.id)

    def test_plan_completion_target_resolution_fallback_normalizes_keys(self) -> None:
        with session_scope() as session:
            plan = Plan.create(session, name="target-resolution-fallback")
            stage = PlanStage.create(
                session,
                plan_id=plan.id,
                name="Stage 1: Release Prep",
                position=1,
            )
            task = PlanTask.create(
                session,
                plan_stage_id=stage.id,
                name="Run Smoke Test!",
                position=1,
            )
            persisted_plan = session.get(Plan, plan.id)
            assert persisted_plan is not None
            resolved = studio_tasks._resolve_plan_completion_target(
                plan=persisted_plan,
                plan_item_id=None,
                stage_key="Stage 1 Release Prep",
                task_key="run-smoke test",
            )
            resolved_stage, resolved_task, resolution, stage_key, task_key = resolved
            self.assertEqual(stage.id, resolved_stage.id)
            self.assertEqual(task.id, resolved_task.id)
            self.assertEqual("stage_task_key", resolution)
            self.assertEqual("stage_1_release_prep", stage_key)
            self.assertEqual("run_smoke_test", task_key)

    def test_plan_completion_target_resolution_rejects_ambiguous_fallback(self) -> None:
        with session_scope() as session:
            plan = Plan.create(session, name="target-resolution-ambiguous")
            stage_a = PlanStage.create(
                session,
                plan_id=plan.id,
                name="Duplicate Stage",
                position=1,
            )
            stage_b = PlanStage.create(
                session,
                plan_id=plan.id,
                name="Duplicate Stage",
                position=2,
            )
            PlanTask.create(
                session,
                plan_stage_id=stage_a.id,
                name="Repeat Task",
                position=1,
            )
            PlanTask.create(
                session,
                plan_stage_id=stage_b.id,
                name="Repeat Task",
                position=1,
            )
            persisted_plan = session.get(Plan, plan.id)
            assert persisted_plan is not None
            with self.assertRaisesRegex(ValueError, "Ambiguous complete_plan_item target"):
                studio_tasks._resolve_plan_completion_target(
                    plan=persisted_plan,
                    plan_item_id=None,
                    stage_key="duplicate stage",
                    task_key="repeat task",
                )

    def test_plan_node_complete_action_prefers_plan_item_id(self) -> None:
        with session_scope() as session:
            flowchart = Flowchart.create(session, name="plan-complete-node")
            plan = Plan.create(session, name="plan-complete")
            stage_a = PlanStage.create(session, plan_id=plan.id, name="Stage A", position=1)
            stage_b = PlanStage.create(session, plan_id=plan.id, name="Stage B", position=2)
            task_a = PlanTask.create(session, plan_stage_id=stage_a.id, name="Task A", position=1)
            task_b = PlanTask.create(session, plan_stage_id=stage_b.id, name="Task B", position=1)
            node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_PLAN,
                ref_id=plan.id,
                x=0.0,
                y=0.0,
            )
            node_id = node.id
            plan_id = plan.id
            task_a_id = task_a.id
            task_b_id = task_b.id

        output_state, _routing_state = studio_tasks._execute_flowchart_plan_node(
            node_id=node_id,
            node_ref_id=plan_id,
            node_config={
                "action": "complete_plan_item",
                "plan_item_id": task_a_id,
                "stage_key": "stage_b",
                "task_key": "task_b",
            },
            input_context={},
            enabled_providers=set(),
            default_model_id=None,
            mcp_server_keys=["llmctl-mcp"],
        )
        completion_target = output_state.get("completion_target") or {}
        self.assertEqual("plan_item_id", completion_target.get("resolution"))
        self.assertEqual(task_a_id, completion_target.get("plan_item_id"))
        touched = output_state.get("touched") or {}
        self.assertIn(task_a_id, touched.get("task_ids") or [])
        self.assertNotIn(task_b_id, touched.get("task_ids") or [])

        with session_scope() as session:
            persisted_task_a = session.get(PlanTask, task_a_id)
            persisted_task_b = session.get(PlanTask, task_b_id)
            assert persisted_task_a is not None
            assert persisted_task_b is not None
            self.assertIsNotNone(persisted_task_a.completed_at)
            self.assertIsNone(persisted_task_b.completed_at)

    def test_plan_node_requires_explicit_action(self) -> None:
        with session_scope() as session:
            flowchart = Flowchart.create(session, name="plan-action-required")
            plan = Plan.create(session, name="plan-action-required")
            node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_PLAN,
                ref_id=plan.id,
                x=0.0,
                y=0.0,
            )
            node_id = node.id
            plan_id = plan.id

        with self.assertRaisesRegex(
            ValueError,
            "Plan node action is required: create_or_update_plan or complete_plan_item",
        ):
            studio_tasks._execute_flowchart_plan_node(
                node_id=node_id,
                node_ref_id=plan_id,
                node_config={},
                input_context={},
                enabled_providers=set(),
                default_model_id=None,
                mcp_server_keys=["llmctl-mcp"],
            )

    def test_milestone_node_requires_explicit_action(self) -> None:
        with session_scope() as session:
            flowchart = Flowchart.create(session, name="milestone-action-required")
            milestone = Milestone.create(session, name="milestone-action-required")
            node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MILESTONE,
                ref_id=milestone.id,
                x=0.0,
                y=0.0,
            )
            node_id = node.id
            milestone_id = milestone.id

        with self.assertRaisesRegex(
            ValueError,
            "Milestone node action is required: create_or_update or mark_complete",
        ):
            studio_tasks._execute_flowchart_milestone_node(
                node_id=node_id,
                node_ref_id=milestone_id,
                node_config={},
                input_context={},
                execution_index=1,
                enabled_providers=set(),
                default_model_id=None,
                mcp_server_keys=["llmctl-mcp"],
            )

    def test_plan_node_artifact_persistence_payload_includes_touched_references(self) -> None:
        with session_scope() as session:
            flowchart = Flowchart.create(session, name="plan-artifact-persistence")
            plan = Plan.create(session, name="artifact-plan")
            stage = PlanStage.create(session, plan_id=plan.id, name="Stage Artifact", position=1)
            task = PlanTask.create(session, plan_stage_id=stage.id, name="Task Artifact", position=1)
            node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_PLAN,
                ref_id=plan.id,
                x=0.0,
                y=0.0,
            )
            run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="completed",
            )
            run_node = FlowchartRunNode.create(
                session,
                flowchart_run_id=run.id,
                flowchart_node_id=node.id,
                execution_index=2,
                status="succeeded",
                input_context_json=json.dumps(
                    {"request_id": "req-plan-1", "correlation_id": "corr-plan-1"},
                    sort_keys=True,
                ),
                output_state_json="{}",
            )
            artifact_summary = studio_tasks._persist_plan_node_artifact(
                session,
                flowchart_id=flowchart.id,
                flowchart_node_id=node.id,
                flowchart_run_id=run.id,
                flowchart_run_node_id=run_node.id,
                node_config={
                    "retention_mode": "ttl",
                    "retention_ttl_seconds": 3600,
                    "retention_max_count": 25,
                },
                input_context={
                    "request_id": "req-plan-1",
                    "correlation_id": "corr-plan-1",
                    "node": {"execution_index": 2},
                },
                output_state={
                    "action": "complete_plan_item",
                    "additive_prompt": "mark done",
                    "completion_target": {
                        "resolution": "plan_item_id",
                        "plan_item_id": task.id,
                        "stage_id": stage.id,
                        "stage_key": "stage_artifact",
                        "task_key": "task_artifact",
                    },
                    "touched": {
                        "stage_ids": [stage.id],
                        "task_ids": [task.id],
                        "stages": [{"id": stage.id, "name": stage.name}],
                        "tasks": [{"id": task.id, "name": task.name}],
                    },
                    "plan": studio_tasks._serialize_plan_for_node(plan),
                },
                routing_state={"route_key": "next"},
            )
            self.assertEqual("plan", artifact_summary.get("artifact_type"))
            self.assertEqual(1, artifact_summary.get("payload_version"))
            self.assertEqual("req-plan-1", artifact_summary.get("request_id"))
            self.assertEqual("corr-plan-1", artifact_summary.get("correlation_id"))
            payload = artifact_summary.get("payload") or {}
            self.assertEqual("complete_plan_item", payload.get("action"))
            self.assertEqual([stage.id], (payload.get("touched") or {}).get("stage_ids"))
            self.assertEqual([task.id], (payload.get("touched") or {}).get("task_ids"))
            self.assertEqual(task.id, (payload.get("completion_target") or {}).get("plan_item_id"))
            persisted_artifact = session.get(NodeArtifact, artifact_summary.get("id"))
            assert persisted_artifact is not None
            self.assertEqual(NODE_ARTIFACT_TYPE_PLAN, persisted_artifact.artifact_type)
            self.assertEqual(plan.id, persisted_artifact.ref_id)
            self.assertEqual(1, persisted_artifact.payload_version)

    def test_plan_node_artifact_prunes_expired_ttl_entries(self) -> None:
        with session_scope() as session:
            flowchart = Flowchart.create(session, name="plan-artifact-ttl-prune")
            plan = Plan.create(session, name="artifact-plan-ttl")
            stage = PlanStage.create(session, plan_id=plan.id, name="Stage TTL", position=1)
            task = PlanTask.create(session, plan_stage_id=stage.id, name="Task TTL", position=1)
            node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_PLAN,
                ref_id=plan.id,
                x=0.0,
                y=0.0,
            )
            run = FlowchartRun.create(session, flowchart_id=flowchart.id, status="completed")
            expired_run_node = FlowchartRunNode.create(
                session,
                flowchart_run_id=run.id,
                flowchart_node_id=node.id,
                execution_index=1,
                status="succeeded",
                input_context_json="{}",
                output_state_json="{}",
            )
            expired_artifact = NodeArtifact.create(
                session,
                flowchart_id=flowchart.id,
                flowchart_node_id=node.id,
                flowchart_run_id=run.id,
                flowchart_run_node_id=expired_run_node.id,
                node_type=FLOWCHART_NODE_TYPE_PLAN,
                artifact_type=NODE_ARTIFACT_TYPE_PLAN,
                ref_id=plan.id,
                execution_index=1,
                variant_key=f"run-{run.id}-node-run-{expired_run_node.id}",
                retention_mode="ttl",
                expires_at=datetime.now(timezone.utc) - timedelta(seconds=10),
                payload_json=json.dumps({"action": "legacy"}, sort_keys=True),
            )
            next_run_node = FlowchartRunNode.create(
                session,
                flowchart_run_id=run.id,
                flowchart_node_id=node.id,
                execution_index=2,
                status="succeeded",
                input_context_json="{}",
                output_state_json="{}",
            )
            artifact_summary = studio_tasks._persist_plan_node_artifact(
                session,
                flowchart_id=flowchart.id,
                flowchart_node_id=node.id,
                flowchart_run_id=run.id,
                flowchart_run_node_id=next_run_node.id,
                node_config={
                    "retention_mode": "ttl",
                    "retention_ttl_seconds": 3600,
                    "retention_max_count": 25,
                },
                input_context={"node": {"execution_index": 2}},
                output_state={
                    "action": "complete_plan_item",
                    "completion_target": {"plan_item_id": task.id},
                    "touched": {"stage_ids": [stage.id], "task_ids": [task.id]},
                    "plan": studio_tasks._serialize_plan_for_node(plan),
                },
                routing_state={},
            )
            remaining = (
                session.query(NodeArtifact)
                .where(
                    NodeArtifact.flowchart_node_id == node.id,
                    NodeArtifact.artifact_type == NODE_ARTIFACT_TYPE_PLAN,
                )
                .order_by(NodeArtifact.id.asc())
                .all()
            )
            self.assertEqual(1, len(remaining))
            self.assertEqual(artifact_summary.get("id"), remaining[0].id)
            self.assertNotEqual(expired_artifact.id, remaining[0].id)

    def test_plan_node_artifact_prunes_to_max_count(self) -> None:
        with session_scope() as session:
            flowchart = Flowchart.create(session, name="plan-artifact-max-prune")
            plan = Plan.create(session, name="artifact-plan-max")
            stage = PlanStage.create(session, plan_id=plan.id, name="Stage Max", position=1)
            task = PlanTask.create(session, plan_stage_id=stage.id, name="Task Max", position=1)
            node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_PLAN,
                ref_id=plan.id,
                x=0.0,
                y=0.0,
            )
            run = FlowchartRun.create(session, flowchart_id=flowchart.id, status="completed")
            for execution_index in (1, 2, 3):
                run_node = FlowchartRunNode.create(
                    session,
                    flowchart_run_id=run.id,
                    flowchart_node_id=node.id,
                    execution_index=execution_index,
                    status="succeeded",
                    input_context_json="{}",
                    output_state_json="{}",
                )
                studio_tasks._persist_plan_node_artifact(
                    session,
                    flowchart_id=flowchart.id,
                    flowchart_node_id=node.id,
                    flowchart_run_id=run.id,
                    flowchart_run_node_id=run_node.id,
                    node_config={
                        "retention_mode": "max_count",
                        "retention_ttl_seconds": 3600,
                        "retention_max_count": 2,
                    },
                    input_context={"node": {"execution_index": execution_index}},
                    output_state={
                        "action": "complete_plan_item",
                        "completion_target": {"plan_item_id": task.id},
                        "touched": {"stage_ids": [stage.id], "task_ids": [task.id]},
                        "plan": studio_tasks._serialize_plan_for_node(plan),
                    },
                    routing_state={},
                )
            remaining = (
                session.query(NodeArtifact)
                .where(
                    NodeArtifact.flowchart_node_id == node.id,
                    NodeArtifact.artifact_type == NODE_ARTIFACT_TYPE_PLAN,
                )
                .order_by(NodeArtifact.id.asc())
                .all()
            )
            self.assertEqual(2, len(remaining))
            self.assertEqual([2, 3], [item.execution_index for item in remaining])

    def test_node_artifact_migration_does_not_backfill_existing_node_runs(self) -> None:
        with session_scope() as session:
            flowchart = Flowchart.create(session, name="artifact-no-backfill")
            plan = Plan.create(session, name="artifact-plan-no-backfill")
            node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_PLAN,
                ref_id=plan.id,
                x=0.0,
                y=0.0,
            )
            run = FlowchartRun.create(session, flowchart_id=flowchart.id, status="completed")
            run_id = run.id
            FlowchartRunNode.create(
                session,
                flowchart_run_id=run.id,
                flowchart_node_id=node.id,
                execution_index=1,
                status="succeeded",
                input_context_json=json.dumps({"legacy": True}, sort_keys=True),
                output_state_json=json.dumps(
                    {"node_type": FLOWCHART_NODE_TYPE_PLAN, "legacy": True},
                    sort_keys=True,
                ),
                routing_state_json=json.dumps({"route_key": "next"}, sort_keys=True),
            )
            before = (
                session.query(NodeArtifact)
                .where(NodeArtifact.flowchart_run_id == run_id)
                .count()
            )
            self.assertEqual(0, before)

        core_db.init_db()

        with session_scope() as session:
            after = (
                session.query(NodeArtifact)
                .where(NodeArtifact.flowchart_run_id == run_id)
                .count()
            )
            self.assertEqual(0, after)

    def test_run_llm_codex_always_includes_skip_git_repo_check(self) -> None:
        failed = subprocess.CompletedProcess(
            args=["codex", "exec"],
            returncode=1,
            stdout="",
            stderr="some other codex failure",
        )

        with patch.object(studio_tasks.Config, "CODEX_SKIP_GIT_REPO_CHECK", False), patch.object(
            studio_tasks.Config, "CODEX_MODEL", ""
        ), patch.object(studio_tasks, "_run_llm_process", return_value=failed) as run_mock:
            result = studio_tasks._run_llm(
                provider="codex",
                prompt="hello",
                mcp_configs={},
                model_config={},
            )

        self.assertEqual(1, result.returncode)
        self.assertEqual(1, run_mock.call_count)
        self.assertIn("--skip-git-repo-check", run_mock.call_args.args[0])

    def test_run_llm_codex_injects_api_key_env(self) -> None:
        failed = subprocess.CompletedProcess(
            args=["codex", "exec"],
            returncode=1,
            stdout="",
            stderr="unauthorized",
        )

        with patch.object(
            studio_tasks, "_load_codex_auth_key", return_value="test-codex-key"
        ), patch.object(studio_tasks, "_run_llm_process", return_value=failed) as run_mock:
            result = studio_tasks._run_llm(
                provider="codex",
                prompt="hello",
                mcp_configs={},
                model_config={},
            )

        self.assertEqual(1, result.returncode)
        env = run_mock.call_args.kwargs.get("env") or {}
        self.assertEqual("test-codex-key", env.get("OPENAI_API_KEY"))
        self.assertEqual("test-codex-key", env.get("CODEX_API_KEY"))

    def test_run_llm_gemini_injects_api_key_env(self) -> None:
        failed = subprocess.CompletedProcess(
            args=["gemini"],
            returncode=1,
            stdout="",
            stderr="unauthorized",
        )

        with patch.object(
            studio_tasks, "_load_gemini_auth_key", return_value="test-gemini-key"
        ), patch.object(
            studio_tasks, "_ensure_gemini_mcp_servers", return_value=None
        ), patch.object(
            studio_tasks, "_run_llm_process", return_value=failed
        ) as run_mock:
            result = studio_tasks._run_llm(
                provider="gemini",
                prompt="hello",
                mcp_configs={},
                model_config={},
            )

        self.assertEqual(1, result.returncode)
        env = run_mock.call_args.kwargs.get("env") or {}
        self.assertEqual("test-gemini-key", env.get("GEMINI_API_KEY"))
        self.assertEqual("test-gemini-key", env.get("GOOGLE_API_KEY"))


class FlowchartStage9ApiTests(StudioDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        template_dir = STUDIO_SRC / "web" / "templates"
        app = Flask("stage9-api-tests", template_folder=str(template_dir))
        app.config["TESTING"] = True
        app.secret_key = "stage9-tests"
        app.register_blueprint(studio_views.bp)
        self.client = app.test_client()

    def _create_flowchart(self, name: str) -> int:
        response = self.client.post(
            "/flowcharts",
            json={"name": name},
        )
        self.assertEqual(201, response.status_code)
        payload = response.get_json() or {}
        return int(payload["flowchart"]["id"])

    def test_new_flowchart_starts_with_single_start_node(self) -> None:
        flowchart_id = self._create_flowchart("Stage 9 Default Start")
        graph_response = self.client.get(f"/flowcharts/{flowchart_id}/graph")
        self.assertEqual(200, graph_response.status_code)
        graph_payload = graph_response.get_json() or {}
        nodes = graph_payload.get("nodes") or []
        start_nodes = [
            node
            for node in nodes
            if node.get("node_type") == FLOWCHART_NODE_TYPE_START
        ]
        self.assertEqual(1, len(start_nodes))
        self.assertEqual(1, len(nodes))
        self.assertTrue((graph_payload.get("validation") or {}).get("valid"))

    def test_flowchart_crud_and_graph_save_load(self) -> None:
        flowchart_id = self._create_flowchart("Stage 9 CRUD")
        list_response = self.client.get("/flowcharts?format=json")
        self.assertEqual(200, list_response.status_code)
        flowcharts = (list_response.get_json() or {}).get("flowcharts") or []
        self.assertIn(flowchart_id, {int(item["id"]) for item in flowcharts})

        update_response = self.client.post(
            f"/flowcharts/{flowchart_id}",
            json={"name": "Stage 9 CRUD Updated", "max_parallel_nodes": 2},
        )
        self.assertEqual(200, update_response.status_code)

        graph_response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "client_id": "n-start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    },
                    {
                        "client_id": "n-decision",
                        "node_type": FLOWCHART_NODE_TYPE_DECISION,
                        "x": 200,
                        "y": 20,
                        "config": {
                            "route_field_path": "latest_upstream.output_state.message"
                        },
                    },
                ],
                "edges": [
                    {
                        "source_node_id": "n-start",
                        "target_node_id": "n-decision",
                        "edge_mode": "solid",
                        "source_handle_id": "r1",
                        "target_handle_id": "l1",
                        "label": "to decision",
                    },
                    {
                        "source_node_id": "n-decision",
                        "target_node_id": "n-start",
                        "edge_mode": "solid",
                        "source_handle_id": "b2",
                        "target_handle_id": "t2",
                        "condition_key": "Start node executed.",
                        "label": "loop",
                    },
                ],
            },
        )
        self.assertEqual(200, graph_response.status_code)
        graph_payload = graph_response.get_json() or {}
        self.assertEqual(2, len(graph_payload.get("nodes") or []))
        self.assertEqual(2, len(graph_payload.get("edges") or []))
        self.assertTrue((graph_payload.get("validation") or {}).get("valid"))
        saved_edges = graph_payload.get("edges") or []
        saved_edge_map = {
            (edge.get("source_handle_id"), edge.get("target_handle_id")): edge
            for edge in saved_edges
        }
        self.assertIn(("r1", "l1"), saved_edge_map)
        self.assertEqual("to decision", saved_edge_map[("r1", "l1")].get("label"))
        self.assertEqual("solid", saved_edge_map[("r1", "l1")].get("edge_mode"))
        self.assertIn(("b2", "t2"), saved_edge_map)
        self.assertEqual("loop", saved_edge_map[("b2", "t2")].get("label"))
        self.assertEqual("solid", saved_edge_map[("b2", "t2")].get("edge_mode"))

        load_response = self.client.get(f"/flowcharts/{flowchart_id}/graph")
        self.assertEqual(200, load_response.status_code)
        loaded = load_response.get_json() or {}
        self.assertEqual(2, len(loaded.get("nodes") or []))
        self.assertEqual(2, len(loaded.get("edges") or []))
        self.assertTrue((loaded.get("validation") or {}).get("valid"))
        loaded_edge_map = {
            (edge.get("source_handle_id"), edge.get("target_handle_id")): edge
            for edge in (loaded.get("edges") or [])
        }
        self.assertIn(("r1", "l1"), loaded_edge_map)
        self.assertIn(("b2", "t2"), loaded_edge_map)

        delete_response = self.client.post(
            f"/flowcharts/{flowchart_id}/delete",
            json={},
        )
        self.assertEqual(200, delete_response.status_code)
        self.assertTrue((delete_response.get_json() or {}).get("deleted"))

    def test_graph_syncs_decision_conditions_from_solid_connectors(self) -> None:
        with session_scope() as session:
            MCPServer.create(
                session,
                name="llmctl-mcp",
                server_key="llmctl-mcp",
                config_json='{"command":"echo"}',
            )
        flowchart_id = self._create_flowchart("Stage 9 Decision Condition Sync")
        response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "client_id": "n-start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    },
                    {
                        "client_id": "n-decision",
                        "node_type": FLOWCHART_NODE_TYPE_DECISION,
                        "x": 180,
                        "y": 0,
                        "config": {
                            "decision_conditions": [
                                {
                                    "connector_id": "stale_connector",
                                    "condition_text": "stale",
                                }
                            ]
                        },
                    },
                    {
                        "client_id": "n-task-a",
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "x": 360,
                        "y": -60,
                        "config": {"task_prompt": "Task A"},
                    },
                    {
                        "client_id": "n-task-b",
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "x": 360,
                        "y": 60,
                        "config": {"task_prompt": "Task B"},
                    },
                ],
                "edges": [
                    {
                        "source_node_id": "n-start",
                        "target_node_id": "n-decision",
                        "edge_mode": "solid",
                    },
                    {
                        "source_node_id": "n-decision",
                        "target_node_id": "n-task-a",
                        "edge_mode": "solid",
                        "condition_key": "left_connector",
                    },
                    {
                        "source_node_id": "n-decision",
                        "target_node_id": "n-task-b",
                        "edge_mode": "solid",
                    },
                ],
            },
        )
        self.assertEqual(200, response.status_code)
        payload = response.get_json() or {}
        nodes = payload.get("nodes") or []
        decision_node = next(
            node for node in nodes if node.get("node_type") == FLOWCHART_NODE_TYPE_DECISION
        )
        synced_conditions = (decision_node.get("config") or {}).get("decision_conditions") or []
        self.assertEqual(
            [
                {"connector_id": "left_connector", "condition_text": ""},
                {"connector_id": "connector_1", "condition_text": ""},
            ],
            synced_conditions,
        )
        decision_edges = [
            edge
            for edge in (payload.get("edges") or [])
            if edge.get("source_node_id") == decision_node.get("id")
            and edge.get("edge_mode") == "solid"
        ]
        self.assertEqual(["left_connector", "connector_1"], [edge.get("condition_key") for edge in decision_edges])

    def test_graph_persists_attachment_ids_and_rejects_unsupported_node_types(self) -> None:
        with session_scope() as session:
            attachment = Attachment.create(
                session,
                file_name="context.txt",
                file_path="/tmp/context.txt",
                content_type="text/plain",
                size_bytes=12,
            )
            attachment_id = attachment.id

        flowchart_id = self._create_flowchart("Stage 9 Attachments")
        graph_before = self.client.get(f"/flowcharts/{flowchart_id}/graph")
        self.assertEqual(200, graph_before.status_code)
        existing_nodes = (graph_before.get_json() or {}).get("nodes") or []
        start_node_id = next(
            int(node["id"])
            for node in existing_nodes
            if node.get("node_type") == FLOWCHART_NODE_TYPE_START
        )
        save_response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "id": start_node_id,
                        "client_id": "n-start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    },
                    {
                        "client_id": "n-memory",
                        "node_type": FLOWCHART_NODE_TYPE_MEMORY,
                        "x": 120,
                        "y": 0,
                        "attachment_ids": [attachment_id],
                    },
                ],
                "edges": [
                    {
                        "source_node_id": "n-start",
                        "target_node_id": "n-memory",
                        "edge_mode": "solid",
                    }
                ],
            },
        )
        self.assertEqual(200, save_response.status_code)
        payload = save_response.get_json() or {}
        memory_node = next(
            node for node in (payload.get("nodes") or []) if node.get("node_type") == "memory"
        )
        self.assertIn(attachment_id, memory_node.get("attachment_ids") or [])

        invalid_response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "id": start_node_id,
                        "client_id": "n-start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                        "attachment_ids": [attachment_id],
                    }
                ],
                "edges": [],
            },
        )
        self.assertEqual(400, invalid_response.status_code)
        error_text = str((invalid_response.get_json() or {}).get("error") or "")
        self.assertIn("does not support attachments", error_text)

    def test_graph_allows_any_edge_handle_direction(self) -> None:
        flowchart_id = self._create_flowchart("Stage 9 Flexible Handles")
        response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "client_id": "n-start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    },
                    {
                        "client_id": "n-task",
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "x": 200,
                        "y": 20,
                        "config": {"task_prompt": "Hello"},
                    },
                ],
                "edges": [
                    {
                        "source_node_id": "n-start",
                        "target_node_id": "n-task",
                        "edge_mode": "solid",
                        "source_handle_id": "l1",
                        "target_handle_id": "r1",
                    }
                ],
            },
        )
        self.assertEqual(200, response.status_code)
        payload = response.get_json() or {}
        self.assertTrue((payload.get("validation") or {}).get("valid"))
        edges = payload.get("edges") or []
        self.assertEqual(1, len(edges))
        self.assertEqual("l1", edges[0].get("source_handle_id"))
        self.assertEqual("r1", edges[0].get("target_handle_id"))
        self.assertEqual("solid", edges[0].get("edge_mode"))

        delete_response = self.client.post(
            f"/flowcharts/{flowchart_id}/delete",
            json={},
        )
        self.assertEqual(200, delete_response.status_code)
        self.assertTrue((delete_response.get_json() or {}).get("deleted"))

    def test_delete_flowchart_removes_tasks_linked_to_flowchart_nodes(self) -> None:
        flowchart_id = self._create_flowchart("Stage 9 Delete Linked Tasks")
        graph_response = self.client.get(f"/flowcharts/{flowchart_id}/graph")
        self.assertEqual(200, graph_response.status_code)
        graph_payload = graph_response.get_json() or {}
        nodes = graph_payload.get("nodes") or []
        self.assertTrue(nodes)
        start_node_id = int(nodes[0]["id"])

        with session_scope() as session:
            task = AgentTask.create(
                session,
                flowchart_id=flowchart_id,
                flowchart_node_id=start_node_id,
                status="queued",
                kind="flowchart",
            )
            task_id = task.id

        delete_response = self.client.post(
            f"/flowcharts/{flowchart_id}/delete",
            json={},
        )
        self.assertEqual(200, delete_response.status_code)
        self.assertTrue((delete_response.get_json() or {}).get("deleted"))

        with session_scope() as session:
            self.assertIsNone(session.get(Flowchart, flowchart_id))
            self.assertIsNone(session.get(AgentTask, task_id))

    def test_graph_upsert_detaches_agent_tasks_before_deleting_removed_nodes(self) -> None:
        with session_scope() as session:
            MCPServer.create(
                session,
                name="llmctl-mcp",
                server_key="llmctl-mcp",
                config_json='{"command":"echo"}',
            )
        flowchart_id = self._create_flowchart("Stage 9 Graph Upsert Detach Linked Tasks")
        graph_response = self.client.get(f"/flowcharts/{flowchart_id}/graph")
        self.assertEqual(200, graph_response.status_code)
        graph_payload = graph_response.get_json() or {}
        start_node = next(
            node
            for node in (graph_payload.get("nodes") or [])
            if node.get("node_type") == FLOWCHART_NODE_TYPE_START
        )
        start_node_id = int(start_node["id"])

        initial_save_response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "id": start_node_id,
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    },
                    {
                        "client_id": "n-task-remove",
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "x": 200,
                        "y": 20,
                        "config": {"task_prompt": "Temporary task"},
                    },
                ],
                "edges": [
                    {
                        "source_node_id": start_node_id,
                        "target_node_id": "n-task-remove",
                        "edge_mode": "solid",
                    }
                ],
            },
        )
        self.assertEqual(200, initial_save_response.status_code)
        saved_payload = initial_save_response.get_json() or {}
        removable_task_node = next(
            node
            for node in (saved_payload.get("nodes") or [])
            if node.get("node_type") == FLOWCHART_NODE_TYPE_TASK
        )
        removable_task_node_id = int(removable_task_node["id"])

        with session_scope() as session:
            task = AgentTask.create(
                session,
                flowchart_id=flowchart_id,
                flowchart_node_id=removable_task_node_id,
                status="queued",
                kind="flowchart",
            )
            task_id = task.id

        remove_node_response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "id": start_node_id,
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    }
                ],
                "edges": [],
            },
        )
        self.assertEqual(200, remove_node_response.status_code)

        with session_scope() as session:
            persisted_task = session.get(AgentTask, task_id)
            self.assertIsNotNone(persisted_task)
            assert persisted_task is not None
            self.assertIsNone(persisted_task.flowchart_node_id)
            self.assertIsNone(session.get(FlowchartNode, removable_task_node_id))

    def test_graph_requires_edge_mode_in_edge_payload(self) -> None:
        flowchart_id = self._create_flowchart("Stage 9 Edge Mode Required")
        response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "client_id": "n-start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    },
                    {
                        "client_id": "n-task",
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "x": 200,
                        "y": 20,
                        "config": {"task_prompt": "Hello"},
                    },
                ],
                "edges": [
                    {
                        "source_node_id": "n-start",
                        "target_node_id": "n-task",
                    }
                ],
            },
        )
        self.assertEqual(400, response.status_code)
        self.assertIn("edges[0].edge_mode is required", (response.get_json() or {}).get("error", ""))

    def test_graph_rejects_invalid_edge_mode(self) -> None:
        flowchart_id = self._create_flowchart("Stage 9 Invalid Edge Mode")
        response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "client_id": "n-start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    },
                    {
                        "client_id": "n-task",
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "x": 200,
                        "y": 20,
                        "config": {"task_prompt": "Hello"},
                    },
                ],
                "edges": [
                    {
                        "source_node_id": "n-start",
                        "target_node_id": "n-task",
                        "edge_mode": "push",
                    }
                ],
            },
        )
        self.assertEqual(400, response.status_code)
        self.assertIn(
            "edges[0].edge_mode must be one of solid, dotted",
            (response.get_json() or {}).get("error", ""),
        )

    def test_graph_persists_dotted_edge_mode(self) -> None:
        flowchart_id = self._create_flowchart("Stage 9 Dotted Edge")
        response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "client_id": "n-start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    },
                    {
                        "client_id": "n-task",
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "x": 200,
                        "y": 20,
                        "config": {"task_prompt": "Hello"},
                    },
                ],
                "edges": [
                    {
                        "source_node_id": "n-start",
                        "target_node_id": "n-task",
                        "edge_mode": "dotted",
                    }
                ],
            },
        )
        self.assertEqual(200, response.status_code)
        edge_payload = ((response.get_json() or {}).get("edges") or [{}])[0]
        self.assertEqual("dotted", edge_payload.get("edge_mode"))

    def test_graph_allows_multiple_outputs_for_non_decision_nodes(self) -> None:
        flowchart_id = self._create_flowchart("Stage 9 Output Fanout")
        response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "client_id": "n-start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    },
                    {
                        "client_id": "n-task-a",
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "x": 200,
                        "y": -60,
                        "config": {"task_prompt": "A"},
                    },
                    {
                        "client_id": "n-task-b",
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "x": 200,
                        "y": 60,
                        "config": {"task_prompt": "B"},
                    },
                ],
                "edges": [
                    {
                        "source_node_id": "n-start",
                        "target_node_id": "n-task-a",
                        "edge_mode": "solid",
                    },
                    {
                        "source_node_id": "n-start",
                        "target_node_id": "n-task-b",
                        "edge_mode": "solid",
                    },
                ],
            },
        )
        self.assertEqual(200, response.status_code)
        payload = response.get_json() or {}
        self.assertTrue((payload.get("validation") or {}).get("valid"))

    def test_graph_allows_more_than_three_decision_outputs(self) -> None:
        flowchart_id = self._create_flowchart("Stage 9 Decision Output Fanout")
        response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "client_id": "n-start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    },
                    {
                        "client_id": "n-decision",
                        "node_type": FLOWCHART_NODE_TYPE_DECISION,
                        "x": 160,
                        "y": 0,
                    },
                    {
                        "client_id": "n-task-1",
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "x": 320,
                        "y": -120,
                        "config": {"task_prompt": "1"},
                    },
                    {
                        "client_id": "n-task-2",
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "x": 320,
                        "y": -40,
                        "config": {"task_prompt": "2"},
                    },
                    {
                        "client_id": "n-task-3",
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "x": 320,
                        "y": 40,
                        "config": {"task_prompt": "3"},
                    },
                    {
                        "client_id": "n-task-4",
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "x": 320,
                        "y": 120,
                        "config": {"task_prompt": "4"},
                    },
                ],
                "edges": [
                    {
                        "source_node_id": "n-start",
                        "target_node_id": "n-decision",
                        "edge_mode": "solid",
                    },
                    {
                        "source_node_id": "n-decision",
                        "target_node_id": "n-task-1",
                        "edge_mode": "solid",
                        "condition_key": "route_1",
                    },
                    {
                        "source_node_id": "n-decision",
                        "target_node_id": "n-task-2",
                        "edge_mode": "solid",
                        "condition_key": "route_2",
                    },
                    {
                        "source_node_id": "n-decision",
                        "target_node_id": "n-task-3",
                        "edge_mode": "solid",
                        "condition_key": "route_3",
                    },
                    {
                        "source_node_id": "n-decision",
                        "target_node_id": "n-task-4",
                        "edge_mode": "solid",
                        "condition_key": "route_4",
                    },
                ],
            },
        )
        self.assertEqual(200, response.status_code)
        payload = response.get_json() or {}
        self.assertTrue((payload.get("validation") or {}).get("valid"))
        self.assertEqual(
            5,
            len(
                [
                    edge
                    for edge in (payload.get("edges") or [])
                    if edge.get("source_node_id") is not None
                ]
            ),
        )

    def test_graph_rejects_mixed_edge_modes_for_same_pair(self) -> None:
        flowchart_id = self._create_flowchart("Stage 9 Mixed Mode Pair")
        response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "client_id": "n-start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    },
                    {
                        "client_id": "n-task",
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "x": 180,
                        "y": 0,
                        "config": {"task_prompt": "do work"},
                    },
                ],
                "edges": [
                    {
                        "source_node_id": "n-start",
                        "target_node_id": "n-task",
                        "edge_mode": "solid",
                    },
                    {
                        "source_node_id": "n-start",
                        "target_node_id": "n-task",
                        "edge_mode": "dotted",
                    },
                ],
            },
        )
        self.assertEqual(400, response.status_code)
        errors = (((response.get_json() or {}).get("validation") or {}).get("errors")) or []
        self.assertTrue(
            any("cannot mix solid and dotted modes" in str(error) for error in errors)
        )

    def test_graph_rejects_custom_fan_in_above_solid_parent_count(self) -> None:
        errors = studio_views._validate_flowchart_graph_snapshot(
            nodes=[
                {"id": 1, "node_type": FLOWCHART_NODE_TYPE_START, "x": 0, "y": 0, "config": {}},
                {
                    "id": 2,
                    "node_type": FLOWCHART_NODE_TYPE_TASK,
                    "x": 180,
                    "y": -40,
                    "config": {"task_prompt": "A"},
                },
                {
                    "id": 3,
                    "node_type": FLOWCHART_NODE_TYPE_TASK,
                    "x": 180,
                    "y": 40,
                    "config": {"task_prompt": "B"},
                },
                {
                    "id": 4,
                    "node_type": FLOWCHART_NODE_TYPE_TASK,
                    "x": 340,
                    "y": 0,
                    "config": {
                        "task_prompt": "Target",
                        "fan_in_mode": "custom",
                        "fan_in_custom_count": 3,
                    },
                },
            ],
            edges=[
                {"source_node_id": 1, "target_node_id": 2, "edge_mode": "solid"},
                {"source_node_id": 1, "target_node_id": 3, "edge_mode": "solid"},
                {"source_node_id": 2, "target_node_id": 4, "edge_mode": "solid"},
                {"source_node_id": 3, "target_node_id": 4, "edge_mode": "solid"},
            ],
        )
        self.assertTrue(any("fan_in_custom_count must be <=" in str(error) for error in errors))

    def test_graph_rejects_decision_fallback_connector_not_in_solid_edges(self) -> None:
        errors = studio_views._validate_flowchart_graph_snapshot(
            nodes=[
                {"id": 1, "node_type": FLOWCHART_NODE_TYPE_START, "x": 0, "y": 0, "config": {}},
                {
                    "id": 2,
                    "node_type": FLOWCHART_NODE_TYPE_DECISION,
                    "x": 120,
                    "y": 0,
                    "config": {"fallback_condition_key": "missing_connector"},
                },
                {
                    "id": 3,
                    "node_type": FLOWCHART_NODE_TYPE_TASK,
                    "x": 280,
                    "y": 0,
                    "config": {"task_prompt": "run"},
                },
            ],
            edges=[
                {"source_node_id": 1, "target_node_id": 2, "edge_mode": "solid"},
                {
                    "source_node_id": 2,
                    "target_node_id": 3,
                    "edge_mode": "solid",
                    "condition_key": "connector_1",
                },
            ],
        )
        self.assertTrue(any("fallback_condition_key" in str(error) for error in errors))

    def test_graph_uses_solid_edges_for_disconnected_detection(self) -> None:
        flowchart_id = self._create_flowchart("Stage 9 Solid Reachability")
        response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "client_id": "n-start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    },
                    {
                        "client_id": "n-task",
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "x": 180,
                        "y": 0,
                        "config": {"task_prompt": "do work"},
                    },
                ],
                "edges": [
                    {
                        "source_node_id": "n-start",
                        "target_node_id": "n-task",
                        "edge_mode": "dotted",
                    },
                ],
            },
        )
        self.assertEqual(400, response.status_code)
        errors = (((response.get_json() or {}).get("validation") or {}).get("errors")) or []
        self.assertTrue(
            any("Disconnected required nodes found" in str(error) for error in errors)
        )

    def test_graph_requires_decision_to_have_solid_outgoing_edge(self) -> None:
        flowchart_id = self._create_flowchart("Stage 9 Decision Solid Required")
        response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "client_id": "n-start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    },
                    {
                        "client_id": "n-decision",
                        "node_type": FLOWCHART_NODE_TYPE_DECISION,
                        "x": 120,
                        "y": 0,
                    },
                    {
                        "client_id": "n-task",
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "x": 260,
                        "y": 0,
                        "config": {"task_prompt": "do work"},
                    },
                ],
                "edges": [
                    {
                        "source_node_id": "n-start",
                        "target_node_id": "n-decision",
                        "edge_mode": "solid",
                    },
                    {
                        "source_node_id": "n-decision",
                        "target_node_id": "n-task",
                        "edge_mode": "dotted",
                        "condition_key": "ignored_route",
                    },
                ],
            },
        )
        self.assertEqual(400, response.status_code)
        errors = (((response.get_json() or {}).get("validation") or {}).get("errors")) or []
        self.assertTrue(
            any("must have at least one solid outgoing edge" in str(error) for error in errors)
        )

    def test_graph_allows_decision_condition_key_on_dotted_edges(self) -> None:
        flowchart_id = self._create_flowchart("Stage 9 Decision Dotted Condition Key")
        response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "client_id": "n-start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    },
                    {
                        "client_id": "n-decision",
                        "node_type": FLOWCHART_NODE_TYPE_DECISION,
                        "x": 120,
                        "y": 0,
                    },
                    {
                        "client_id": "n-task-a",
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "x": 280,
                        "y": -30,
                        "config": {"task_prompt": "A"},
                    },
                    {
                        "client_id": "n-task-b",
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "x": 280,
                        "y": 30,
                        "config": {"task_prompt": "B"},
                    },
                ],
                "edges": [
                    {
                        "source_node_id": "n-start",
                        "target_node_id": "n-decision",
                        "edge_mode": "solid",
                    },
                    {
                        "source_node_id": "n-decision",
                        "target_node_id": "n-task-a",
                        "edge_mode": "solid",
                        "condition_key": "route_a",
                    },
                    {
                        "source_node_id": "n-decision",
                        "target_node_id": "n-task-b",
                        "edge_mode": "dotted",
                        "condition_key": "ignored_route_b",
                    },
                ],
            },
        )
        self.assertEqual(200, response.status_code)
        self.assertTrue((response.get_json() or {}).get("validation", {}).get("valid"))

    def test_graph_rejects_non_decision_condition_key_on_dotted_edges(self) -> None:
        flowchart_id = self._create_flowchart("Stage 9 Dotted Condition Key Non Decision")
        response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "client_id": "n-start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    },
                    {
                        "client_id": "n-task",
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "x": 180,
                        "y": 0,
                        "config": {"task_prompt": "do work"},
                    },
                ],
                "edges": [
                    {
                        "source_node_id": "n-start",
                        "target_node_id": "n-task",
                        "edge_mode": "dotted",
                        "condition_key": "invalid",
                    },
                ],
            },
        )
        self.assertEqual(400, response.status_code)
        errors = (((response.get_json() or {}).get("validation") or {}).get("errors")) or []
        self.assertTrue(
            any("Only decision nodes may define condition_key on dotted edges" in str(error) for error in errors)
        )

    def test_graph_rejects_outgoing_edges_from_end_nodes(self) -> None:
        flowchart_id = self._create_flowchart("Stage 9 End Output Limit")
        response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "client_id": "n-start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    },
                    {
                        "client_id": "n-end",
                        "node_type": FLOWCHART_NODE_TYPE_END,
                        "x": 150,
                        "y": 0,
                    },
                    {
                        "client_id": "n-task",
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "x": 300,
                        "y": 0,
                        "config": {"task_prompt": "Do work"},
                    },
                ],
                "edges": [
                    {
                        "source_node_id": "n-start",
                        "target_node_id": "n-end",
                        "edge_mode": "solid",
                    },
                    {
                        "source_node_id": "n-end",
                        "target_node_id": "n-task",
                        "edge_mode": "solid",
                    },
                ],
            },
        )
        self.assertEqual(400, response.status_code)
        payload = response.get_json() or {}
        errors = ((payload.get("validation") or {}).get("errors")) or []
        self.assertTrue(any("End node" in str(error) for error in errors))

    def test_run_start_stop_and_status(self) -> None:
        flowchart_id = self._create_flowchart("Stage 9 Run")
        graph_response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "client_id": "n-start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    }
                ],
                "edges": [],
            },
        )
        self.assertEqual(200, graph_response.status_code)

        with patch.object(
            studio_views.run_flowchart, "delay", return_value=SimpleNamespace(id="job-123")
        ):
            run_response = self.client.post(f"/flowcharts/{flowchart_id}/run", json={})
        self.assertEqual(202, run_response.status_code)
        run_payload = (run_response.get_json() or {}).get("flowchart_run") or {}
        run_id = int(run_payload["id"])
        self.assertEqual("queued", run_payload["status"])

        status_response = self.client.get(f"/flowcharts/runs/{run_id}/status")
        self.assertEqual(200, status_response.status_code)
        status_payload = status_response.get_json() or {}
        self.assertEqual("queued", status_payload["status"])

        with patch.object(studio_views.celery_app.control, "revoke", return_value=None) as revoke_mock:
            stop_response = self.client.post(f"/flowcharts/runs/{run_id}/cancel", json={})
        self.assertEqual(200, stop_response.status_code)
        stop_payload = stop_response.get_json() or {}
        self.assertFalse(stop_payload["canceled"])
        self.assertEqual("stopped", stop_payload["flowchart_run"]["status"])
        self.assertEqual("stopped", stop_payload["action"])
        self.assertTrue(stop_payload["stop_requested"])
        self.assertEqual(1, revoke_mock.call_count)

        status_after_stop = self.client.get(f"/flowcharts/runs/{run_id}/status")
        self.assertEqual(200, status_after_stop.status_code)
        self.assertEqual("stopped", (status_after_stop.get_json() or {})["status"])

    def test_run_force_stop_sets_canceled(self) -> None:
        flowchart_id = self._create_flowchart("Stage 9 Force Stop")
        graph_response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "client_id": "n-start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    }
                ],
                "edges": [],
            },
        )
        self.assertEqual(200, graph_response.status_code)

        with patch.object(
            studio_views.run_flowchart, "delay", return_value=SimpleNamespace(id="job-456")
        ):
            run_response = self.client.post(f"/flowcharts/{flowchart_id}/run", json={})
        self.assertEqual(202, run_response.status_code)
        run_payload = (run_response.get_json() or {}).get("flowchart_run") or {}
        run_id = int(run_payload["id"])

        with patch.object(studio_views.celery_app.control, "revoke", return_value=None) as revoke_mock:
            force_response = self.client.post(
                f"/flowcharts/runs/{run_id}/cancel",
                json={"force": True},
            )
        self.assertEqual(200, force_response.status_code)
        force_payload = force_response.get_json() or {}
        self.assertTrue(force_payload["canceled"])
        self.assertEqual("canceled", force_payload["flowchart_run"]["status"])
        self.assertEqual("canceled", force_payload["action"])
        self.assertTrue(force_payload["force"])
        self.assertEqual(1, revoke_mock.call_count)
        _, revoke_kwargs = revoke_mock.call_args
        self.assertTrue(revoke_kwargs.get("terminate"))
        self.assertEqual("SIGTERM", revoke_kwargs.get("signal"))

    def test_graph_allows_task_inline_prompt_without_ref(self) -> None:
        flowchart_id = self._create_flowchart("Stage 9 Inline Task")
        graph_response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "client_id": "n-start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    },
                    {
                        "client_id": "n-task",
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "x": 160,
                        "y": 0,
                        "config": {"task_prompt": "Do something useful"},
                    },
                ],
                "edges": [
                    {
                        "source_node_id": "n-start",
                        "target_node_id": "n-task",
                        "edge_mode": "solid",
                    }
                ],
            },
        )
        self.assertEqual(200, graph_response.status_code)
        payload = graph_response.get_json() or {}
        self.assertTrue((payload.get("validation") or {}).get("valid"))
        task_node = next(
            node for node in (payload.get("nodes") or []) if node["node_type"] == FLOWCHART_NODE_TYPE_TASK
        )
        self.assertIsNone(task_node.get("ref_id"))

    def test_graph_persists_task_agent_binding_from_config(self) -> None:
        with session_scope() as session:
            agent = Agent.create(
                session,
                name="Stage 9 Task Agent",
                prompt_json=json.dumps({"instruction": "Use this agent."}),
            )
            agent_id = agent.id

        flowchart_id = self._create_flowchart("Stage 9 Task Agent Binding")
        graph_response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "client_id": "n-start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    },
                    {
                        "client_id": "n-task",
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "x": 160,
                        "y": 0,
                        "config": {
                            "task_prompt": "Do something useful",
                            "agent_id": agent_id,
                        },
                    },
                ],
                "edges": [
                    {
                        "source_node_id": "n-start",
                        "target_node_id": "n-task",
                        "edge_mode": "solid",
                    }
                ],
            },
        )
        self.assertEqual(200, graph_response.status_code)
        payload = graph_response.get_json() or {}
        task_node = next(
            node
            for node in (payload.get("nodes") or [])
            if node["node_type"] == FLOWCHART_NODE_TYPE_TASK
        )
        self.assertEqual(agent_id, (task_node.get("config") or {}).get("agent_id"))

    def test_graph_rejects_unknown_task_agent_binding(self) -> None:
        flowchart_id = self._create_flowchart("Stage 9 Invalid Task Agent Binding")
        graph_response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "client_id": "n-start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    },
                    {
                        "client_id": "n-task",
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "x": 160,
                        "y": 0,
                        "config": {
                            "task_prompt": "Do something useful",
                            "agent_id": 999999,
                        },
                    },
                ],
                "edges": [
                    {
                        "source_node_id": "n-start",
                        "target_node_id": "n-task",
                        "edge_mode": "solid",
                    }
                ],
            },
        )
        self.assertEqual(400, graph_response.status_code)
        self.assertIn(
            "nodes[1].config.agent_id 999999 was not found",
            str((graph_response.get_json() or {}).get("error") or ""),
        )

    def test_history_run_view_backfills_node_activity_tasks(self) -> None:
        with session_scope() as session:
            flowchart = Flowchart.create(session, name="Stage 9 History Backfill")
            start_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                x=0.0,
                y=0.0,
            )
            flowchart_run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="completed",
            )
            node_run = FlowchartRunNode.create(
                session,
                flowchart_run_id=flowchart_run.id,
                flowchart_node_id=start_node.id,
                execution_index=1,
                status="succeeded",
                input_context_json=json.dumps({"flowchart": {"run_id": flowchart_run.id}}),
                output_state_json=json.dumps({"message": "Start node executed."}),
            )
            flowchart_id = flowchart.id
            run_id = flowchart_run.id
            node_run_id = node_run.id
            start_node_id = start_node.id

        response = self.client.get(f"/flowcharts/{flowchart_id}/history/{run_id}")
        self.assertEqual(200, response.status_code)

        with session_scope() as session:
            stored_node_run = session.get(FlowchartRunNode, node_run_id)
            self.assertIsNotNone(stored_node_run)
            assert stored_node_run is not None
            self.assertIsNotNone(stored_node_run.agent_task_id)
            task = session.get(AgentTask, stored_node_run.agent_task_id)
            self.assertIsNotNone(task)
            assert task is not None
            self.assertEqual(flowchart_id, task.flowchart_id)
            self.assertEqual(run_id, task.flowchart_run_id)
            self.assertEqual(start_node_id, task.flowchart_node_id)

    def test_history_run_api_exposes_trigger_and_pulled_context_sources(self) -> None:
        with session_scope() as session:
            flowchart = Flowchart.create(session, name="Stage 9 Trace Metadata")
            start_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                x=0.0,
                y=0.0,
            )
            flowchart_run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="completed",
            )
            FlowchartRunNode.create(
                session,
                flowchart_run_id=flowchart_run.id,
                flowchart_node_id=start_node.id,
                execution_index=1,
                status="succeeded",
                input_context_json=json.dumps(
                    {
                        "trigger_sources": [
                            {
                                "source_edge_id": 11,
                                "source_node_id": 21,
                                "source_node_type": FLOWCHART_NODE_TYPE_TASK,
                                "edge_mode": "solid",
                            }
                        ],
                        "pulled_dotted_sources": [
                            {
                                "source_edge_id": 33,
                                "source_node_id": 44,
                                "source_node_type": FLOWCHART_NODE_TYPE_MEMORY,
                                "edge_mode": "dotted",
                            }
                        ],
                    }
                ),
                output_state_json=json.dumps({"message": "ok"}),
            )
            flowchart_id = flowchart.id
            run_id = flowchart_run.id

        response = self.client.get(f"/flowcharts/{flowchart_id}/history/{run_id}?format=json")
        self.assertEqual(200, response.status_code)
        payload = response.get_json() or {}
        node_runs = payload.get("node_runs") or []
        self.assertEqual(1, len(node_runs))
        node_run = node_runs[0]
        trigger_sources = node_run.get("trigger_sources") or []
        pulled_sources = node_run.get("pulled_dotted_sources") or []
        self.assertEqual(1, len(trigger_sources))
        self.assertEqual(11, trigger_sources[0].get("source_edge_id"))
        self.assertEqual("solid", trigger_sources[0].get("edge_mode"))
        self.assertEqual(1, len(pulled_sources))
        self.assertEqual(33, pulled_sources[0].get("source_edge_id"))
        self.assertEqual("dotted", pulled_sources[0].get("edge_mode"))

    def test_graph_allows_save_for_task_without_ref_or_inline_prompt(self) -> None:
        flowchart_id = self._create_flowchart("Stage 9 Invalid Task")
        graph_response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "client_id": "n-start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    },
                    {
                        "client_id": "n-task",
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "x": 160,
                        "y": 0,
                        "config": {},
                    },
                ],
                "edges": [
                    {
                        "source_node_id": "n-start",
                        "target_node_id": "n-task",
                        "edge_mode": "solid",
                    }
                ],
            },
        )
        self.assertEqual(200, graph_response.status_code)
        payload = graph_response.get_json() or {}
        validation = payload.get("validation") or {}
        self.assertFalse(bool(validation.get("valid")))
        self.assertTrue(
            any(
                "task node requires config.task_prompt" in str(item)
                for item in (validation.get("errors") or [])
            )
        )

        validate_response = self.client.get(f"/flowcharts/{flowchart_id}/validate")
        self.assertEqual(200, validate_response.status_code)
        validate_payload = validate_response.get_json() or {}
        self.assertFalse(bool(validate_payload.get("valid")))
        self.assertTrue(
            any(
                "task node requires config.task_prompt" in str(item)
                for item in (validate_payload.get("errors") or [])
            )
        )

        run_response = self.client.post(f"/flowcharts/{flowchart_id}/run", json={})
        self.assertEqual(400, run_response.status_code)
        run_payload = run_response.get_json() or {}
        run_validation = run_payload.get("validation") or {}
        self.assertFalse(bool(run_validation.get("valid")))
        self.assertTrue(
            any(
                "task node requires config.task_prompt" in str(item)
                for item in (run_validation.get("errors") or [])
            )
        )

    def test_graph_accepts_flowchart_node_with_ref_and_rejects_missing_ref(self) -> None:
        parent_flowchart_id = self._create_flowchart("Stage 9 Parent Flowchart")
        child_flowchart_id = self._create_flowchart("Stage 9 Child Flowchart")

        invalid_response = self.client.post(
            f"/flowcharts/{parent_flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "client_id": "start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    },
                    {
                        "client_id": "launch",
                        "node_type": FLOWCHART_NODE_TYPE_FLOWCHART,
                        "x": 180,
                        "y": 0,
                    },
                ],
                "edges": [
                    {
                        "source_node_id": "start",
                        "target_node_id": "launch",
                        "edge_mode": "solid",
                    },
                ],
            },
        )
        self.assertEqual(400, invalid_response.status_code)
        invalid_payload = invalid_response.get_json() or {}
        self.assertIn("requires ref_id", invalid_payload.get("error", ""))

        valid_response = self.client.post(
            f"/flowcharts/{parent_flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "client_id": "start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    },
                    {
                        "client_id": "launch",
                        "node_type": FLOWCHART_NODE_TYPE_FLOWCHART,
                        "ref_id": child_flowchart_id,
                        "x": 180,
                        "y": 0,
                    },
                ],
                "edges": [
                    {
                        "source_node_id": "start",
                        "target_node_id": "launch",
                        "edge_mode": "solid",
                    },
                ],
            },
        )
        self.assertEqual(200, valid_response.status_code)
        valid_payload = valid_response.get_json() or {}
        self.assertTrue((valid_payload.get("validation") or {}).get("valid"))
        flowchart_node = next(
            node
            for node in (valid_payload.get("nodes") or [])
            if node.get("node_type") == FLOWCHART_NODE_TYPE_FLOWCHART
        )
        self.assertEqual(child_flowchart_id, int(flowchart_node.get("ref_id") or 0))

    def test_graph_auto_assigns_specialized_node_refs_when_missing(self) -> None:
        flowchart_id = self._create_flowchart("Stage 9 Specialized Auto Ref Flowchart")

        create_response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "client_id": "start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    },
                    {
                        "client_id": "plan",
                        "node_type": FLOWCHART_NODE_TYPE_PLAN,
                        "x": 180,
                        "y": 0,
                        "config": {"action": "create_or_update_plan"},
                    },
                    {
                        "client_id": "milestone",
                        "node_type": FLOWCHART_NODE_TYPE_MILESTONE,
                        "x": 360,
                        "y": 0,
                        "config": {"action": "create_or_update"},
                    },
                    {
                        "client_id": "memory",
                        "node_type": FLOWCHART_NODE_TYPE_MEMORY,
                        "x": 540,
                        "y": 0,
                        "config": {"action": "add", "additive_prompt": "seed memory"},
                    },
                ],
                "edges": [
                    {
                        "source_node_id": "start",
                        "target_node_id": "plan",
                        "edge_mode": "solid",
                    },
                    {
                        "source_node_id": "plan",
                        "target_node_id": "milestone",
                        "edge_mode": "solid",
                    },
                    {
                        "source_node_id": "milestone",
                        "target_node_id": "memory",
                        "edge_mode": "solid",
                    },
                ],
            },
        )
        self.assertEqual(200, create_response.status_code)
        create_payload = create_response.get_json() or {}
        self.assertTrue((create_payload.get("validation") or {}).get("valid"))
        created_nodes = create_payload.get("nodes") or []
        node_by_type = {str(node.get("node_type")): node for node in created_nodes}

        plan_node = node_by_type.get(FLOWCHART_NODE_TYPE_PLAN) or {}
        milestone_node = node_by_type.get(FLOWCHART_NODE_TYPE_MILESTONE) or {}
        memory_node = node_by_type.get(FLOWCHART_NODE_TYPE_MEMORY) or {}
        self.assertGreater(int(plan_node.get("ref_id") or 0), 0)
        self.assertGreater(int(milestone_node.get("ref_id") or 0), 0)
        self.assertGreater(int(memory_node.get("ref_id") or 0), 0)

        update_response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "id": node_by_type[FLOWCHART_NODE_TYPE_START]["id"],
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    },
                    {
                        "id": plan_node["id"],
                        "node_type": FLOWCHART_NODE_TYPE_PLAN,
                        "x": 180,
                        "y": 0,
                        "config": {"action": "create_or_update_plan"},
                    },
                    {
                        "id": milestone_node["id"],
                        "node_type": FLOWCHART_NODE_TYPE_MILESTONE,
                        "x": 360,
                        "y": 0,
                        "config": {"action": "create_or_update"},
                    },
                    {
                        "id": memory_node["id"],
                        "node_type": FLOWCHART_NODE_TYPE_MEMORY,
                        "x": 540,
                        "y": 0,
                        "config": {"action": "add", "additive_prompt": "seed memory"},
                    },
                ],
                "edges": [
                    {
                        "source_node_id": node_by_type[FLOWCHART_NODE_TYPE_START]["id"],
                        "target_node_id": plan_node["id"],
                        "edge_mode": "solid",
                    },
                    {
                        "source_node_id": plan_node["id"],
                        "target_node_id": milestone_node["id"],
                        "edge_mode": "solid",
                    },
                    {
                        "source_node_id": milestone_node["id"],
                        "target_node_id": memory_node["id"],
                        "edge_mode": "solid",
                    },
                ],
            },
        )
        self.assertEqual(200, update_response.status_code)
        update_payload = update_response.get_json() or {}
        self.assertTrue((update_payload.get("validation") or {}).get("valid"))
        updated_node_by_type = {
            str(node.get("node_type")): node for node in (update_payload.get("nodes") or [])
        }
        self.assertEqual(
            int(plan_node.get("ref_id") or 0),
            int((updated_node_by_type.get(FLOWCHART_NODE_TYPE_PLAN) or {}).get("ref_id") or 0),
        )
        self.assertEqual(
            int(milestone_node.get("ref_id") or 0),
            int((updated_node_by_type.get(FLOWCHART_NODE_TYPE_MILESTONE) or {}).get("ref_id") or 0),
        )
        self.assertEqual(
            int(memory_node.get("ref_id") or 0),
            int((updated_node_by_type.get(FLOWCHART_NODE_TYPE_MEMORY) or {}).get("ref_id") or 0),
        )

        with session_scope() as session:
            self.assertIsNotNone(session.get(Plan, int(plan_node.get("ref_id") or 0)))
            self.assertIsNotNone(
                session.get(Milestone, int(milestone_node.get("ref_id") or 0))
            )
            self.assertIsNotNone(session.get(Memory, int(memory_node.get("ref_id") or 0)))

    def test_node_bound_utilities_do_not_inherit_template_bindings(self) -> None:
        with session_scope() as session:
            node_model = LLMModel.create(
                session,
                name="node-model",
                provider="codex",
                config_json="{}",
            )
            node_mcp = MCPServer.create(
                session,
                name="node-mcp",
                server_key="node-mcp",
                config_json='{"command":"echo"}',
            )
            node_script = Script.create(
                session,
                file_name="node.sh",
                content="#!/bin/sh\necho node\n",
                script_type=SCRIPT_TYPE_INIT,
            )
            node_model_id = node_model.id
            node_mcp_id = node_mcp.id
            node_script_id = node_script.id

        flowchart_id = self._create_flowchart("Stage 9 Utilities")
        graph_response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "client_id": "n-start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    },
                    {
                        "client_id": "n-task",
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "config": {"task_prompt": "Return route_key=done"},
                        "x": 120,
                        "y": 0,
                    },
                ],
                "edges": [
                    {
                        "source_node_id": "n-start",
                        "target_node_id": "n-task",
                        "edge_mode": "solid",
                    }
                ],
            },
        )
        self.assertEqual(200, graph_response.status_code)
        graph_payload = graph_response.get_json() or {}
        task_node = next(
            node for node in (graph_payload.get("nodes") or []) if node["node_type"] == "task"
        )
        task_node_id = int(task_node["id"])

        before = self.client.get(
            f"/flowcharts/{flowchart_id}/nodes/{task_node_id}/utilities"
        )
        self.assertEqual(200, before.status_code)
        before_node = (before.get_json() or {}).get("node") or {}
        self.assertIsNone(before_node.get("model_id"))
        self.assertEqual([], before_node.get("mcp_server_ids"))
        self.assertEqual([], before_node.get("script_ids"))

        set_model = self.client.post(
            f"/flowcharts/{flowchart_id}/nodes/{task_node_id}/model",
            json={"model_id": node_model_id},
        )
        self.assertEqual(200, set_model.status_code)
        attach_mcp = self.client.post(
            f"/flowcharts/{flowchart_id}/nodes/{task_node_id}/mcp-servers",
            json={"mcp_server_id": node_mcp_id},
        )
        self.assertEqual(200, attach_mcp.status_code)
        attach_script = self.client.post(
            f"/flowcharts/{flowchart_id}/nodes/{task_node_id}/scripts",
            json={"script_id": node_script_id},
        )
        self.assertEqual(200, attach_script.status_code)

        after = self.client.get(f"/flowcharts/{flowchart_id}/nodes/{task_node_id}/utilities")
        self.assertEqual(200, after.status_code)
        after_node = (after.get_json() or {}).get("node") or {}
        self.assertEqual(node_model_id, after_node.get("model_id"))
        self.assertIn(node_mcp_id, after_node.get("mcp_server_ids") or [])
        self.assertIn(node_script_id, after_node.get("script_ids") or [])

    def test_node_type_behaviors_task_plan_milestone_memory_decision(self) -> None:
        with session_scope() as session:
            llmctl_mcp = MCPServer.create(
                session,
                name="llmctl-mcp",
                server_key="llmctl-mcp",
                config_json='{"command":"echo"}',
            )
            custom_mcp = MCPServer.create(
                session,
                name="custom-mcp",
                server_key="custom-mcp",
                config_json='{"command":"echo"}',
            )
            model = LLMModel.create(
                session,
                name="integration-model",
                provider="codex",
                config_json="{}",
            )
            plan = Plan.create(session, name="integration-plan")
            stage = PlanStage.create(
                session,
                plan_id=plan.id,
                name="stage-1",
                position=1,
            )
            plan_task = PlanTask.create(
                session,
                plan_stage_id=stage.id,
                name="task-1",
                position=1,
            )
            milestone = Milestone.create(
                session,
                name="integration-milestone",
            )
            memory = Memory.create(session, description="before")
            plan_id = plan.id
            stage_id = stage.id
            plan_task_id = plan_task.id
            milestone_id = milestone.id
            memory_id = memory.id
            model_id = model.id
            llmctl_mcp_id = llmctl_mcp.id
            custom_mcp_id = custom_mcp.id

        flowchart_id = self._create_flowchart("Stage 9 Node Behaviors")
        graph_response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "client_id": "start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    },
                    {
                        "client_id": "task",
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "model_id": model_id,
                        "config": {"task_prompt": "Return structured JSON"},
                        "x": 100,
                        "y": 0,
                    },
                    {
                        "client_id": "plan",
                        "node_type": FLOWCHART_NODE_TYPE_PLAN,
                        "ref_id": plan_id,
                        "x": 200,
                        "y": 0,
                        "config": {
                            "action": "update_completion",
                            "patch": {
                                "mark_plan_complete": True,
                                "complete_stage_ids": [stage_id],
                                "complete_task_ids": [plan_task_id],
                            },
                        },
                    },
                    {
                        "client_id": "milestone",
                        "node_type": FLOWCHART_NODE_TYPE_MILESTONE,
                        "ref_id": milestone_id,
                        "x": 300,
                        "y": 0,
                        "config": {
                            "action": "mark_complete",
                            "additive_prompt": "milestone-updated",
                            "retention_mode": "ttl",
                            "retention_ttl_seconds": 3600,
                        },
                    },
                    {
                        "client_id": "memory",
                        "node_type": FLOWCHART_NODE_TYPE_MEMORY,
                        "ref_id": memory_id,
                        "x": 400,
                        "y": 0,
                        "mcp_server_ids": [custom_mcp_id],
                        "config": {
                            "action": "store",
                            "text_source_path": "latest_upstream.output_state.milestone.latest_update",
                        },
                    },
                ],
                "edges": [
                    {
                        "source_node_id": "start",
                        "target_node_id": "task",
                        "edge_mode": "solid",
                    },
                    {
                        "source_node_id": "task",
                        "target_node_id": "plan",
                        "edge_mode": "solid",
                    },
                    {
                        "source_node_id": "plan",
                        "target_node_id": "milestone",
                        "edge_mode": "solid",
                    },
                    {
                        "source_node_id": "milestone",
                        "target_node_id": "memory",
                        "edge_mode": "solid",
                    },
                ],
            },
        )
        self.assertEqual(200, graph_response.status_code)
        graph_payload = graph_response.get_json() or {}
        self.assertTrue(graph_payload.get("validation", {}).get("valid"))
        memory_graph_node = next(
            node
            for node in (graph_payload.get("nodes") or [])
            if node.get("node_type") == FLOWCHART_NODE_TYPE_MEMORY
        )
        self.assertEqual([llmctl_mcp_id], memory_graph_node.get("mcp_server_ids") or [])
        self.assertEqual("add", (memory_graph_node.get("config") or {}).get("action"))

        with patch.object(
            studio_views.run_flowchart, "delay", return_value=SimpleNamespace(id="job-node-types")
        ):
            run_response = self.client.post(f"/flowcharts/{flowchart_id}/run", json={})
        self.assertEqual(202, run_response.status_code)
        run_id = int(((run_response.get_json() or {}).get("flowchart_run") or {})["id"])

        fake_task_output = {
            "route_key": "continue",
            "note": "task-ok",
        }
        with patch.object(
            studio_tasks,
            "_run_llm",
            return_value=SimpleNamespace(
                args=[],
                returncode=0,
                stdout=json.dumps(fake_task_output),
                stderr="",
            ),
        ), patch.object(studio_tasks, "load_integration_settings", return_value={}), patch.object(
            studio_tasks, "resolve_enabled_llm_providers", return_value={"codex"}
        ), patch.object(studio_tasks, "resolve_default_model_id", return_value=None):
            studio_tasks.run_flowchart.run(flowchart_id, run_id)

        with session_scope() as session:
            run = session.get(FlowchartRun, run_id)
            self.assertEqual("completed", run.status)
            node_runs = (
                session.query(FlowchartRunNode)
                .where(FlowchartRunNode.flowchart_run_id == run_id)
                .order_by(FlowchartRunNode.id.asc())
                .all()
            )
            observed_types = {
                json.loads(item.output_state_json or "{}").get("node_type") for item in node_runs
            }
            self.assertEqual(
                {
                    FLOWCHART_NODE_TYPE_START,
                    FLOWCHART_NODE_TYPE_TASK,
                    FLOWCHART_NODE_TYPE_PLAN,
                    FLOWCHART_NODE_TYPE_MILESTONE,
                    FLOWCHART_NODE_TYPE_MEMORY,
                },
                observed_types,
            )

            plan = session.get(Plan, plan_id)
            stage = session.get(PlanStage, stage_id)
            plan_task = session.get(PlanTask, plan_task_id)
            milestone = session.get(Milestone, milestone_id)
            memory = session.get(Memory, memory_id)

            self.assertIsNotNone(plan.completed_at)
            self.assertIsNotNone(stage.completed_at)
            self.assertIsNotNone(plan_task.completed_at)
            self.assertTrue(milestone.completed)
            self.assertEqual("done", milestone.status)
            self.assertEqual(100, milestone.progress_percent)
            self.assertEqual("milestone-updated", milestone.latest_update)
            self.assertIn("milestone-updated", memory.description or "")
            milestone_artifacts = (
                session.query(NodeArtifact)
                .where(
                    NodeArtifact.flowchart_run_id == run_id,
                    NodeArtifact.artifact_type == NODE_ARTIFACT_TYPE_MILESTONE,
                )
                .order_by(NodeArtifact.id.asc())
                .all()
            )
            self.assertEqual(1, len(milestone_artifacts))
            artifact_payload = json.loads(milestone_artifacts[0].payload_json or "{}")
            self.assertEqual("mark_complete", artifact_payload.get("action"))
            self.assertEqual(
                "milestone-updated",
                artifact_payload.get("milestone", {}).get("latest_update"),
            )
            memory_artifacts = (
                session.query(NodeArtifact)
                .where(
                    NodeArtifact.flowchart_run_id == run_id,
                    NodeArtifact.artifact_type == NODE_ARTIFACT_TYPE_MEMORY,
                )
                .order_by(NodeArtifact.id.asc())
                .all()
            )
            self.assertEqual(1, len(memory_artifacts))
            memory_artifact_payload = json.loads(memory_artifacts[0].payload_json or "{}")
            self.assertEqual("add", memory_artifact_payload.get("action"))
            self.assertEqual(
                ["llmctl-mcp"],
                memory_artifact_payload.get("mcp_server_keys") or [],
            )

        run_detail = self.client.get(f"/flowcharts/runs/{run_id}")
        self.assertEqual(200, run_detail.status_code)
        run_payload = run_detail.get_json() or {}
        milestone_node_run = next(
            node_run
            for node_run in (run_payload.get("node_runs") or [])
            if (node_run.get("output_state") or {}).get("node_type")
            == FLOWCHART_NODE_TYPE_MILESTONE
        )
        artifact_history = milestone_node_run.get("artifact_history") or []
        self.assertEqual(1, len(artifact_history))
        self.assertEqual("milestone", artifact_history[0].get("artifact_type"))
        self.assertEqual(
            "mark_complete",
            (artifact_history[0].get("payload") or {}).get("action"),
        )
        memory_node_run = next(
            node_run
            for node_run in (run_payload.get("node_runs") or [])
            if (node_run.get("output_state") or {}).get("node_type")
            == FLOWCHART_NODE_TYPE_MEMORY
        )
        memory_artifact_history = memory_node_run.get("artifact_history") or []
        self.assertEqual(1, len(memory_artifact_history))
        self.assertEqual("memory", memory_artifact_history[0].get("artifact_type"))
        self.assertEqual(
            "add",
            (memory_artifact_history[0].get("payload") or {}).get("action"),
        )

    def test_flowchart_graph_rejects_memory_node_without_required_action(self) -> None:
        with session_scope() as session:
            MCPServer.create(
                session,
                name="llmctl-mcp",
                server_key="llmctl-mcp",
                config_json='{"command":"echo"}',
            )
            memory = Memory.create(session, description="requires-action-memory")
            memory_id = memory.id

        flowchart_id = self._create_flowchart("Memory Action Required")
        graph_response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "client_id": "start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    },
                    {
                        "client_id": "memory",
                        "node_type": FLOWCHART_NODE_TYPE_MEMORY,
                        "ref_id": memory_id,
                        "x": 250,
                        "y": 0,
                        "config": {},
                    },
                ],
                "edges": [
                    {
                        "source_node_id": "start",
                        "target_node_id": "memory",
                        "edge_mode": "solid",
                    },
                ],
            },
        )
        self.assertEqual(400, graph_response.status_code)
        payload = graph_response.get_json() or {}
        self.assertIn(
            "config.action is required and must be add or retrieve.",
            str(payload.get("error") or ""),
        )

    def test_flowchart_graph_rejects_plan_node_without_required_action(self) -> None:
        with session_scope() as session:
            plan = Plan.create(session, name="requires-plan-action")
            plan_id = plan.id

        flowchart_id = self._create_flowchart("Plan Action Required")
        graph_response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "client_id": "start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    },
                    {
                        "client_id": "plan",
                        "node_type": FLOWCHART_NODE_TYPE_PLAN,
                        "ref_id": plan_id,
                        "x": 250,
                        "y": 0,
                        "config": {},
                    },
                ],
                "edges": [
                    {
                        "source_node_id": "start",
                        "target_node_id": "plan",
                        "edge_mode": "solid",
                    },
                ],
            },
        )
        self.assertEqual(400, graph_response.status_code)
        payload = graph_response.get_json() or {}
        self.assertIn(
            "nodes[1].config.action is required for plan nodes.",
            str(payload.get("error") or ""),
        )

    def test_flowchart_graph_rejects_milestone_node_without_required_action(self) -> None:
        with session_scope() as session:
            milestone = Milestone.create(session, name="requires-milestone-action")
            milestone_id = milestone.id

        flowchart_id = self._create_flowchart("Milestone Action Required")
        graph_response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "client_id": "start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    },
                    {
                        "client_id": "milestone",
                        "node_type": FLOWCHART_NODE_TYPE_MILESTONE,
                        "ref_id": milestone_id,
                        "x": 250,
                        "y": 0,
                        "config": {},
                    },
                ],
                "edges": [
                    {
                        "source_node_id": "start",
                        "target_node_id": "milestone",
                        "edge_mode": "solid",
                    },
                ],
            },
        )
        self.assertEqual(400, graph_response.status_code)
        payload = graph_response.get_json() or {}
        self.assertIn(
            "nodes[1].config.action is required for milestone nodes.",
            str(payload.get("error") or ""),
        )

    def test_plan_artifact_endpoints_expose_queryable_payloads(self) -> None:
        with session_scope() as session:
            plan = Plan.create(session, name="plan-artifacts-api")
            stage = PlanStage.create(session, plan_id=plan.id, name="Stage API", position=1)
            task = PlanTask.create(session, plan_stage_id=stage.id, name="Task API", position=1)
            flowchart = Flowchart.create(session, name="plan-artifacts-api-flowchart")
            plan_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_PLAN,
                ref_id=plan.id,
                x=0.0,
                y=0.0,
            )
            run = FlowchartRun.create(session, flowchart_id=flowchart.id, status="completed")
            run_node = FlowchartRunNode.create(
                session,
                flowchart_run_id=run.id,
                flowchart_node_id=plan_node.id,
                execution_index=1,
                status="succeeded",
                output_state_json=json.dumps({"node_type": FLOWCHART_NODE_TYPE_PLAN}),
            )
            artifact = NodeArtifact.create(
                session,
                flowchart_id=flowchart.id,
                flowchart_node_id=plan_node.id,
                flowchart_run_id=run.id,
                flowchart_run_node_id=run_node.id,
                node_type=FLOWCHART_NODE_TYPE_PLAN,
                artifact_type=NODE_ARTIFACT_TYPE_PLAN,
                ref_id=plan.id,
                execution_index=1,
                variant_key=f"run-{run.id}-node-run-{run_node.id}",
                retention_mode="ttl",
                request_id="req-plan-artifact-api",
                correlation_id="corr-plan-artifact-api",
                payload_json=json.dumps(
                    {
                        "action": "complete_plan_item",
                        "completion_target": {
                            "plan_item_id": task.id,
                            "stage_key": "stage_api",
                            "task_key": "task_api",
                        },
                        "touched": {"stage_ids": [stage.id], "task_ids": [task.id]},
                    },
                    sort_keys=True,
                ),
            )
            plan_id = plan.id
            artifact_id = artifact.id
            flowchart_node_id = plan_node.id
            flowchart_run_id = run.id
            task_id = task.id

        headers = {
            "X-Request-ID": "req-plan-list-1",
            "X-Correlation-ID": "corr-plan-list-1",
        }
        list_response = self.client.get(
            (
                f"/plans/{plan_id}/artifacts?limit=5&offset=0"
                f"&flowchart_node_id={flowchart_node_id}&flowchart_run_id={flowchart_run_id}"
            ),
            headers=headers,
        )
        self.assertEqual(200, list_response.status_code)
        list_payload = list_response.get_json() or {}
        self.assertTrue(list_payload.get("ok"))
        self.assertEqual("req-plan-list-1", list_payload.get("request_id"))
        self.assertEqual("corr-plan-list-1", list_payload.get("correlation_id"))
        self.assertEqual(1, list_payload.get("count"))
        self.assertEqual(1, list_payload.get("total_count"))
        items = list_payload.get("items") or []
        self.assertEqual(1, len(items))
        self.assertEqual(NODE_ARTIFACT_TYPE_PLAN, items[0].get("artifact_type"))
        self.assertEqual(1, items[0].get("payload_version"))
        self.assertEqual([task_id], ((items[0].get("payload") or {}).get("touched") or {}).get("task_ids"))

        detail_response = self.client.get(
            f"/plans/{plan_id}/artifacts/{artifact_id}",
            headers={
                "X-Request-ID": "req-plan-detail-1",
                "X-Correlation-ID": "corr-plan-detail-1",
            },
        )
        self.assertEqual(200, detail_response.status_code)
        detail_payload = detail_response.get_json() or {}
        self.assertTrue(detail_payload.get("ok"))
        self.assertEqual("req-plan-detail-1", detail_payload.get("request_id"))
        self.assertEqual("corr-plan-detail-1", detail_payload.get("correlation_id"))
        item = detail_payload.get("item") or {}
        self.assertEqual(artifact_id, item.get("id"))
        self.assertEqual(1, item.get("payload_version"))
        completion_target = (item.get("payload") or {}).get("completion_target") or {}
        self.assertEqual(task_id, completion_target.get("plan_item_id"))
        self.assertEqual("stage_api", completion_target.get("stage_key"))
        self.assertEqual("task_api", completion_target.get("task_key"))

    def test_plan_artifact_delete_endpoint_removes_only_artifact(self) -> None:
        with session_scope() as session:
            plan = Plan.create(session, name="plan-artifacts-delete")
            flowchart = Flowchart.create(session, name="plan-artifacts-delete-flowchart")
            plan_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_PLAN,
                ref_id=plan.id,
                x=0.0,
                y=0.0,
            )
            run = FlowchartRun.create(session, flowchart_id=flowchart.id, status="completed")
            run_node = FlowchartRunNode.create(
                session,
                flowchart_run_id=run.id,
                flowchart_node_id=plan_node.id,
                execution_index=1,
                status="succeeded",
                output_state_json=json.dumps({"node_type": FLOWCHART_NODE_TYPE_PLAN}),
            )
            artifact = NodeArtifact.create(
                session,
                flowchart_id=flowchart.id,
                flowchart_node_id=plan_node.id,
                flowchart_run_id=run.id,
                flowchart_run_node_id=run_node.id,
                node_type=FLOWCHART_NODE_TYPE_PLAN,
                artifact_type=NODE_ARTIFACT_TYPE_PLAN,
                ref_id=plan.id,
                execution_index=1,
                variant_key=f"run-{run.id}-node-run-{run_node.id}",
                retention_mode="ttl",
                payload_json=json.dumps({"action": "create_or_update_plan"}, sort_keys=True),
            )
            plan_id = plan.id
            flowchart_node_id = plan_node.id
            artifact_id = artifact.id

        delete_response = self.client.delete(
            f"/plans/{plan_id}/artifacts/{artifact_id}",
            headers={
                "X-Request-ID": "req-plan-delete-1",
                "X-Correlation-ID": "corr-plan-delete-1",
            },
        )
        self.assertEqual(200, delete_response.status_code)
        delete_payload = delete_response.get_json() or {}
        self.assertTrue(delete_payload.get("ok"))
        self.assertTrue(delete_payload.get("deleted"))
        self.assertEqual("req-plan-delete-1", delete_payload.get("request_id"))
        self.assertEqual("corr-plan-delete-1", delete_payload.get("correlation_id"))

        with session_scope() as session:
            self.assertIsNone(session.get(NodeArtifact, artifact_id))
            self.assertIsNotNone(session.get(FlowchartNode, flowchart_node_id))

    def test_memory_artifact_endpoints_expose_queryable_payloads(self) -> None:
        with session_scope() as session:
            memory = Memory.create(session, description="memory-artifacts-api")
            flowchart = Flowchart.create(session, name="memory-artifacts-api-flowchart")
            memory_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                ref_id=memory.id,
                x=0.0,
                y=0.0,
            )
            run = FlowchartRun.create(session, flowchart_id=flowchart.id, status="completed")
            run_node = FlowchartRunNode.create(
                session,
                flowchart_run_id=run.id,
                flowchart_node_id=memory_node.id,
                execution_index=1,
                status="succeeded",
                output_state_json=json.dumps({"node_type": FLOWCHART_NODE_TYPE_MEMORY}),
            )
            artifact = NodeArtifact.create(
                session,
                flowchart_id=flowchart.id,
                flowchart_node_id=memory_node.id,
                flowchart_run_id=run.id,
                flowchart_run_node_id=run_node.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                artifact_type=NODE_ARTIFACT_TYPE_MEMORY,
                ref_id=memory.id,
                execution_index=1,
                variant_key=f"run-{run.id}-node-run-{run_node.id}",
                retention_mode="ttl",
                request_id="req-memory-artifact-api",
                correlation_id="corr-memory-artifact-api",
                payload_json=json.dumps(
                    {"action": "add", "effective_prompt": "remember this"},
                    sort_keys=True,
                ),
            )
            memory_id = memory.id
            artifact_id = artifact.id
            flowchart_node_id = memory_node.id
            flowchart_run_id = run.id

        list_response = self.client.get(
            (
                f"/memories/{memory_id}/artifacts?limit=5&offset=0"
                f"&flowchart_node_id={flowchart_node_id}&flowchart_run_id={flowchart_run_id}"
            ),
            headers={
                "X-Request-ID": "req-memory-list-1",
                "X-Correlation-ID": "corr-memory-list-1",
            },
        )
        self.assertEqual(200, list_response.status_code)
        list_payload = list_response.get_json() or {}
        self.assertTrue(list_payload.get("ok"))
        self.assertEqual("req-memory-list-1", list_payload.get("request_id"))
        self.assertEqual("corr-memory-list-1", list_payload.get("correlation_id"))
        self.assertEqual(1, list_payload.get("total_count"))
        items = list_payload.get("items") or []
        self.assertEqual(1, len(items))
        self.assertEqual(NODE_ARTIFACT_TYPE_MEMORY, items[0].get("artifact_type"))
        self.assertEqual("add", (items[0].get("payload") or {}).get("action"))

        detail_response = self.client.get(
            f"/memories/{memory_id}/artifacts/{artifact_id}",
            headers={
                "X-Request-ID": "req-memory-detail-1",
                "X-Correlation-ID": "corr-memory-detail-1",
            },
        )
        self.assertEqual(200, detail_response.status_code)
        detail_payload = detail_response.get_json() or {}
        self.assertTrue(detail_payload.get("ok"))
        self.assertEqual("req-memory-detail-1", detail_payload.get("request_id"))
        self.assertEqual("corr-memory-detail-1", detail_payload.get("correlation_id"))
        item = detail_payload.get("item") or {}
        self.assertEqual(artifact_id, item.get("id"))
        self.assertEqual("remember this", (item.get("payload") or {}).get("effective_prompt"))

    def test_memory_artifact_delete_endpoint_removes_only_artifact(self) -> None:
        with session_scope() as session:
            memory = Memory.create(session, description="memory-artifacts-delete")
            flowchart = Flowchart.create(session, name="memory-artifacts-delete-flowchart")
            memory_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                ref_id=memory.id,
                x=0.0,
                y=0.0,
            )
            run = FlowchartRun.create(session, flowchart_id=flowchart.id, status="completed")
            run_node = FlowchartRunNode.create(
                session,
                flowchart_run_id=run.id,
                flowchart_node_id=memory_node.id,
                execution_index=1,
                status="succeeded",
                output_state_json=json.dumps({"node_type": FLOWCHART_NODE_TYPE_MEMORY}),
            )
            artifact = NodeArtifact.create(
                session,
                flowchart_id=flowchart.id,
                flowchart_node_id=memory_node.id,
                flowchart_run_id=run.id,
                flowchart_run_node_id=run_node.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                artifact_type=NODE_ARTIFACT_TYPE_MEMORY,
                ref_id=memory.id,
                execution_index=1,
                variant_key=f"run-{run.id}-node-run-{run_node.id}",
                retention_mode="ttl",
                payload_json=json.dumps({"action": "add"}, sort_keys=True),
            )
            memory_id = memory.id
            flowchart_node_id = memory_node.id
            artifact_id = artifact.id

        delete_response = self.client.delete(
            f"/memories/{memory_id}/artifacts/{artifact_id}",
            headers={
                "X-Request-ID": "req-memory-delete-1",
                "X-Correlation-ID": "corr-memory-delete-1",
            },
        )
        self.assertEqual(200, delete_response.status_code)
        delete_payload = delete_response.get_json() or {}
        self.assertTrue(delete_payload.get("ok"))
        self.assertTrue(delete_payload.get("deleted"))
        self.assertEqual("req-memory-delete-1", delete_payload.get("request_id"))
        self.assertEqual("corr-memory-delete-1", delete_payload.get("correlation_id"))

        with session_scope() as session:
            self.assertIsNone(session.get(NodeArtifact, artifact_id))
            self.assertIsNotNone(session.get(FlowchartNode, flowchart_node_id))

    def test_milestone_artifact_endpoints_expose_queryable_payloads(self) -> None:
        with session_scope() as session:
            milestone = Milestone.create(session, name="milestone-artifacts-api")
            flowchart = Flowchart.create(session, name="milestone-artifacts-api-flowchart")
            milestone_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MILESTONE,
                ref_id=milestone.id,
                x=0.0,
                y=0.0,
            )
            run = FlowchartRun.create(session, flowchart_id=flowchart.id, status="completed")
            run_node = FlowchartRunNode.create(
                session,
                flowchart_run_id=run.id,
                flowchart_node_id=milestone_node.id,
                execution_index=1,
                status="succeeded",
                output_state_json=json.dumps({"node_type": FLOWCHART_NODE_TYPE_MILESTONE}),
            )
            artifact = NodeArtifact.create(
                session,
                flowchart_id=flowchart.id,
                flowchart_node_id=milestone_node.id,
                flowchart_run_id=run.id,
                flowchart_run_node_id=run_node.id,
                node_type=FLOWCHART_NODE_TYPE_MILESTONE,
                artifact_type=NODE_ARTIFACT_TYPE_MILESTONE,
                ref_id=milestone.id,
                execution_index=1,
                variant_key=f"run-{run.id}-node-run-{run_node.id}",
                retention_mode="ttl",
                request_id="req-milestone-artifact-api",
                correlation_id="corr-milestone-artifact-api",
                payload_json=json.dumps(
                    {"action": "mark_complete", "milestone": {"id": milestone.id, "status": "done"}},
                    sort_keys=True,
                ),
            )
            milestone_id = milestone.id
            artifact_id = artifact.id
            flowchart_node_id = milestone_node.id
            flowchart_run_id = run.id

        list_response = self.client.get(
            (
                f"/milestones/{milestone_id}/artifacts?limit=5&offset=0"
                f"&flowchart_node_id={flowchart_node_id}&flowchart_run_id={flowchart_run_id}"
            ),
            headers={
                "X-Request-ID": "req-milestone-list-1",
                "X-Correlation-ID": "corr-milestone-list-1",
            },
        )
        self.assertEqual(200, list_response.status_code)
        list_payload = list_response.get_json() or {}
        self.assertTrue(list_payload.get("ok"))
        self.assertEqual("req-milestone-list-1", list_payload.get("request_id"))
        self.assertEqual("corr-milestone-list-1", list_payload.get("correlation_id"))
        self.assertEqual(1, list_payload.get("total_count"))
        items = list_payload.get("items") or []
        self.assertEqual(1, len(items))
        self.assertEqual(NODE_ARTIFACT_TYPE_MILESTONE, items[0].get("artifact_type"))
        self.assertEqual("mark_complete", (items[0].get("payload") or {}).get("action"))

        detail_response = self.client.get(
            f"/milestones/{milestone_id}/artifacts/{artifact_id}",
            headers={
                "X-Request-ID": "req-milestone-detail-1",
                "X-Correlation-ID": "corr-milestone-detail-1",
            },
        )
        self.assertEqual(200, detail_response.status_code)
        detail_payload = detail_response.get_json() or {}
        self.assertTrue(detail_payload.get("ok"))
        self.assertEqual("req-milestone-detail-1", detail_payload.get("request_id"))
        self.assertEqual("corr-milestone-detail-1", detail_payload.get("correlation_id"))
        item = detail_payload.get("item") or {}
        self.assertEqual(artifact_id, item.get("id"))
        self.assertEqual("done", ((item.get("payload") or {}).get("milestone") or {}).get("status"))

    def test_milestone_artifact_delete_endpoint_removes_only_artifact(self) -> None:
        with session_scope() as session:
            milestone = Milestone.create(session, name="milestone-artifacts-delete")
            flowchart = Flowchart.create(session, name="milestone-artifacts-delete-flowchart")
            milestone_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MILESTONE,
                ref_id=milestone.id,
                x=0.0,
                y=0.0,
            )
            run = FlowchartRun.create(session, flowchart_id=flowchart.id, status="completed")
            run_node = FlowchartRunNode.create(
                session,
                flowchart_run_id=run.id,
                flowchart_node_id=milestone_node.id,
                execution_index=1,
                status="succeeded",
                output_state_json=json.dumps({"node_type": FLOWCHART_NODE_TYPE_MILESTONE}),
            )
            artifact = NodeArtifact.create(
                session,
                flowchart_id=flowchart.id,
                flowchart_node_id=milestone_node.id,
                flowchart_run_id=run.id,
                flowchart_run_node_id=run_node.id,
                node_type=FLOWCHART_NODE_TYPE_MILESTONE,
                artifact_type=NODE_ARTIFACT_TYPE_MILESTONE,
                ref_id=milestone.id,
                execution_index=1,
                variant_key=f"run-{run.id}-node-run-{run_node.id}",
                retention_mode="ttl",
                payload_json=json.dumps({"action": "mark_complete"}, sort_keys=True),
            )
            milestone_id = milestone.id
            flowchart_node_id = milestone_node.id
            artifact_id = artifact.id

        delete_response = self.client.delete(
            f"/milestones/{milestone_id}/artifacts/{artifact_id}",
            headers={
                "X-Request-ID": "req-milestone-delete-1",
                "X-Correlation-ID": "corr-milestone-delete-1",
            },
        )
        self.assertEqual(200, delete_response.status_code)
        delete_payload = delete_response.get_json() or {}
        self.assertTrue(delete_payload.get("ok"))
        self.assertTrue(delete_payload.get("deleted"))
        self.assertEqual("req-milestone-delete-1", delete_payload.get("request_id"))
        self.assertEqual("corr-milestone-delete-1", delete_payload.get("correlation_id"))

        with session_scope() as session:
            self.assertIsNone(session.get(NodeArtifact, artifact_id))
            self.assertIsNotNone(session.get(FlowchartNode, flowchart_node_id))

    def test_decision_artifact_endpoints_expose_routing_payload_contract(self) -> None:
        with session_scope() as session:
            flowchart = Flowchart.create(session, name="decision-artifacts-api-flowchart")
            decision_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_DECISION,
                x=0.0,
                y=0.0,
            )
            run = FlowchartRun.create(session, flowchart_id=flowchart.id, status="completed")
            run_node = FlowchartRunNode.create(
                session,
                flowchart_run_id=run.id,
                flowchart_node_id=decision_node.id,
                execution_index=1,
                status="succeeded",
                output_state_json=json.dumps({"node_type": FLOWCHART_NODE_TYPE_DECISION}),
            )
            artifact = NodeArtifact.create(
                session,
                flowchart_id=flowchart.id,
                flowchart_node_id=decision_node.id,
                flowchart_run_id=run.id,
                flowchart_run_node_id=run_node.id,
                node_type=FLOWCHART_NODE_TYPE_DECISION,
                artifact_type=NODE_ARTIFACT_TYPE_DECISION,
                ref_id=None,
                execution_index=1,
                variant_key=f"run-{run.id}-node-run-{run_node.id}",
                retention_mode="ttl",
                request_id="req-decision-artifact-api",
                correlation_id="corr-decision-artifact-api",
                payload_json=json.dumps(
                    {
                        "matched_connector_ids": ["approve_connector"],
                        "evaluations": [
                            {
                                "connector_id": "approve_connector",
                                "condition_text": "approved",
                                "matched": True,
                                "reason": "matched",
                            }
                        ],
                        "no_match": False,
                    },
                    sort_keys=True,
                ),
            )
            flowchart_id = flowchart.id
            flowchart_node_id = decision_node.id
            flowchart_run_id = run.id
            artifact_id = artifact.id

        list_response = self.client.get(
            (
                f"/flowcharts/{flowchart_id}/nodes/{flowchart_node_id}/decision-artifacts"
                f"?limit=5&offset=0&flowchart_run_id={flowchart_run_id}"
            ),
            headers={
                "X-Request-ID": "req-decision-list-1",
                "X-Correlation-ID": "corr-decision-list-1",
            },
        )
        self.assertEqual(200, list_response.status_code)
        list_payload = list_response.get_json() or {}
        self.assertTrue(list_payload.get("ok"))
        self.assertEqual("req-decision-list-1", list_payload.get("request_id"))
        self.assertEqual("corr-decision-list-1", list_payload.get("correlation_id"))
        items = list_payload.get("items") or []
        self.assertEqual(1, len(items))
        self.assertEqual(NODE_ARTIFACT_TYPE_DECISION, items[0].get("artifact_type"))
        routing_payload = items[0].get("payload") or {}
        self.assertEqual(["approve_connector"], routing_payload.get("matched_connector_ids"))
        self.assertFalse(routing_payload.get("no_match"))
        self.assertEqual("approve_connector", (routing_payload.get("evaluations") or [{}])[0].get("connector_id"))

        detail_response = self.client.get(
            f"/flowcharts/{flowchart_id}/nodes/{flowchart_node_id}/decision-artifacts/{artifact_id}",
            headers={
                "X-Request-ID": "req-decision-detail-1",
                "X-Correlation-ID": "corr-decision-detail-1",
            },
        )
        self.assertEqual(200, detail_response.status_code)
        detail_payload = detail_response.get_json() or {}
        self.assertTrue(detail_payload.get("ok"))
        self.assertEqual("req-decision-detail-1", detail_payload.get("request_id"))
        self.assertEqual("corr-decision-detail-1", detail_payload.get("correlation_id"))
        detail_item = detail_payload.get("item") or {}
        self.assertEqual(artifact_id, detail_item.get("id"))
        self.assertEqual(
            ["approve_connector"],
            (detail_item.get("payload") or {}).get("matched_connector_ids"),
        )

    def test_plan_artifact_list_invalid_limit_uses_error_envelope(self) -> None:
        with session_scope() as session:
            plan = Plan.create(session, name="plan-artifacts-errors")
            plan_id = plan.id

        response = self.client.get(
            f"/plans/{plan_id}/artifacts?limit=0",
            headers={
                "X-Request-ID": "req-plan-error-1",
                "X-Correlation-ID": "corr-plan-error-1",
            },
        )
        self.assertEqual(400, response.status_code)
        payload = response.get_json() or {}
        self.assertFalse(payload.get("ok"))
        error = payload.get("error") or {}
        self.assertEqual("invalid_request", error.get("code"))
        self.assertEqual("req-plan-error-1", error.get("request_id"))
        self.assertEqual("corr-plan-error-1", payload.get("correlation_id"))


if __name__ == "__main__":
    unittest.main()

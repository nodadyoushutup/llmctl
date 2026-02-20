from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

import core.db as core_db
from core.config import Config
from core.db import session_scope
from core.models import (
    FLOWCHART_NODE_TYPE_DECISION,
    FLOWCHART_NODE_TYPE_MEMORY,
    FLOWCHART_NODE_TYPE_START,
    FLOWCHART_NODE_TYPE_TASK,
    Flowchart,
    FlowchartEdge,
    FlowchartNode,
    FlowchartRun,
    FlowchartRunNode,
)
from services import tasks as studio_tasks
import web.views as studio_views


class StudioDbTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp_dir = Path(self._tmp.name)
        self._orig_db_uri = Config.SQLALCHEMY_DATABASE_URI
        self._orig_workspaces_dir = Config.WORKSPACES_DIR
        Config.SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_dir / 'connector-stage6.sqlite3'}"
        Config.WORKSPACES_DIR = str(tmp_dir / "workspaces")
        Path(Config.WORKSPACES_DIR).mkdir(parents=True, exist_ok=True)
        self._reset_engine()

    def tearDown(self) -> None:
        self._dispose_engine()
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


class FlowchartConnectorStage6UnitTests(StudioDbTestCase):
    def _invoke_flowchart_run(self, flowchart_id: int, run_id: int) -> None:
        with (
            patch.object(studio_tasks, "load_integration_settings", return_value={}),
            patch.object(studio_tasks, "resolve_enabled_llm_providers", return_value=set()),
            patch.object(studio_tasks, "resolve_default_model_id", return_value=None),
        ):
            studio_tasks.run_flowchart.run(flowchart_id, run_id)

    def test_validator_requires_edge_mode(self) -> None:
        nodes = [
            {"id": 1, "node_type": FLOWCHART_NODE_TYPE_START, "x": 0, "y": 0, "config": {}},
            {
                "id": 2,
                "node_type": FLOWCHART_NODE_TYPE_TASK,
                "x": 120,
                "y": 0,
                "config": {"task_prompt": "hello"},
            },
        ]
        errors = studio_views._validate_flowchart_graph_snapshot(
            nodes,
            [
                {
                    "source_node_id": 1,
                    "target_node_id": 2,
                }
            ],
        )
        self.assertTrue(
            any("must define edge_mode as solid or dotted" in str(error) for error in errors)
        )

    def test_validator_rejects_mixed_modes_for_same_pair(self) -> None:
        nodes = [
            {"id": 1, "node_type": FLOWCHART_NODE_TYPE_START, "x": 0, "y": 0, "config": {}},
            {
                "id": 2,
                "node_type": FLOWCHART_NODE_TYPE_TASK,
                "x": 120,
                "y": 0,
                "config": {"task_prompt": "hello"},
            },
        ]
        errors = studio_views._validate_flowchart_graph_snapshot(
            nodes,
            [
                {"source_node_id": 1, "target_node_id": 2, "edge_mode": "solid"},
                {"source_node_id": 1, "target_node_id": 2, "edge_mode": "dotted"},
            ],
        )
        self.assertTrue(
            any("cannot mix solid and dotted modes" in str(error) for error in errors)
        )

    def test_decision_route_resolution_uses_only_solid_edges(self) -> None:
        selected = studio_tasks._resolve_flowchart_outgoing_edges(
            node_type=FLOWCHART_NODE_TYPE_DECISION,
            node_config={},
            outgoing_edges=[
                {"id": 10, "edge_mode": "dotted", "condition_key": "approve"},
                {"id": 11, "edge_mode": "solid", "condition_key": "approve"},
                {"id": 12, "edge_mode": "solid", "condition_key": "reject"},
            ],
            routing_state={"route_key": "approve"},
        )
        self.assertEqual([11], [edge["id"] for edge in selected])

    def test_dotted_context_pull_assembly(self) -> None:
        context = studio_tasks._build_flowchart_input_context(
            flowchart_id=88,
            run_id=99,
            node_id=7,
            node_type=FLOWCHART_NODE_TYPE_MEMORY,
            execution_index=2,
            total_execution_count=5,
            incoming_edges=[
                {
                    "id": 101,
                    "source_node_id": 2,
                    "target_node_id": 7,
                    "edge_mode": "solid",
                    "condition_key": "",
                },
                {
                    "id": 102,
                    "source_node_id": 3,
                    "target_node_id": 7,
                    "edge_mode": "dotted",
                    "condition_key": "",
                },
            ],
            latest_results={
                2: {"node_type": FLOWCHART_NODE_TYPE_TASK, "output_state": {"value": "trigger"}},
                3: {"node_type": FLOWCHART_NODE_TYPE_MEMORY, "output_state": {"value": "pull"}},
            },
            upstream_results=None,
        )
        trigger_sources = context.get("trigger_sources") or []
        pulled_sources = context.get("pulled_dotted_sources") or []
        self.assertEqual(1, len(trigger_sources))
        self.assertEqual(1, len(pulled_sources))
        self.assertEqual("solid", trigger_sources[0].get("edge_mode"))
        self.assertEqual("dotted", pulled_sources[0].get("edge_mode"))

    def test_runtime_fan_out_one_to_many_solid_edges(self) -> None:
        with session_scope() as session:
            flowchart = Flowchart.create(session, name="stage6-fan-out")
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
                x=150.0,
                y=-50.0,
            )
            right_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=150.0,
                y=50.0,
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=left_node.id,
                edge_mode="solid",
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=right_node.id,
                edge_mode="solid",
            )
            flowchart_run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="queued",
            )
            flowchart_id = flowchart.id
            run_id = flowchart_run.id
            start_node_id = start_node.id
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
                [start_node_id, left_node_id, right_node_id],
                [item.flowchart_node_id for item in node_runs],
            )

    def test_runtime_fan_in_pull_only_with_two_dotted_sources(self) -> None:
        with session_scope() as session:
            flowchart = Flowchart.create(session, name="stage6-fan-in-dotted")
            start_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                x=0.0,
                y=0.0,
            )
            dotted_a = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=120.0,
                y=-90.0,
            )
            dotted_b = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=120.0,
                y=90.0,
            )
            trigger_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=120.0,
                y=0.0,
            )
            target_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=260.0,
                y=0.0,
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=dotted_a.id,
                edge_mode="solid",
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=dotted_b.id,
                edge_mode="solid",
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=trigger_node.id,
                edge_mode="solid",
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=dotted_a.id,
                target_node_id=target_node.id,
                edge_mode="dotted",
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=dotted_b.id,
                target_node_id=target_node.id,
                edge_mode="dotted",
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=trigger_node.id,
                target_node_id=target_node.id,
                edge_mode="solid",
            )
            flowchart_run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="queued",
            )
            flowchart_id = flowchart.id
            run_id = flowchart_run.id
            dotted_a_id = dotted_a.id
            dotted_b_id = dotted_b.id
            trigger_node_id = trigger_node.id
            target_node_id = target_node.id

        self._invoke_flowchart_run(flowchart_id, run_id)

        with session_scope() as session:
            run = session.get(FlowchartRun, run_id)
            assert run is not None
            self.assertEqual("completed", run.status)
            target_runs = (
                session.query(FlowchartRunNode)
                .where(
                    FlowchartRunNode.flowchart_run_id == run_id,
                    FlowchartRunNode.flowchart_node_id == target_node_id,
                )
                .all()
            )
            self.assertEqual(1, len(target_runs))
            input_context = json.loads(target_runs[0].input_context_json or "{}")
            upstream_nodes = input_context.get("upstream_nodes") or []
            dotted_upstream_nodes = input_context.get("dotted_upstream_nodes") or []
            self.assertEqual(1, len(upstream_nodes))
            self.assertEqual(trigger_node_id, upstream_nodes[0].get("node_id"))
            self.assertEqual(
                [dotted_a_id, dotted_b_id],
                sorted(item.get("node_id") for item in dotted_upstream_nodes),
            )

    def test_runtime_fan_in_any_triggers_on_each_parent_token(self) -> None:
        with session_scope() as session:
            flowchart = Flowchart.create(session, name="stage6-fan-in-any")
            start_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                x=0.0,
                y=0.0,
            )
            left_parent = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=120.0,
                y=-50.0,
            )
            right_parent = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=120.0,
                y=50.0,
            )
            target_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=260.0,
                y=0.0,
                config_json=json.dumps({"fan_in_mode": "any"}, sort_keys=True),
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=left_parent.id,
                edge_mode="solid",
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=right_parent.id,
                edge_mode="solid",
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=left_parent.id,
                target_node_id=target_node.id,
                edge_mode="solid",
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=right_parent.id,
                target_node_id=target_node.id,
                edge_mode="solid",
            )
            flowchart_run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="queued",
            )
            flowchart_id = flowchart.id
            run_id = flowchart_run.id
            target_node_id = target_node.id

        self._invoke_flowchart_run(flowchart_id, run_id)

        with session_scope() as session:
            run = session.get(FlowchartRun, run_id)
            assert run is not None
            self.assertEqual("completed", run.status)
            target_runs = (
                session.query(FlowchartRunNode)
                .where(
                    FlowchartRunNode.flowchart_run_id == run_id,
                    FlowchartRunNode.flowchart_node_id == target_node_id,
                )
                .all()
            )
            self.assertEqual(2, len(target_runs))

    def test_runtime_fan_in_custom_requires_two_parents(self) -> None:
        with session_scope() as session:
            flowchart = Flowchart.create(session, name="stage6-fan-in-custom")
            start_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                x=0.0,
                y=0.0,
            )
            left_parent = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=120.0,
                y=-50.0,
            )
            right_parent = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=120.0,
                y=50.0,
            )
            target_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=260.0,
                y=0.0,
                config_json=json.dumps(
                    {"fan_in_mode": "custom", "fan_in_custom_count": 2},
                    sort_keys=True,
                ),
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=left_parent.id,
                edge_mode="solid",
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=right_parent.id,
                edge_mode="solid",
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=left_parent.id,
                target_node_id=target_node.id,
                edge_mode="solid",
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=right_parent.id,
                target_node_id=target_node.id,
                edge_mode="solid",
            )
            flowchart_run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="queued",
            )
            flowchart_id = flowchart.id
            run_id = flowchart_run.id
            target_node_id = target_node.id

        self._invoke_flowchart_run(flowchart_id, run_id)

        with session_scope() as session:
            run = session.get(FlowchartRun, run_id)
            assert run is not None
            self.assertEqual("completed", run.status)
            target_runs = (
                session.query(FlowchartRunNode)
                .where(
                    FlowchartRunNode.flowchart_run_id == run_id,
                    FlowchartRunNode.flowchart_node_id == target_node_id,
                )
                .all()
            )
            self.assertEqual(1, len(target_runs))
            target_input_context = json.loads(target_runs[0].input_context_json or "{}")
            upstream_nodes = target_input_context.get("upstream_nodes") or []
            self.assertEqual(2, len(upstream_nodes))

    def test_runtime_mixed_loop_hits_guardrail(self) -> None:
        with session_scope() as session:
            flowchart = Flowchart.create(
                session,
                name="stage6-mixed-loop-guardrail",
                max_node_executions=1,
            )
            start_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                x=0.0,
                y=0.0,
            )
            loop_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=120.0,
                y=0.0,
            )
            observer_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=240.0,
                y=0.0,
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=loop_node.id,
                edge_mode="solid",
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=loop_node.id,
                target_node_id=start_node.id,
                edge_mode="solid",
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=loop_node.id,
                target_node_id=observer_node.id,
                edge_mode="dotted",
            )
            flowchart_run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="queued",
            )
            flowchart_id = flowchart.id
            run_id = flowchart_run.id
            loop_node_id = loop_node.id
            observer_node_id = observer_node.id

        self._invoke_flowchart_run(flowchart_id, run_id)

        with session_scope() as session:
            run = session.get(FlowchartRun, run_id)
            assert run is not None
            self.assertEqual("failed", run.status)
            failed_node = (
                session.query(FlowchartRunNode)
                .where(
                    FlowchartRunNode.flowchart_run_id == run_id,
                    FlowchartRunNode.flowchart_node_id == loop_node_id,
                    FlowchartRunNode.status == "failed",
                )
                .first()
            )
            self.assertIsNotNone(failed_node)
            assert failed_node is not None
            self.assertIn("max_node_executions", str(failed_node.error or ""))
            observer_runs = (
                session.query(FlowchartRunNode)
                .where(
                    FlowchartRunNode.flowchart_run_id == run_id,
                    FlowchartRunNode.flowchart_node_id == observer_node_id,
                )
                .all()
            )
            self.assertEqual([], observer_runs)

    def test_migration_compatibility_existing_edges_default_to_solid(self) -> None:
        with session_scope() as session:
            flowchart = Flowchart.create(session, name="stage6-migration-default-solid")
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
                x=140.0,
                y=0.0,
            )
            edge = FlowchartEdge.create(
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
            flowchart_id = flowchart.id
            run_id = flowchart_run.id
            task_node_id = task_node.id
            self.assertEqual("solid", edge.edge_mode)

        self._invoke_flowchart_run(flowchart_id, run_id)

        with session_scope() as session:
            run = session.get(FlowchartRun, run_id)
            assert run is not None
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


class FlowchartConnectorStage6ApiTests(StudioDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        template_dir = STUDIO_SRC / "web" / "templates"
        app = Flask("connector-stage6-api-tests", template_folder=str(template_dir))
        app.config["TESTING"] = True
        app.secret_key = "connector-stage6-tests"
        app.register_blueprint(studio_views.bp)
        self.client = app.test_client()

    def _create_flowchart(self, name: str) -> int:
        response = self.client.post("/flowcharts", json={"name": name})
        self.assertEqual(201, response.status_code)
        payload = response.get_json() or {}
        return int(payload["flowchart"]["id"])

    def _default_start_node_id(self, flowchart_id: int) -> int:
        response = self.client.get(f"/flowcharts/{flowchart_id}/graph")
        self.assertEqual(200, response.status_code)
        payload = response.get_json() or {}
        start_nodes = [
            node
            for node in (payload.get("nodes") or [])
            if node.get("node_type") == FLOWCHART_NODE_TYPE_START
        ]
        self.assertEqual(1, len(start_nodes))
        return int(start_nodes[0]["id"])

    def test_edge_inspector_mode_toggle_persistence(self) -> None:
        flowchart_id = self._create_flowchart("stage6-ui-toggle")
        start_node_id = self._default_start_node_id(flowchart_id)

        initial_save = self.client.post(
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
                        "client_id": "n-task",
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "x": 200,
                        "y": 0,
                        "config": {"task_prompt": "work"},
                    },
                    {
                        "client_id": "n-bridge",
                        "node_type": FLOWCHART_NODE_TYPE_MEMORY,
                        "x": 100,
                        "y": 80,
                    },
                ],
                "edges": [
                    {
                        "source_node_id": start_node_id,
                        "target_node_id": "n-bridge",
                        "edge_mode": "solid",
                    },
                    {
                        "source_node_id": "n-bridge",
                        "target_node_id": "n-task",
                        "edge_mode": "solid",
                    },
                    {
                        "source_node_id": start_node_id,
                        "target_node_id": "n-task",
                        "edge_mode": "solid",
                    }
                ],
            },
        )
        self.assertEqual(200, initial_save.status_code)
        initial_payload = initial_save.get_json() or {}
        task_node = next(
            node
            for node in (initial_payload.get("nodes") or [])
            if node.get("node_type") == FLOWCHART_NODE_TYPE_TASK
        )
        bridge_node = next(
            node
            for node in (initial_payload.get("nodes") or [])
            if node.get("node_type") == FLOWCHART_NODE_TYPE_MEMORY
        )
        task_node_id = int(task_node["id"])
        bridge_node_id = int(bridge_node["id"])

        toggle_save = self.client.post(
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
                        "id": task_node_id,
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "x": 200,
                        "y": 0,
                        "config": {"task_prompt": "work"},
                    },
                    {
                        "id": bridge_node_id,
                        "node_type": FLOWCHART_NODE_TYPE_MEMORY,
                        "x": 100,
                        "y": 80,
                    },
                ],
                "edges": [
                    {
                        "source_node_id": start_node_id,
                        "target_node_id": bridge_node_id,
                        "edge_mode": "solid",
                    },
                    {
                        "source_node_id": bridge_node_id,
                        "target_node_id": task_node_id,
                        "edge_mode": "solid",
                    },
                    {
                        "source_node_id": start_node_id,
                        "target_node_id": task_node_id,
                        "edge_mode": "dotted",
                    }
                ],
            },
        )
        self.assertEqual(200, toggle_save.status_code)

        loaded = self.client.get(f"/flowcharts/{flowchart_id}/graph")
        self.assertEqual(200, loaded.status_code)
        loaded_payload = loaded.get_json() or {}
        toggled_edges = [
            edge
            for edge in (loaded_payload.get("edges") or [])
            if int(edge.get("source_node_id") or 0) == start_node_id
            and int(edge.get("target_node_id") or 0) == task_node_id
        ]
        self.assertEqual(1, len(toggled_edges))
        self.assertEqual("dotted", toggled_edges[0].get("edge_mode"))

    def test_edge_visual_style_rules_selected_and_dotted(self) -> None:
        flowchart_id = self._create_flowchart("stage6-ui-style-rules")
        response = self.client.get(f"/flowcharts/{flowchart_id}")
        self.assertEqual(200, response.status_code)
        html = response.get_data(as_text=True)
        self.assertIn(".flow-edge-path.is-dotted", html)
        self.assertIn("stroke-dasharray: 7 5;", html)
        self.assertIn(".flow-edge-path.is-selected", html)

    def test_graph_save_load_roundtrip_with_edge_modes(self) -> None:
        flowchart_id = self._create_flowchart("stage6-ui-roundtrip")
        start_node_id = self._default_start_node_id(flowchart_id)

        save_response = self.client.post(
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
                        "client_id": "n-task",
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "x": 210,
                        "y": 20,
                        "config": {"task_prompt": "persist"},
                    },
                    {
                        "client_id": "n-context",
                        "node_type": FLOWCHART_NODE_TYPE_MEMORY,
                        "x": 120,
                        "y": -40,
                    },
                ],
                "edges": [
                    {
                        "source_node_id": start_node_id,
                        "target_node_id": "n-task",
                        "edge_mode": "solid",
                    },
                    {
                        "source_node_id": start_node_id,
                        "target_node_id": "n-context",
                        "edge_mode": "solid",
                    },
                    {
                        "source_node_id": "n-context",
                        "target_node_id": "n-task",
                        "edge_mode": "dotted",
                        "source_handle_id": "r1",
                        "target_handle_id": "l1",
                        "label": "pull context",
                    }
                ],
            },
        )
        self.assertEqual(200, save_response.status_code)
        payload = save_response.get_json() or {}
        self.assertTrue((payload.get("validation") or {}).get("valid"))

        load_response = self.client.get(f"/flowcharts/{flowchart_id}/graph")
        self.assertEqual(200, load_response.status_code)
        loaded = load_response.get_json() or {}
        dotted_edges = [
            edge
            for edge in (loaded.get("edges") or [])
            if edge.get("edge_mode") == "dotted"
        ]
        self.assertEqual(1, len(dotted_edges))
        self.assertEqual("r1", dotted_edges[0].get("source_handle_id"))
        self.assertEqual("l1", dotted_edges[0].get("target_handle_id"))
        self.assertEqual("pull context", dotted_edges[0].get("label"))


if __name__ == "__main__":
    unittest.main()

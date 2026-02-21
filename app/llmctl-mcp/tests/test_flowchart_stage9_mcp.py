from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from unittest.mock import patch

import psycopg
REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
MCP_SRC = REPO_ROOT / "app" / "llmctl-mcp" / "src"
for path in (str(STUDIO_SRC), str(MCP_SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

os.environ.setdefault(
    "LLMCTL_STUDIO_DATABASE_URI",
    "postgresql+psycopg://llmctl:llmctl@127.0.0.1:15432/llmctl_studio",
)

import core.db as core_db
from core.config import Config
from core.db import session_scope
from sqlalchemy import select
from core.models import (
    FLOWCHART_NODE_TYPE_DECISION,
    FLOWCHART_NODE_TYPE_MEMORY,
    FLOWCHART_NODE_TYPE_MILESTONE,
    FLOWCHART_NODE_TYPE_PLAN,
    FLOWCHART_NODE_TYPE_START,
    FLOWCHART_NODE_TYPE_TASK,
    Flowchart,
    FlowchartNode,
    FlowchartRun,
    FlowchartRunNode,
    LLMModel,
    MCPServer,
    Memory,
    Milestone,
    NodeArtifact,
    NODE_ARTIFACT_TYPE_DECISION,
    NODE_ARTIFACT_TYPE_MEMORY,
    NODE_ARTIFACT_TYPE_MILESTONE,
    NODE_ARTIFACT_TYPE_PLAN,
    Plan,
    PlanStage,
    PlanTask,
    SCRIPT_TYPE_INIT,
    Script,
    flowchart_node_scripts,
)
import tools as mcp_tools


class _DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator


class FlowchartStage9McpToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._base_db_uri = os.environ["LLMCTL_STUDIO_DATABASE_URI"]
        self._schema_name = f"mcp_stage9_{uuid.uuid4().hex}"
        self._orig_db_uri = Config.SQLALCHEMY_DATABASE_URI
        self._create_schema(self._schema_name)
        Config.SQLALCHEMY_DATABASE_URI = self._with_search_path(
            self._base_db_uri,
            self._schema_name,
        )
        self._dispose_engine()
        core_db.init_engine(Config.SQLALCHEMY_DATABASE_URI)
        core_db.init_db()

        self.mcp = _DummyMCP()
        mcp_tools.register(self.mcp)

    def tearDown(self) -> None:
        self._dispose_engine()
        self._drop_schema(self._schema_name)
        Config.SQLALCHEMY_DATABASE_URI = self._orig_db_uri
        self._tmp.cleanup()

    def _dispose_engine(self) -> None:
        if core_db._engine is not None:
            core_db._engine.dispose()
        core_db._engine = None
        core_db.SessionLocal = None

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

    def test_flowchart_and_node_mcp_tools_coverage(self) -> None:
        with session_scope() as session:
            model = LLMModel.create(
                session,
                name="mcp-model",
                provider="codex",
                config_json="{}",
            )
            mcp_server = MCPServer.create(
                session,
                name="mcp-server",
                server_key="mcp-server",
                config_json='{"command":"echo"}',
            )
            script_a = Script.create(
                session,
                file_name="a.sh",
                content="#!/bin/sh\necho a\n",
                script_type=SCRIPT_TYPE_INIT,
            )
            script_b = Script.create(
                session,
                file_name="b.sh",
                content="#!/bin/sh\necho b\n",
                script_type=SCRIPT_TYPE_INIT,
            )
            model_id = model.id
            mcp_server_id = mcp_server.id
            script_a_id = script_a.id
            script_b_id = script_b.id

        create_flowchart = self.mcp.tools["llmctl_create_flowchart"]
        update_graph = self.mcp.tools["llmctl_update_flowchart_graph"]
        get_flowchart = self.mcp.tools["llmctl_get_flowchart"]
        get_graph = self.mcp.tools["llmctl_get_flowchart_graph"]
        set_model = self.mcp.tools["llmctl_set_flowchart_node_model"]
        bind_mcp = self.mcp.tools["llmctl_bind_flowchart_node_mcp"]
        bind_script = self.mcp.tools["llmctl_bind_flowchart_node_script"]
        reorder_scripts = self.mcp.tools["llmctl_reorder_flowchart_node_scripts"]
        create_skill = self.mcp.tools["llmctl_create_skill"]
        get_skill = self.mcp.tools["llmctl_get_skill"]
        update_skill = self.mcp.tools["llmctl_update_skill"]
        archive_skill = self.mcp.tools["llmctl_archive_skill"]
        start_flowchart = self.mcp.tools["start_flowchart"]
        get_run = self.mcp.tools["llmctl_get_flowchart_run"]
        cancel_run = self.mcp.tools["cancel_flowchart_run"]

        created = create_flowchart(name="MCP Stage 9")
        self.assertTrue(created["ok"])
        flowchart_id = int(created["item"]["id"])

        updated = update_graph(
            flowchart_id=flowchart_id,
            nodes=[
                {
                    "client_id": "start",
                    "node_type": FLOWCHART_NODE_TYPE_START,
                    "x": 0,
                    "y": 0,
                },
                {
                    "client_id": "task",
                    "node_type": FLOWCHART_NODE_TYPE_TASK,
                    "config": {"task_prompt": "hello"},
                    "x": 100,
                    "y": 0,
                },
            ],
            edges=[
                {
                    "source_node_id": "start",
                    "target_node_id": "task",
                    "source_handle_id": "r1",
                    "target_handle_id": "l1",
                    "label": "start to task",
                }
            ],
        )
        self.assertTrue(updated["ok"])
        self.assertTrue(updated["validation"]["valid"])

        graph = get_graph(flowchart_id=flowchart_id)
        self.assertTrue(graph["ok"])
        self.assertTrue(graph["validation"]["valid"])
        self.assertEqual(2, len(graph["nodes"]))
        self.assertEqual(1, len(graph["edges"]))
        edge = graph["edges"][0]
        self.assertEqual("r1", edge.get("source_handle_id"))
        self.assertEqual("l1", edge.get("target_handle_id"))
        self.assertEqual("start to task", edge.get("label"))
        task_node_id = next(
            int(node["id"]) for node in graph["nodes"] if node["node_type"] == FLOWCHART_NODE_TYPE_TASK
        )

        self.assertTrue(
            set_model(flowchart_id=flowchart_id, node_id=task_node_id, model_id=model_id)["ok"]
        )
        self.assertTrue(
            bind_mcp(
                flowchart_id=flowchart_id,
                node_id=task_node_id,
                mcp_server_id=mcp_server_id,
            )["ok"]
        )
        self.assertTrue(
            bind_script(
                flowchart_id=flowchart_id,
                node_id=task_node_id,
                script_id=script_a_id,
            )["ok"]
        )
        self.assertTrue(
            bind_script(
                flowchart_id=flowchart_id,
                node_id=task_node_id,
                script_id=script_b_id,
            )["ok"]
        )
        reordered = reorder_scripts(
            flowchart_id=flowchart_id,
            node_id=task_node_id,
            script_ids=[script_b_id, script_a_id],
        )
        self.assertTrue(reordered["ok"])
        self.assertEqual({script_a_id, script_b_id}, set(reordered["node"]["script_ids"]))
        with session_scope() as session:
            ordered_script_ids = [
                int(row[0])
                for row in session.execute(
                    select(flowchart_node_scripts.c.script_id)
                    .where(flowchart_node_scripts.c.flowchart_node_id == task_node_id)
                    .order_by(flowchart_node_scripts.c.position.asc())
                ).all()
            ]
        self.assertEqual([script_b_id, script_a_id], ordered_script_ids)

        created_skill_a = create_skill(
            name="mcp-skill-a",
            display_name="MCP Skill A",
            description="MCP skill A",
            version="1.0.0",
            status="active",
        )
        self.assertTrue(created_skill_a["ok"])
        skill_a_id = int(created_skill_a["skill_id"])
        created_skill_b = create_skill(
            name="mcp-skill-b",
            display_name="MCP Skill B",
            description="MCP skill B",
            version="1.0.0",
            status="active",
        )
        self.assertTrue(created_skill_b["ok"])
        skill_b_id = int(created_skill_b["skill_id"])

        fetched_skill = get_skill(skill_id=skill_a_id, include_versions=True)
        self.assertTrue(fetched_skill["ok"])
        self.assertTrue(fetched_skill.get("versions"))
        updated_skill = update_skill(
            skill_id=skill_a_id,
            patch={
                "display_name": "MCP Skill A Updated",
                "description": "Updated",
                "status": "active",
            },
        )
        self.assertTrue(updated_skill["ok"])
        self.assertEqual("MCP Skill A Updated", updated_skill["item"]["display_name"])

        archived = archive_skill(skill_id=skill_b_id)
        self.assertTrue(archived["ok"])
        self.assertEqual("archived", archived["item"]["status"])

        fetched = get_flowchart(
            flowchart_id=flowchart_id,
            include_graph=True,
            include_validation=True,
        )
        self.assertTrue(fetched["ok"])
        self.assertTrue(fetched["validation"]["valid"])
        task_node = next(
            node for node in fetched["nodes"] if node["node_type"] == FLOWCHART_NODE_TYPE_TASK
        )
        self.assertEqual(model_id, task_node["model_id"])
        self.assertIn(mcp_server_id, task_node["mcp_server_ids"])
        self.assertEqual({script_a_id, script_b_id}, set(task_node["script_ids"]))

        with patch.object(
            mcp_tools.run_flowchart, "delay", return_value=SimpleNamespace(id="flow-job")
        ):
            started = start_flowchart(flowchart_id=flowchart_id)
        self.assertTrue(started["ok"])
        run_id = int(started["flowchart_run"]["id"])
        self.assertEqual("queued", started["flowchart_run"]["status"])

        run_before_cancel = get_run(run_id=run_id, include_node_runs=True)
        self.assertTrue(run_before_cancel["ok"])
        self.assertEqual("queued", run_before_cancel["flowchart_run"]["status"])

        with patch.object(mcp_tools.celery_app.control, "revoke", return_value=None):
            canceled = cancel_run(run_id=run_id)
        self.assertTrue(canceled["ok"])
        self.assertTrue(canceled["canceled"])
        self.assertEqual("canceled", canceled["flowchart_run"]["status"])

        run_after_cancel = get_run(run_id=run_id, include_node_runs=True)
        self.assertTrue(run_after_cancel["ok"])
        self.assertEqual("canceled", run_after_cancel["flowchart_run"]["status"])

        inline_created = create_flowchart(name="MCP Inline Task")
        self.assertTrue(inline_created["ok"])
        inline_flowchart_id = int(inline_created["item"]["id"])
        inline_updated = update_graph(
            flowchart_id=inline_flowchart_id,
            nodes=[
                {
                    "client_id": "start-inline",
                    "node_type": FLOWCHART_NODE_TYPE_START,
                    "x": 0,
                    "y": 0,
                },
                {
                    "client_id": "task-inline",
                    "node_type": FLOWCHART_NODE_TYPE_TASK,
                    "x": 120,
                    "y": 0,
                    "config": {"task_prompt": "Run inline task"},
                },
            ],
            edges=[{"source_node_id": "start-inline", "target_node_id": "task-inline"}],
        )
        self.assertTrue(inline_updated["ok"])
        self.assertTrue(inline_updated["validation"]["valid"])

    def test_update_flowchart_graph_allows_any_edge_handle_direction(self) -> None:
        create_flowchart = self.mcp.tools["llmctl_create_flowchart"]
        update_graph = self.mcp.tools["llmctl_update_flowchart_graph"]

        created = create_flowchart(name="MCP Invalid Handles")
        self.assertTrue(created["ok"])
        flowchart_id = int(created["item"]["id"])

        updated = update_graph(
            flowchart_id=flowchart_id,
            nodes=[
                {
                    "client_id": "start",
                    "node_type": FLOWCHART_NODE_TYPE_START,
                    "x": 0,
                    "y": 0,
                },
                {
                    "client_id": "task",
                    "node_type": FLOWCHART_NODE_TYPE_TASK,
                    "x": 120,
                    "y": 0,
                    "config": {"task_prompt": "Run inline task"},
                },
            ],
            edges=[
                {
                    "source_node_id": "start",
                    "target_node_id": "task",
                    "source_handle_id": "l1",
                    "target_handle_id": "r1",
                }
            ],
        )
        self.assertTrue(updated["ok"])
        self.assertTrue(updated["validation"]["valid"])
        edges = updated.get("edges") or []
        self.assertEqual(1, len(edges))
        self.assertEqual("l1", edges[0].get("source_handle_id"))
        self.assertEqual("r1", edges[0].get("target_handle_id"))

    def test_update_flowchart_graph_rejects_multiple_outputs_for_non_decision_nodes(
        self,
    ) -> None:
        create_flowchart = self.mcp.tools["llmctl_create_flowchart"]
        update_graph = self.mcp.tools["llmctl_update_flowchart_graph"]

        created = create_flowchart(name="MCP Output Limit")
        self.assertTrue(created["ok"])
        flowchart_id = int(created["item"]["id"])

        updated = update_graph(
            flowchart_id=flowchart_id,
            nodes=[
                {
                    "client_id": "start",
                    "node_type": FLOWCHART_NODE_TYPE_START,
                    "x": 0,
                    "y": 0,
                },
                {
                    "client_id": "task-a",
                    "node_type": FLOWCHART_NODE_TYPE_TASK,
                    "x": 120,
                    "y": -40,
                    "config": {"task_prompt": "A"},
                },
                {
                    "client_id": "task-b",
                    "node_type": FLOWCHART_NODE_TYPE_TASK,
                    "x": 120,
                    "y": 40,
                    "config": {"task_prompt": "B"},
                },
            ],
            edges=[
                {"source_node_id": "start", "target_node_id": "task-a"},
                {"source_node_id": "start", "target_node_id": "task-b"},
            ],
        )
        self.assertFalse(updated["ok"])
        errors = ((updated.get("validation") or {}).get("errors")) or []
        self.assertTrue(
            any("supports at most 1 outgoing edge" in str(error) for error in errors)
        )

    def test_update_flowchart_graph_rejects_more_than_three_decision_outputs(self) -> None:
        create_flowchart = self.mcp.tools["llmctl_create_flowchart"]
        update_graph = self.mcp.tools["llmctl_update_flowchart_graph"]

        created = create_flowchart(name="MCP Decision Output Limit")
        self.assertTrue(created["ok"])
        flowchart_id = int(created["item"]["id"])

        updated = update_graph(
            flowchart_id=flowchart_id,
            nodes=[
                {
                    "client_id": "start",
                    "node_type": FLOWCHART_NODE_TYPE_START,
                    "x": 0,
                    "y": 0,
                },
                {
                    "client_id": "decision",
                    "node_type": FLOWCHART_NODE_TYPE_DECISION,
                    "x": 120,
                    "y": 0,
                },
                {
                    "client_id": "task-1",
                    "node_type": FLOWCHART_NODE_TYPE_TASK,
                    "x": 260,
                    "y": -120,
                    "config": {"task_prompt": "1"},
                },
                {
                    "client_id": "task-2",
                    "node_type": FLOWCHART_NODE_TYPE_TASK,
                    "x": 260,
                    "y": -40,
                    "config": {"task_prompt": "2"},
                },
                {
                    "client_id": "task-3",
                    "node_type": FLOWCHART_NODE_TYPE_TASK,
                    "x": 260,
                    "y": 40,
                    "config": {"task_prompt": "3"},
                },
                {
                    "client_id": "task-4",
                    "node_type": FLOWCHART_NODE_TYPE_TASK,
                    "x": 260,
                    "y": 120,
                    "config": {"task_prompt": "4"},
                },
            ],
            edges=[
                {"source_node_id": "start", "target_node_id": "decision"},
                {
                    "source_node_id": "decision",
                    "target_node_id": "task-1",
                    "condition_key": "route_1",
                },
                {
                    "source_node_id": "decision",
                    "target_node_id": "task-2",
                    "condition_key": "route_2",
                },
                {
                    "source_node_id": "decision",
                    "target_node_id": "task-3",
                    "condition_key": "route_3",
                },
                {
                    "source_node_id": "decision",
                    "target_node_id": "task-4",
                    "condition_key": "route_4",
                },
            ],
        )
        self.assertFalse(updated["ok"])
        errors = ((updated.get("validation") or {}).get("errors")) or []
        self.assertTrue(
            any("supports at most 3 outgoing edges" in str(error) for error in errors)
        )

    def test_mcp_milestone_artifact_history_is_exposed_across_run_and_milestone_reads(self) -> None:
        with session_scope() as session:
            milestone = Milestone.create(session, name="Artifact Milestone")
            flowchart = Flowchart.create(session, name="Artifact Flowchart")
            start_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                title="Start",
                x=0,
                y=0,
                config_json=json.dumps({}, sort_keys=True),
            )
            milestone_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MILESTONE,
                title="Milestone",
                ref_id=milestone.id,
                x=120,
                y=0,
                config_json=json.dumps({"action": "mark_complete"}, sort_keys=True),
            )
            run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="completed",
            )
            FlowchartRunNode.create(
                session,
                flowchart_run_id=run.id,
                flowchart_node_id=start_node.id,
                execution_index=1,
                status="succeeded",
                output_state_json=json.dumps({"node_type": FLOWCHART_NODE_TYPE_START}),
            )
            milestone_run_node = FlowchartRunNode.create(
                session,
                flowchart_run_id=run.id,
                flowchart_node_id=milestone_node.id,
                execution_index=1,
                status="succeeded",
                output_state_json=json.dumps(
                    {
                        "node_type": FLOWCHART_NODE_TYPE_MILESTONE,
                        "action": "mark_complete",
                        "milestone": {
                            "id": milestone.id,
                            "status": "done",
                            "completed": True,
                        },
                    },
                    sort_keys=True,
                ),
            )
            NodeArtifact.create(
                session,
                flowchart_id=flowchart.id,
                flowchart_node_id=milestone_node.id,
                flowchart_run_id=run.id,
                flowchart_run_node_id=milestone_run_node.id,
                node_type=FLOWCHART_NODE_TYPE_MILESTONE,
                artifact_type=NODE_ARTIFACT_TYPE_MILESTONE,
                ref_id=milestone.id,
                execution_index=1,
                variant_key=f"run-{run.id}-node-run-{milestone_run_node.id}",
                retention_mode="ttl",
                payload_json=json.dumps(
                    {
                        "action": "mark_complete",
                        "milestone": {"id": milestone.id, "status": "done"},
                    },
                    sort_keys=True,
                ),
            )
            run_id = run.id
            milestone_id = milestone.id
            milestone_node_run_id = milestone_run_node.id

        get_run = self.mcp.tools["llmctl_get_flowchart_run"]
        get_node_artifact = self.mcp.tools["llmctl_get_node_artifact"]
        get_milestone = self.mcp.tools["llmctl_get_milestone"]

        run_payload = get_run(run_id=run_id, include_node_runs=True)
        self.assertTrue(run_payload["ok"])
        milestone_node_run_payload = next(
            node_run
            for node_run in (run_payload.get("node_runs") or [])
            if int(node_run.get("id") or 0) == milestone_node_run_id
        )
        artifact_history = milestone_node_run_payload.get("artifact_history") or []
        self.assertEqual(1, len(artifact_history))
        self.assertEqual("milestone", artifact_history[0].get("artifact_type"))
        self.assertEqual(
            "mark_complete",
            (artifact_history[0].get("payload") or {}).get("action"),
        )

        artifacts_payload = get_node_artifact(
            flowchart_run_id=run_id,
            artifact_type="milestone",
        )
        self.assertTrue(artifacts_payload["ok"])
        self.assertEqual(1, artifacts_payload.get("count"))

        milestone_payload = get_milestone(
            milestone_id=milestone_id,
            include_artifacts=True,
        )
        self.assertTrue(milestone_payload["ok"])
        milestone_history = milestone_payload.get("artifact_history") or []
        self.assertEqual(1, len(milestone_history))
        self.assertEqual("milestone", milestone_history[0].get("artifact_type"))

    def test_mcp_plan_artifacts_are_queryable(self) -> None:
        with session_scope() as session:
            plan = Plan.create(session, name="Artifact Plan")
            stage = PlanStage.create(
                session,
                plan_id=plan.id,
                name="Stage MCP",
                position=1,
            )
            task = PlanTask.create(
                session,
                plan_stage_id=stage.id,
                name="Task MCP",
                position=1,
            )
            flowchart = Flowchart.create(session, name="Plan Artifact Flowchart")
            plan_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_PLAN,
                title="Plan",
                ref_id=plan.id,
                x=120,
                y=0,
                config_json=json.dumps({"action": "complete_plan_item"}, sort_keys=True),
            )
            run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="completed",
            )
            plan_run_node = FlowchartRunNode.create(
                session,
                flowchart_run_id=run.id,
                flowchart_node_id=plan_node.id,
                execution_index=1,
                status="succeeded",
                output_state_json=json.dumps(
                    {
                        "node_type": FLOWCHART_NODE_TYPE_PLAN,
                        "action": "complete_plan_item",
                        "completion_target": {"plan_item_id": task.id},
                    },
                    sort_keys=True,
                ),
            )
            NodeArtifact.create(
                session,
                flowchart_id=flowchart.id,
                flowchart_node_id=plan_node.id,
                flowchart_run_id=run.id,
                flowchart_run_node_id=plan_run_node.id,
                node_type=FLOWCHART_NODE_TYPE_PLAN,
                artifact_type=NODE_ARTIFACT_TYPE_PLAN,
                ref_id=plan.id,
                execution_index=1,
                variant_key=f"run-{run.id}-node-run-{plan_run_node.id}",
                retention_mode="ttl",
                payload_json=json.dumps(
                    {
                        "action": "complete_plan_item",
                        "completion_target": {"plan_item_id": task.id},
                        "touched": {"stage_ids": [stage.id], "task_ids": [task.id]},
                    },
                    sort_keys=True,
                ),
            )
            run_id = run.id
            plan_id = plan.id
            task_id = task.id

        get_node_artifact = self.mcp.tools["llmctl_get_node_artifact"]
        artifacts_payload = get_node_artifact(
            flowchart_run_id=run_id,
            artifact_type="plan",
            ref_id=plan_id,
        )
        self.assertTrue(artifacts_payload["ok"])
        self.assertEqual(1, artifacts_payload.get("count"))
        item = (artifacts_payload.get("items") or [])[0]
        self.assertEqual(NODE_ARTIFACT_TYPE_PLAN, item.get("artifact_type"))
        self.assertEqual(task_id, ((item.get("payload") or {}).get("completion_target") or {}).get("plan_item_id"))
        self.assertEqual([task_id], ((item.get("payload") or {}).get("touched") or {}).get("task_ids"))

    def test_mcp_memory_artifacts_are_queryable(self) -> None:
        with session_scope() as session:
            memory = Memory.create(session, description="artifact memory")
            flowchart = Flowchart.create(session, name="Memory Artifact Flowchart")
            memory_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                title="Memory",
                ref_id=memory.id,
                x=120,
                y=0,
                config_json=json.dumps({"action": "add"}, sort_keys=True),
            )
            run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="completed",
            )
            memory_run_node = FlowchartRunNode.create(
                session,
                flowchart_run_id=run.id,
                flowchart_node_id=memory_node.id,
                execution_index=1,
                status="succeeded",
                output_state_json=json.dumps(
                    {
                        "node_type": FLOWCHART_NODE_TYPE_MEMORY,
                        "action": "add",
                    },
                    sort_keys=True,
                ),
            )
            NodeArtifact.create(
                session,
                flowchart_id=flowchart.id,
                flowchart_node_id=memory_node.id,
                flowchart_run_id=run.id,
                flowchart_run_node_id=memory_run_node.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                artifact_type=NODE_ARTIFACT_TYPE_MEMORY,
                ref_id=memory.id,
                execution_index=1,
                variant_key=f"run-{run.id}-node-run-{memory_run_node.id}",
                retention_mode="ttl",
                payload_json=json.dumps(
                    {
                        "action": "add",
                        "effective_prompt": "artifact memory",
                    },
                    sort_keys=True,
                ),
            )
            run_id = run.id
            memory_id = memory.id

        get_memory = self.mcp.tools["llmctl_get_memory"]
        get_node_artifact = self.mcp.tools["llmctl_get_node_artifact"]
        memory_payload = get_memory(memory_id=memory_id, include_artifacts=True)
        self.assertTrue(memory_payload["ok"])
        artifact_history = memory_payload.get("artifact_history") or []
        self.assertEqual(1, len(artifact_history))
        self.assertEqual("memory", artifact_history[0].get("artifact_type"))
        self.assertEqual("add", (artifact_history[0].get("payload") or {}).get("action"))

        artifacts_payload = get_node_artifact(
            flowchart_run_id=run_id,
            artifact_type="memory",
            ref_id=memory_id,
        )
        self.assertTrue(artifacts_payload["ok"])
        self.assertEqual(1, artifacts_payload.get("count"))

    def test_mcp_decision_artifacts_are_queryable(self) -> None:
        with session_scope() as session:
            flowchart = Flowchart.create(session, name="Decision Artifact Flowchart")
            decision_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_DECISION,
                title="Decision",
                x=120,
                y=0,
            )
            run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="completed",
            )
            decision_run_node = FlowchartRunNode.create(
                session,
                flowchart_run_id=run.id,
                flowchart_node_id=decision_node.id,
                execution_index=1,
                status="succeeded",
                output_state_json=json.dumps(
                    {
                        "node_type": FLOWCHART_NODE_TYPE_DECISION,
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
            artifact = NodeArtifact.create(
                session,
                flowchart_id=flowchart.id,
                flowchart_node_id=decision_node.id,
                flowchart_run_id=run.id,
                flowchart_run_node_id=decision_run_node.id,
                node_type=FLOWCHART_NODE_TYPE_DECISION,
                artifact_type=NODE_ARTIFACT_TYPE_DECISION,
                ref_id=None,
                execution_index=1,
                variant_key=f"run-{run.id}-node-run-{decision_run_node.id}",
                retention_mode="ttl",
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

        get_decision_artifact = self.mcp.tools["llmctl_get_decision_artifact"]
        list_payload = get_decision_artifact(
            flowchart_id=flowchart_id,
            flowchart_node_id=flowchart_node_id,
            flowchart_run_id=flowchart_run_id,
        )
        self.assertTrue(list_payload["ok"])
        self.assertEqual(1, list_payload.get("count"))
        item = (list_payload.get("items") or [])[0]
        self.assertEqual(NODE_ARTIFACT_TYPE_DECISION, item.get("artifact_type"))
        self.assertEqual(
            ["approve_connector"],
            (item.get("payload") or {}).get("matched_connector_ids") or [],
        )
        self.assertFalse((item.get("payload") or {}).get("no_match"))

        detail_payload = get_decision_artifact(artifact_id=artifact_id)
        self.assertTrue(detail_payload["ok"])
        detail_item = detail_payload.get("item") or {}
        self.assertEqual(artifact_id, detail_item.get("id"))
        self.assertEqual(
            ["approve_connector"],
            (detail_item.get("payload") or {}).get("matched_connector_ids") or [],
        )

    def test_decision_tool_coverage_includes_core_operations(self) -> None:
        with session_scope() as session:
            flowchart = Flowchart.create(session, name="Decision Coverage Flowchart")
            decision_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_DECISION,
                title="Decision Coverage Node",
                x=120,
                y=0,
                config_json=json.dumps(
                    {
                        "decision_conditions": [
                            {
                                "connector_id": "approve_connector",
                                "condition_text": "risk_score < 0.5",
                                "label": "Approve",
                            },
                            {
                                "connector_id": "reject_connector",
                                "condition_text": "risk_score >= 0.5",
                                "label": "Reject",
                            },
                        ]
                    },
                    sort_keys=True,
                ),
            )
            run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="completed",
            )
            run_node = FlowchartRunNode.create(
                session,
                flowchart_run_id=run.id,
                flowchart_node_id=decision_node.id,
                execution_index=1,
                status="succeeded",
                output_state_json=json.dumps(
                    {
                        "node_type": FLOWCHART_NODE_TYPE_DECISION,
                        "matched_connector_ids": [],
                        "evaluations": [],
                        "no_match": True,
                    },
                    sort_keys=True,
                ),
            )
            flowchart_id = flowchart.id
            flowchart_node_id = decision_node.id
            flowchart_run_id = run.id
            flowchart_run_node_id = run_node.id

        list_options = self.mcp.tools["llmctl_list_decision_options"]
        score_options = self.mcp.tools["llmctl_score_decision_options"]
        evaluate_decision = self.mcp.tools["llmctl_evaluate_decision"]
        create_decision = self.mcp.tools["llmctl_create_decision"]
        record_outcome = self.mcp.tools["llmctl_record_decision_outcome"]
        get_decision = self.mcp.tools["llmctl_get_decision"]

        listed_options = list_options(
            flowchart_id=flowchart_id,
            flowchart_node_id=flowchart_node_id,
        )
        self.assertTrue(listed_options["ok"])
        self.assertEqual(2, listed_options.get("count"))
        self.assertEqual(
            {"approve_connector", "reject_connector"},
            {
                str(item.get("option_id") or "")
                for item in (listed_options.get("options") or [])
            },
        )

        scored_options = score_options(
            options=listed_options.get("options") or [],
            matched_option_ids=["approve_connector"],
        )
        self.assertTrue(scored_options["ok"])
        self.assertEqual(2, scored_options.get("count"))
        self.assertEqual("approve_connector", (scored_options.get("scores") or [])[0].get("option_id"))

        evaluated = evaluate_decision(
            option_scores=scored_options.get("scores") or [],
            min_score=0.5,
        )
        self.assertTrue(evaluated["ok"])
        evaluated_routing_state = evaluated.get("routing_state") or {}
        self.assertEqual("approve_connector", evaluated_routing_state.get("route_key"))
        self.assertFalse(bool(evaluated_routing_state.get("no_match")))

        created_decision = create_decision(
            flowchart_id=flowchart_id,
            flowchart_node_id=flowchart_node_id,
            flowchart_run_id=flowchart_run_id,
            flowchart_run_node_id=flowchart_run_node_id,
            matched_connector_ids=evaluated_routing_state.get("matched_connector_ids") or [],
            evaluations=evaluated_routing_state.get("evaluations") or [],
            route_key=evaluated_routing_state.get("route_key"),
            no_match=evaluated_routing_state.get("no_match"),
            options=listed_options.get("options") or [],
            option_scores=scored_options.get("scores") or [],
        )
        self.assertTrue(created_decision["ok"])
        decision_id = int((created_decision.get("item") or {}).get("id") or 0)
        self.assertGreater(decision_id, 0)

        recorded = record_outcome(
            decision_id=decision_id,
            outcome="approved",
            selected_option_id="approve_connector",
            notes="Recorded by stage9 MCP coverage test",
        )
        self.assertTrue(recorded["ok"])
        recorded_payload = (recorded.get("item") or {}).get("payload") or {}
        self.assertEqual("approved", recorded_payload.get("outcome"))
        self.assertEqual("approve_connector", recorded_payload.get("selected_option_id"))

        detail = get_decision(decision_id=decision_id)
        self.assertTrue(detail["ok"])
        self.assertEqual(decision_id, int((detail.get("item") or {}).get("id") or 0))

        listed = get_decision(flowchart_run_id=flowchart_run_id)
        self.assertTrue(listed["ok"])
        listed_ids = {int(item.get("id") or 0) for item in (listed.get("items") or [])}
        self.assertIn(decision_id, listed_ids)

    def test_memory_tool_coverage_includes_crud_and_search(self) -> None:
        create_memory = self.mcp.tools["llmctl_create_memory"]
        get_memory = self.mcp.tools["llmctl_get_memory"]
        update_memory = self.mcp.tools["llmctl_update_memory"]
        delete_memory = self.mcp.tools["llmctl_delete_memory"]
        search_memory = self.mcp.tools["llmctl_search_memory"]

        first = create_memory(description="Alpha memory item")
        second = create_memory(description="Beta memory note")
        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])
        first_id = int((first.get("item") or {}).get("id") or 0)
        second_id = int((second.get("item") or {}).get("id") or 0)
        self.assertGreater(first_id, 0)
        self.assertGreater(second_id, 0)

        listed = get_memory(limit=20, include_artifacts=False)
        self.assertTrue(listed["ok"])
        listed_ids = {int(item.get("id") or 0) for item in (listed.get("items") or [])}
        self.assertIn(first_id, listed_ids)
        self.assertIn(second_id, listed_ids)

        found = search_memory(query="alpha")
        self.assertTrue(found["ok"])
        found_ids = {int(item.get("id") or 0) for item in (found.get("items") or [])}
        self.assertIn(first_id, found_ids)
        self.assertNotIn(second_id, found_ids)

        updated = update_memory(memory_id=first_id, description="Alpha memory item updated")
        self.assertTrue(updated["ok"])
        detail = get_memory(memory_id=first_id, include_artifacts=False)
        self.assertTrue(detail["ok"])
        self.assertEqual("Alpha memory item updated", (detail.get("item") or {}).get("description"))

        deleted = delete_memory(memory_id=second_id)
        self.assertTrue(deleted["ok"])
        missing = get_memory(memory_id=second_id, include_artifacts=False)
        self.assertFalse(missing["ok"])

    def test_plan_tool_coverage_includes_reorder_and_stage_status(self) -> None:
        create_plan = self.mcp.tools["llmctl_create_plan"]
        get_plan = self.mcp.tools["llmctl_get_plan"]
        update_plan = self.mcp.tools["llmctl_update_plan"]
        delete_plan = self.mcp.tools["llmctl_delete_plan"]
        create_stage = self.mcp.tools["llmctl_create_plan_stage"]
        reorder_stages = self.mcp.tools["llmctl_reorder_plan_stages"]
        set_stage_status = self.mcp.tools["llmctl_set_plan_stage_status"]

        created = create_plan(name="Coverage Plan", description="Initial")
        self.assertTrue(created["ok"])
        plan_id = int((created.get("item") or {}).get("id") or 0)
        self.assertGreater(plan_id, 0)

        stage_a = create_stage(plan_id=plan_id, name="Stage A")
        stage_b = create_stage(plan_id=plan_id, name="Stage B")
        self.assertTrue(stage_a["ok"])
        self.assertTrue(stage_b["ok"])
        stage_a_id = int((stage_a.get("item") or {}).get("id") or 0)
        stage_b_id = int((stage_b.get("item") or {}).get("id") or 0)

        reordered = reorder_stages(plan_id=plan_id, stage_ids=[stage_b_id, stage_a_id])
        self.assertTrue(reordered["ok"])
        reordered_ids = [
            int(stage.get("id") or 0)
            for stage in ((reordered.get("item") or {}).get("stages") or [])
        ]
        self.assertEqual([stage_b_id, stage_a_id], reordered_ids)

        completed = set_stage_status(stage_id=stage_b_id, status="completed", plan_id=plan_id)
        self.assertTrue(completed["ok"])
        self.assertEqual("completed", ((completed.get("item") or {}).get("status")))
        self.assertTrue(bool((completed.get("item") or {}).get("completed_at")))

        in_progress = set_stage_status(stage_id=stage_b_id, status="in_progress", plan_id=plan_id)
        self.assertTrue(in_progress["ok"])
        self.assertEqual("in_progress", ((in_progress.get("item") or {}).get("status")))
        self.assertIsNone((in_progress.get("item") or {}).get("completed_at"))

        updated = update_plan(plan_id=plan_id, patch={"description": "Updated description"})
        self.assertTrue(updated["ok"])
        self.assertEqual("Updated description", ((updated.get("item") or {}).get("description")))

        listed = get_plan(limit=20, include_stages=True, include_tasks=True, include_artifacts=False)
        self.assertTrue(listed["ok"])
        listed_ids = {int(item.get("id") or 0) for item in (listed.get("items") or [])}
        self.assertIn(plan_id, listed_ids)

        detail = get_plan(plan_id=plan_id, include_stages=True, include_tasks=True, include_artifacts=False)
        self.assertTrue(detail["ok"])
        self.assertEqual(plan_id, int(((detail.get("item") or {}).get("id") or 0)))

        deleted = delete_plan(plan_id=plan_id)
        self.assertTrue(deleted["ok"])
        missing = get_plan(plan_id=plan_id, include_artifacts=False)
        self.assertFalse(missing["ok"])

    def test_milestone_tool_coverage_includes_set_status_and_attach_evidence(self) -> None:
        create_milestone = self.mcp.tools["llmctl_create_milestone"]
        get_milestone = self.mcp.tools["llmctl_get_milestone"]
        update_milestone = self.mcp.tools["llmctl_update_milestone"]
        delete_milestone = self.mcp.tools["llmctl_delete_milestone"]
        set_milestone_status = self.mcp.tools["llmctl_set_milestone_status"]
        attach_milestone_evidence = self.mcp.tools["llmctl_attach_milestone_evidence"]

        created = create_milestone(name="Coverage Milestone")
        self.assertTrue(created["ok"])
        milestone_id = int((created.get("item") or {}).get("id") or 0)
        self.assertGreater(milestone_id, 0)

        listed = get_milestone(limit=20, include_artifacts=False)
        self.assertTrue(listed["ok"])
        listed_ids = {int(item.get("id") or 0) for item in (listed.get("items") or [])}
        self.assertIn(milestone_id, listed_ids)

        updated = update_milestone(
            milestone_id=milestone_id,
            patch={"description": "Updated milestone description"},
        )
        self.assertTrue(updated["ok"])
        self.assertEqual(
            "Updated milestone description",
            ((updated.get("item") or {}).get("description")),
        )

        status_update = set_milestone_status(milestone_id=milestone_id, status="done")
        self.assertTrue(status_update["ok"])
        status_item = status_update.get("item") or {}
        self.assertEqual("done", status_item.get("status"))
        self.assertTrue(bool(status_item.get("completed")))

        evidence_update = attach_milestone_evidence(
            milestone_id=milestone_id,
            evidence="Verified in deterministic tooling coverage test.",
        )
        self.assertTrue(evidence_update["ok"])
        self.assertIn(
            "Verified in deterministic tooling coverage test.",
            str((evidence_update.get("item") or {}).get("latest_update") or ""),
        )

        detail = get_milestone(milestone_id=milestone_id, include_artifacts=False)
        self.assertTrue(detail["ok"])
        self.assertIn(
            "Verified in deterministic tooling coverage test.",
            str((detail.get("item") or {}).get("latest_update") or ""),
        )

        deleted = delete_milestone(milestone_id=milestone_id)
        self.assertTrue(deleted["ok"])
        missing = get_milestone(milestone_id=milestone_id, include_artifacts=False)
        self.assertFalse(missing["ok"])


if __name__ == "__main__":
    unittest.main()

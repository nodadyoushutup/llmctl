from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio" / "src"
MCP_SRC = REPO_ROOT / "app" / "llmctl-mcp" / "src"
for path in (str(STUDIO_SRC), str(MCP_SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

import core.db as core_db
from core.config import Config
from core.db import session_scope
from sqlalchemy import select
from core.models import (
    FLOWCHART_NODE_TYPE_DECISION,
    FLOWCHART_NODE_TYPE_START,
    FLOWCHART_NODE_TYPE_TASK,
    LLMModel,
    MCPServer,
    SCRIPT_TYPE_INIT,
    Script,
    TaskTemplate,
    flowchart_node_skills,
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
        tmp_dir = Path(self._tmp.name)
        self._orig_db_uri = Config.SQLALCHEMY_DATABASE_URI
        Config.SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_dir / 'stage9-mcp.sqlite3'}"
        self._dispose_engine()
        core_db.init_engine(Config.SQLALCHEMY_DATABASE_URI)
        core_db.init_db()

        self.mcp = _DummyMCP()
        mcp_tools.register(self.mcp)

    def tearDown(self) -> None:
        self._dispose_engine()
        Config.SQLALCHEMY_DATABASE_URI = self._orig_db_uri
        self._tmp.cleanup()

    def _dispose_engine(self) -> None:
        if core_db._engine is not None:
            core_db._engine.dispose()
        core_db._engine = None
        core_db.SessionLocal = None

    def test_flowchart_and_node_mcp_tools_coverage(self) -> None:
        with session_scope() as session:
            model = LLMModel.create(
                session,
                name="mcp-model",
                provider="codex",
                config_json="{}",
            )
            task_template = TaskTemplate.create(
                session,
                name="mcp-template",
                prompt="hello",
                model_id=model.id,
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
            template_id = task_template.id
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
        bind_skill = self.mcp.tools["llmctl_bind_flowchart_node_skill"]
        unbind_skill = self.mcp.tools["llmctl_unbind_flowchart_node_skill"]
        reorder_skills = self.mcp.tools["llmctl_reorder_flowchart_node_skills"]
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
                    "ref_id": template_id,
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

        self.assertTrue(
            bind_skill(
                flowchart_id=flowchart_id,
                node_id=task_node_id,
                skill_id=skill_a_id,
            )["ok"]
        )
        self.assertTrue(
            bind_skill(
                flowchart_id=flowchart_id,
                node_id=task_node_id,
                skill_id=skill_b_id,
            )["ok"]
        )
        reordered_skills = reorder_skills(
            flowchart_id=flowchart_id,
            node_id=task_node_id,
            skill_ids=[skill_b_id, skill_a_id],
        )
        self.assertTrue(reordered_skills["ok"])
        self.assertEqual({skill_a_id, skill_b_id}, set(reordered_skills["node"]["skill_ids"]))
        with session_scope() as session:
            ordered_skill_ids = [
                int(row[0])
                for row in session.execute(
                    select(flowchart_node_skills.c.skill_id)
                    .where(flowchart_node_skills.c.flowchart_node_id == task_node_id)
                    .order_by(flowchart_node_skills.c.position.asc())
                ).all()
            ]
        self.assertEqual([skill_b_id, skill_a_id], ordered_skill_ids)

        self.assertTrue(
            unbind_skill(
                flowchart_id=flowchart_id,
                node_id=task_node_id,
                skill_id=skill_b_id,
            )["ok"]
        )
        archived = archive_skill(skill_id=skill_b_id)
        self.assertTrue(archived["ok"])
        self.assertEqual("archived", archived["item"]["status"])
        archived_attach = bind_skill(
            flowchart_id=flowchart_id,
            node_id=task_node_id,
            skill_id=skill_b_id,
        )
        self.assertFalse(archived_attach["ok"])

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
        self.assertIn(skill_a_id, task_node["skill_ids"])
        self.assertNotIn(skill_b_id, task_node["skill_ids"])

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


if __name__ == "__main__":
    unittest.main()

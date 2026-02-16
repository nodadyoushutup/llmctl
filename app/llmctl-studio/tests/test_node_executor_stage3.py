from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import select

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

import core.db as core_db
from core.config import Config
from core.db import session_scope
from core.models import (
    AgentTask,
    FLOWCHART_NODE_TYPE_END,
    FLOWCHART_NODE_TYPE_START,
    Flowchart,
    FlowchartEdge,
    FlowchartNode,
    FlowchartRun,
    FlowchartRunNode,
)
from services.integrations import save_node_executor_settings
from services import tasks as studio_tasks
from services.execution.idempotency import clear_dispatch_registry


class NodeExecutorStage3Tests(unittest.TestCase):
    def setUp(self) -> None:
        clear_dispatch_registry()
        self._tmp = tempfile.TemporaryDirectory()
        self._tmp_path = Path(self._tmp.name)
        self._orig_db_uri = Config.SQLALCHEMY_DATABASE_URI
        Config.SQLALCHEMY_DATABASE_URI = (
            f"sqlite:///{self._tmp_path / 'node-executor-stage3.sqlite3'}"
        )
        self._dispose_engine()
        core_db.init_engine(Config.SQLALCHEMY_DATABASE_URI)
        core_db.init_db()

    def tearDown(self) -> None:
        self._dispose_engine()
        Config.SQLALCHEMY_DATABASE_URI = self._orig_db_uri
        self._tmp.cleanup()

    def _dispose_engine(self) -> None:
        if core_db._engine is not None:
            core_db._engine.dispose()
        core_db._engine = None
        core_db.SessionLocal = None

    def _create_simple_flowchart_run(self) -> tuple[int, int]:
        with session_scope() as session:
            flowchart = Flowchart.create(session, name="stage3-node-executor")
            start_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                title="Start",
                x=0.0,
                y=0.0,
            )
            end_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_END,
                title="End",
                x=400.0,
                y=0.0,
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=end_node.id,
            )
            run = FlowchartRun.create(session, flowchart_id=flowchart.id, status="queued")
            return int(flowchart.id), int(run.id)

    def _assert_run_metadata(self, run_id: int, *, expect_selected: str) -> None:
        with session_scope() as session:
            node_runs = session.execute(
                select(FlowchartRunNode).where(FlowchartRunNode.flowchart_run_id == run_id)
            ).scalars().all()
            tasks = session.execute(
                select(AgentTask).where(AgentTask.flowchart_run_id == run_id)
            ).scalars().all()

        self.assertEqual(2, len(node_runs))
        self.assertEqual(2, len(tasks))

        node_run_by_task_id = {
            int(node_run.agent_task_id): node_run
            for node_run in node_runs
            if node_run.agent_task_id is not None
        }
        self.assertEqual(2, len(node_run_by_task_id))

        for task in tasks:
            self.assertEqual(expect_selected, task.selected_provider)
            self.assertEqual("workspace", task.final_provider)
            self.assertEqual("dispatch_confirmed", task.dispatch_status)
            self.assertEqual("workspace-main", task.workspace_identity)
            self.assertEqual(expect_selected != "workspace", task.fallback_attempted)
            if expect_selected == "workspace":
                self.assertIsNone(task.fallback_reason)
            else:
                self.assertIn(
                    str(task.fallback_reason or ""),
                    {"provider_unavailable", "image_pull_failed", "dispatch_timeout", "create_failed"},
                )
            self.assertFalse(task.dispatch_uncertain)
            self.assertFalse(task.cli_fallback_used)
            self.assertIsNone(task.cli_preflight_passed)
            self.assertIsNone(task.api_failure_category)

            node_run = node_run_by_task_id.get(int(task.id))
            self.assertIsNotNone(node_run)
            self.assertEqual(
                f"workspace:workspace-{int(node_run.id)}",
                task.provider_dispatch_id,
            )

    def test_run_flowchart_persists_workspace_provider_metadata(self) -> None:
        save_node_executor_settings(
            {
                "provider": "workspace",
                "workspace_identity_key": "workspace-main",
            }
        )
        flowchart_id, run_id = self._create_simple_flowchart_run()
        studio_tasks.run_flowchart.run(flowchart_id, run_id)
        self._assert_run_metadata(run_id, expect_selected="workspace")

    def test_run_flowchart_falls_back_to_workspace_for_unimplemented_provider(self) -> None:
        save_node_executor_settings(
            {
                "provider": "docker",
                "workspace_identity_key": "workspace-main",
            }
        )
        flowchart_id, run_id = self._create_simple_flowchart_run()
        studio_tasks.run_flowchart.run(flowchart_id, run_id)
        self._assert_run_metadata(run_id, expect_selected="docker")

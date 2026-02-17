from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from flask import Flask

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

import core.db as core_db
from core.config import Config
from core.db import session_scope
from core.models import (
    Agent,
    AgentTask,
    FLOWCHART_NODE_TYPE_START,
    Flowchart,
    FlowchartNode,
    FlowchartRun,
    FlowchartRunNode,
    Run,
)
import web.views as studio_views


class StudioDbTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp_dir = Path(self._tmp.name)
        self._orig_db_uri = Config.SQLALCHEMY_DATABASE_URI
        self._orig_workspaces_dir = Config.WORKSPACES_DIR
        Config.SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_dir / 'stage8.sqlite3'}"
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


class NodeExecutorStage8ApiTests(StudioDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        template_dir = STUDIO_SRC / "web" / "templates"
        app = Flask("stage8-api-tests", template_folder=str(template_dir))
        app.config["TESTING"] = True
        app.secret_key = "stage8-tests"
        app.register_blueprint(studio_views.bp)
        self.client = app.test_client()

    def test_run_detail_api_includes_node_executor_metadata(self) -> None:
        with session_scope() as session:
            agent = Agent.create(
                session,
                name="Stage8 Agent",
                prompt_json="{}",
            )
            run = Run.create(
                session,
                name="Stage8 Autorun",
                agent_id=agent.id,
                status="running",
                task_id="run-task-1",
                last_run_task_id="run-task-1",
            )
            AgentTask.create(
                session,
                agent_id=agent.id,
                run_id=run.id,
                run_task_id="run-task-1",
                status="succeeded",
                selected_provider="kubernetes",
                final_provider="kubernetes",
                provider_dispatch_id="kubernetes:default/job-42",
                workspace_identity="workspace-main",
                dispatch_status="dispatch_confirmed",
                fallback_attempted=False,
                fallback_reason=None,
                dispatch_uncertain=False,
                api_failure_category=None,
                cli_fallback_used=False,
                cli_preflight_passed=None,
            )
            run_id = int(run.id)

        response = self.client.get(f"/runs/{run_id}?format=json")
        self.assertEqual(200, response.status_code)
        payload = response.get_json() or {}
        run_tasks = payload.get("run_tasks") or []
        self.assertEqual(1, len(run_tasks))
        run_task = run_tasks[0]
        self.assertEqual("kubernetes", run_task.get("selected_provider"))
        self.assertEqual("kubernetes", run_task.get("final_provider"))
        self.assertEqual("dispatch_confirmed", run_task.get("dispatch_status"))
        self.assertFalse(bool(run_task.get("fallback_attempted")))
        self.assertEqual("", run_task.get("fallback_reason"))
        self.assertIsNone(run_task.get("api_failure_category"))
        self.assertFalse(bool(run_task.get("cli_fallback_used")))
        self.assertEqual(
            "kubernetes:default/job-42",
            run_task.get("provider_dispatch_id"),
        )

    def test_flowchart_history_run_api_includes_node_executor_metadata(self) -> None:
        with session_scope() as session:
            agent = Agent.create(
                session,
                name="Stage8 Flowchart Agent",
                prompt_json="{}",
            )
            flowchart = Flowchart.create(session, name="Stage8 Flowchart")
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
            task = AgentTask.create(
                session,
                agent_id=agent.id,
                flowchart_id=flowchart.id,
                flowchart_run_id=flowchart_run.id,
                flowchart_node_id=start_node.id,
                status="succeeded",
                selected_provider="kubernetes",
                final_provider="kubernetes",
                provider_dispatch_id="kubernetes:default/job-1",
                workspace_identity="workspace-main",
                dispatch_status="dispatch_confirmed",
                fallback_attempted=False,
                fallback_reason=None,
                dispatch_uncertain=False,
                api_failure_category=None,
                cli_fallback_used=False,
                cli_preflight_passed=None,
            )
            FlowchartRunNode.create(
                session,
                flowchart_run_id=flowchart_run.id,
                flowchart_node_id=start_node.id,
                execution_index=1,
                agent_task_id=task.id,
                status="succeeded",
                input_context_json=json.dumps({}),
                output_state_json=json.dumps({"message": "ok"}),
            )
            flowchart_id = int(flowchart.id)
            run_id = int(flowchart_run.id)

        response = self.client.get(f"/flowcharts/{flowchart_id}/history/{run_id}?format=json")
        self.assertEqual(200, response.status_code)
        payload = response.get_json() or {}
        node_runs = payload.get("node_runs") or []
        self.assertEqual(1, len(node_runs))
        node_run = node_runs[0]
        self.assertEqual("kubernetes", node_run.get("selected_provider"))
        self.assertEqual("kubernetes", node_run.get("final_provider"))
        self.assertEqual("dispatch_confirmed", node_run.get("dispatch_status"))
        self.assertEqual("kubernetes -> kubernetes", node_run.get("provider_route"))
        self.assertEqual("workspace-main", node_run.get("workspace_identity"))
        self.assertEqual(
            "kubernetes:default/job-1",
            node_run.get("provider_dispatch_id"),
        )


if __name__ == "__main__":
    unittest.main()

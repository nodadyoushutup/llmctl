from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from flask import Flask
import psycopg

os.environ.setdefault(
    "LLMCTL_STUDIO_DATABASE_URI",
    "postgresql+psycopg://llmctl:llmctl@127.0.0.1:15432/llmctl_studio",
)

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
    Attachment,
    FLOWCHART_NODE_TYPE_START,
    Flowchart,
    FlowchartNode,
    FlowchartRun,
    FlowchartRunNode,
    MCPServer,
    Run,
    Script,
)
import web.views as studio_views


class StudioDbTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp_dir = Path(self._tmp.name)
        self._base_db_uri = os.environ["LLMCTL_STUDIO_DATABASE_URI"]
        self._schema_name = f"node_executor_stage8_{uuid.uuid4().hex}"
        self._orig_db_uri = Config.SQLALCHEMY_DATABASE_URI
        self._orig_workspaces_dir = Config.WORKSPACES_DIR
        self._create_schema(self._schema_name)
        Config.SQLALCHEMY_DATABASE_URI = self._with_search_path(
            self._base_db_uri,
            self._schema_name,
        )
        Config.WORKSPACES_DIR = str(tmp_dir / "workspaces")
        Path(Config.WORKSPACES_DIR).mkdir(parents=True, exist_ok=True)
        self._reset_engine()

    def tearDown(self) -> None:
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
                output=json.dumps(
                    {
                        "runtime_evidence": {
                            "provider_dispatch_id": "kubernetes:default/job-42",
                            "k8s_job_name": "job-42",
                            "k8s_pod_name": "pod-42",
                            "k8s_terminal_reason": "complete",
                        }
                    }
                ),
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
        self.assertEqual("", run_task.get("api_failure_category"))
        self.assertFalse(bool(run_task.get("cli_fallback_used")))
        self.assertEqual(
            "kubernetes:default/job-42",
            run_task.get("provider_dispatch_id"),
        )
        self.assertEqual("job-42", run_task.get("k8s_job_name"))
        self.assertEqual("pod-42", run_task.get("k8s_pod_name"))
        self.assertEqual("complete", run_task.get("k8s_terminal_reason"))

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
                output=json.dumps(
                    {
                        "runtime_evidence": {
                            "provider_dispatch_id": "kubernetes:default/job-1",
                            "k8s_job_name": "job-1",
                            "k8s_pod_name": "pod-1",
                            "k8s_terminal_reason": "complete",
                        }
                    }
                ),
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
                routing_state_json=json.dumps(
                    {
                        "runtime_evidence": {
                            "provider_dispatch_id": "kubernetes:default/job-1",
                            "k8s_job_name": "job-1",
                            "k8s_pod_name": "pod-1",
                            "k8s_terminal_reason": "complete",
                        }
                    }
                ),
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
        self.assertEqual("job-1", node_run.get("k8s_job_name"))
        self.assertEqual("pod-1", node_run.get("k8s_pod_name"))
        self.assertEqual("complete", node_run.get("k8s_terminal_reason"))

    def test_node_detail_api_includes_runtime_evidence_metadata(self) -> None:
        with session_scope() as session:
            task = AgentTask.create(
                session,
                status="succeeded",
                kind="rag_quick_index",
                selected_provider="kubernetes",
                final_provider="kubernetes",
                provider_dispatch_id="kubernetes:default/job-node-1",
                workspace_identity="workspace-main",
                dispatch_status="dispatch_confirmed",
                fallback_attempted=False,
                fallback_reason=None,
                dispatch_uncertain=False,
                api_failure_category=None,
                cli_fallback_used=False,
                cli_preflight_passed=None,
                output=json.dumps(
                    {
                        "runtime_evidence": {
                            "provider_dispatch_id": "kubernetes:default/job-node-1",
                            "k8s_job_name": "job-node-1",
                            "k8s_pod_name": "pod-node-1",
                            "k8s_terminal_reason": "complete",
                        }
                    }
                ),
            )
            task_id = int(task.id)

        response = self.client.get(f"/nodes/{task_id}?format=json")
        self.assertEqual(200, response.status_code)
        payload = response.get_json() or {}
        task_payload = payload.get("task") or {}
        self.assertEqual("kubernetes", task_payload.get("selected_provider"))
        self.assertEqual("dispatch_confirmed", task_payload.get("dispatch_status"))
        self.assertEqual("job-node-1", task_payload.get("k8s_job_name"))
        self.assertEqual("pod-node-1", task_payload.get("k8s_pod_name"))
        self.assertEqual("complete", task_payload.get("k8s_terminal_reason"))

    def test_node_status_api_includes_runtime_evidence_metadata(self) -> None:
        with session_scope() as session:
            task = AgentTask.create(
                session,
                status="failed",
                kind="rag_quick_index",
                selected_provider="kubernetes",
                final_provider="kubernetes",
                provider_dispatch_id="kubernetes:default/job-node-2",
                workspace_identity="workspace-main",
                dispatch_status="dispatch_confirmed",
                fallback_attempted=True,
                fallback_reason="create_failed",
                dispatch_uncertain=False,
                api_failure_category=None,
                cli_fallback_used=False,
                cli_preflight_passed=None,
                output=json.dumps(
                    {
                        "runtime_evidence": {
                            "provider_dispatch_id": "kubernetes:default/job-node-2",
                            "k8s_job_name": "job-node-2",
                            "k8s_pod_name": "pod-node-2",
                            "k8s_terminal_reason": "create_failed",
                        }
                    }
                ),
            )
            task_id = int(task.id)

        response = self.client.get(f"/nodes/{task_id}/status")
        self.assertEqual(200, response.status_code)
        payload = response.get_json() or {}
        self.assertEqual("kubernetes", payload.get("selected_provider"))
        self.assertEqual("dispatch_confirmed", payload.get("dispatch_status"))
        self.assertEqual("job-node-2", payload.get("k8s_job_name"))
        self.assertEqual("pod-node-2", payload.get("k8s_pod_name"))
        self.assertEqual("create_failed", payload.get("k8s_terminal_reason"))

    def test_retry_node_api_queues_cloned_node(self) -> None:
        with session_scope() as session:
            agent = Agent.create(
                session,
                name="Retry Agent",
                prompt_json="{}",
            )
            script = Script.create(
                session,
                file_name="retry-init.sh",
                content="#!/usr/bin/env bash\necho retry\n",
                script_type="init",
            )
            attachment = Attachment.create(
                session,
                file_name="retry.txt",
                file_path="/tmp/retry.txt",
                content_type="text/plain",
                size_bytes=11,
            )
            mcp_server = MCPServer.create(
                session,
                name="Retry MCP",
                server_key=f"retry-mcp-{uuid.uuid4().hex[:10]}",
                config_json={"command": "echo", "args": ["retry"]},
            )
            source_task = AgentTask.create(
                session,
                agent_id=agent.id,
                status="succeeded",
                prompt='{"message":"retry me"}',
                kind="task",
                integration_keys_json='["github"]',
                run_task_id="run-task-source",
                celery_task_id="celery-source",
                current_stage="post_run",
                stage_logs='{"post_run":"done"}',
                output="source output",
                error="source error",
            )
            source_task.scripts = [script]
            source_task.attachments = [attachment]
            source_task.mcp_servers = [mcp_server]
            source_task_id = int(source_task.id)

        class _FakeCeleryResult:
            id = "celery-retry-123"

        with patch.object(
            studio_views.run_agent_task,
            "delay",
            return_value=_FakeCeleryResult(),
        ) as delay_mock:
            response = self.client.post(f"/nodes/{source_task_id}/retry", json={})

        self.assertEqual(201, response.status_code)
        payload = response.get_json() or {}
        self.assertTrue(bool(payload.get("ok")))
        self.assertEqual(source_task_id, payload.get("source_task_id"))
        retry_task_id = int(payload.get("task_id"))
        self.assertNotEqual(source_task_id, retry_task_id)
        self.assertEqual("celery-retry-123", payload.get("celery_task_id"))
        delay_mock.assert_called_once_with(retry_task_id)

        with session_scope() as session:
            source_task = session.get(AgentTask, source_task_id)
            retry_task = session.get(AgentTask, retry_task_id)

            self.assertIsNotNone(source_task)
            self.assertIsNotNone(retry_task)
            if source_task is None or retry_task is None:
                return

            self.assertEqual("queued", retry_task.status)
            self.assertEqual(source_task.agent_id, retry_task.agent_id)
            self.assertEqual(source_task.prompt, retry_task.prompt)
            self.assertEqual(source_task.kind, retry_task.kind)
            self.assertEqual(
                source_task.integration_keys_json,
                retry_task.integration_keys_json,
            )
            self.assertEqual("celery-retry-123", retry_task.celery_task_id)
            self.assertIsNone(retry_task.run_task_id)
            self.assertIsNone(retry_task.current_stage)
            self.assertIsNone(retry_task.stage_logs)
            self.assertIsNone(retry_task.output)
            self.assertIsNone(retry_task.error)
            self.assertEqual(
                sorted(script.id for script in source_task.scripts),
                sorted(script.id for script in retry_task.scripts),
            )
            self.assertEqual(
                sorted(attachment.id for attachment in source_task.attachments),
                sorted(attachment.id for attachment in retry_task.attachments),
            )
            self.assertEqual(
                sorted(server.id for server in source_task.mcp_servers),
                sorted(server.id for server in retry_task.mcp_servers),
            )


if __name__ == "__main__":
    unittest.main()

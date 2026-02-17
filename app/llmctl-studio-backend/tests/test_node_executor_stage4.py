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
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

os.environ.setdefault(
    "LLMCTL_STUDIO_DATABASE_URI",
    "postgresql+psycopg://llmctl:llmctl@127.0.0.1:15432/llmctl_studio",
)

import core.db as core_db
from core.config import Config
from core.db import session_scope
from core.models import AgentTask
from core.prompt_envelope import build_prompt_envelope, serialize_prompt_envelope
from core.task_kinds import QUICK_TASK_KIND, RAG_QUICK_INDEX_TASK_KIND
from services import tasks as studio_tasks


class StudioDbTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._tmp_path = Path(self._tmp.name)
        self._base_db_uri = os.environ["LLMCTL_STUDIO_DATABASE_URI"]
        self._schema_name = f"node_executor_stage4_{uuid.uuid4().hex}"
        self._orig_db_uri = Config.SQLALCHEMY_DATABASE_URI
        self._create_schema(self._schema_name)
        Config.SQLALCHEMY_DATABASE_URI = self._with_search_path(
            self._base_db_uri,
            self._schema_name,
        )
        self._reset_engine()

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


class NodeExecutorStage4QuickRagTests(StudioDbTestCase):
    @staticmethod
    def _quick_rag_prompt_payload() -> str:
        return serialize_prompt_envelope(
            build_prompt_envelope(
                user_request="Quick RAG index for docs source.",
                task_context={
                    "kind": RAG_QUICK_INDEX_TASK_KIND,
                    "rag_quick_run": {
                        "source_id": 11,
                        "source_name": "Docs",
                        "collection": "docs",
                        "mode": "fresh",
                        "flowchart_mode": "fresh_index",
                        "model_provider": "codex",
                    },
                },
                output_contract={"format": "json"},
            )
        )

    def _create_quick_rag_task(self) -> int:
        with session_scope() as session:
            task = AgentTask.create(
                session,
                status="queued",
                kind=RAG_QUICK_INDEX_TASK_KIND,
                prompt=self._quick_rag_prompt_payload(),
            )
            return int(task.id)

    def test_quick_rag_executor_path_avoids_worker_compute(self) -> None:
        task_id = self._create_quick_rag_task()
        captured_events: list[dict[str, object]] = []

        class _StubRoutedRequest:
            def __init__(self, run_metadata: dict[str, object]) -> None:
                self._run_metadata = dict(run_metadata)

            def run_metadata_payload(self) -> dict[str, object]:
                return dict(self._run_metadata)

        class _StubExecutionRouter:
            last_callback_name = ""

            def __init__(self, runtime_settings=None) -> None:
                self.runtime_settings = runtime_settings or {}

            def route_request(self, _request):
                return _StubRoutedRequest(
                    {
                        "selected_provider": "kubernetes",
                        "final_provider": "kubernetes",
                        "provider_dispatch_id": "",
                        "workspace_identity": "default",
                        "dispatch_status": "dispatch_pending",
                        "fallback_attempted": False,
                        "fallback_reason": None,
                        "dispatch_uncertain": False,
                        "api_failure_category": None,
                        "cli_fallback_used": False,
                        "cli_preflight_passed": None,
                    }
                )

            def execute_routed(self, _request, execute_callback):
                _StubExecutionRouter.last_callback_name = execute_callback.__name__
                return SimpleNamespace(
                    status="success",
                    output_state={
                        "node_type": "rag",
                        "mode": "fresh_index",
                        "collections": ["docs"],
                        "index_summary": {
                            "source_count": 1,
                            "total_files": 2,
                            "total_chunks": 3,
                        },
                    },
                    routing_state={},
                    error=None,
                    run_metadata={
                        "selected_provider": "kubernetes",
                        "final_provider": "kubernetes",
                        "provider_dispatch_id": "kubernetes:default/job-quick-1",
                        "workspace_identity": "default",
                        "dispatch_status": "dispatch_confirmed",
                        "fallback_attempted": False,
                        "fallback_reason": None,
                        "dispatch_uncertain": False,
                        "api_failure_category": None,
                        "cli_fallback_used": False,
                        "cli_preflight_passed": None,
                    },
                    provider_metadata={
                        "k8s_job_name": "job-quick-1",
                        "k8s_pod_name": "pod-quick-1",
                        "k8s_terminal_reason": "complete",
                    },
                )

        def _capture_emit(**kwargs):
            captured_events.append(dict(kwargs))
            return {}

        with patch.object(studio_tasks, "ExecutionRouter", _StubExecutionRouter), patch.object(
            studio_tasks,
            "load_node_executor_runtime_settings",
            return_value={"provider": "kubernetes"},
        ), patch.object(
            studio_tasks,
            "run_index_for_collections",
            side_effect=AssertionError("worker compute should not run"),
        ) as run_index_mock, patch.object(
            studio_tasks,
            "emit_contract_event",
            side_effect=_capture_emit,
        ):
            studio_tasks.run_quick_rag_task.run(task_id)

        self.assertEqual(
            "_quick_rag_worker_compute_disabled",
            _StubExecutionRouter.last_callback_name,
        )
        run_index_mock.assert_not_called()

        with session_scope() as session:
            stored = session.get(AgentTask, task_id)
            assert stored is not None
            self.assertEqual("succeeded", stored.status)
            self.assertEqual(
                "kubernetes:default/job-quick-1",
                stored.provider_dispatch_id,
            )
            output_payload = json.loads(stored.output or "{}")
            runtime_evidence = output_payload.get("runtime_evidence") or {}
            self.assertEqual(
                "kubernetes:default/job-quick-1",
                runtime_evidence.get("provider_dispatch_id"),
            )
            self.assertEqual("job-quick-1", runtime_evidence.get("k8s_job_name"))
            self.assertEqual("pod-quick-1", runtime_evidence.get("k8s_pod_name"))
            self.assertEqual("complete", runtime_evidence.get("k8s_terminal_reason"))

        completed_payloads = [
            event.get("payload")
            for event in captured_events
            if event.get("event_type") == "node.task.completed"
        ]
        self.assertTrue(completed_payloads)
        completed_payload = completed_payloads[-1] or {}
        runtime_evidence = completed_payload.get("runtime_evidence") or {}
        self.assertEqual("job-quick-1", runtime_evidence.get("k8s_job_name"))

    def test_quick_rag_failure_persists_terminal_runtime_diagnostic(self) -> None:
        task_id = self._create_quick_rag_task()
        captured_events: list[dict[str, object]] = []

        class _StubRoutedRequest:
            def run_metadata_payload(self) -> dict[str, object]:
                return {
                    "selected_provider": "kubernetes",
                    "final_provider": "kubernetes",
                    "provider_dispatch_id": "",
                    "workspace_identity": "default",
                    "dispatch_status": "dispatch_pending",
                    "fallback_attempted": False,
                    "fallback_reason": None,
                    "dispatch_uncertain": False,
                    "api_failure_category": None,
                    "cli_fallback_used": False,
                    "cli_preflight_passed": None,
                }

        class _StubExecutionRouter:
            def __init__(self, runtime_settings=None) -> None:
                self.runtime_settings = runtime_settings or {}

            def route_request(self, _request):
                return _StubRoutedRequest()

            def execute_routed(self, _request, _execute_callback):
                return SimpleNamespace(
                    status="failed",
                    output_state={},
                    routing_state={},
                    error={"code": "execution_error", "message": "pod terminated"},
                    run_metadata={
                        "selected_provider": "kubernetes",
                        "final_provider": "kubernetes",
                        "provider_dispatch_id": "kubernetes:default/job-quick-2",
                        "workspace_identity": "default",
                        "dispatch_status": "dispatch_confirmed",
                        "fallback_attempted": True,
                        "fallback_reason": "create_failed",
                        "dispatch_uncertain": False,
                        "api_failure_category": None,
                        "cli_fallback_used": False,
                        "cli_preflight_passed": None,
                    },
                    provider_metadata={
                        "k8s_job_name": "job-quick-2",
                        "k8s_pod_name": "pod-quick-2",
                    },
                )

        def _capture_emit(**kwargs):
            captured_events.append(dict(kwargs))
            return {}

        with patch.object(studio_tasks, "ExecutionRouter", _StubExecutionRouter), patch.object(
            studio_tasks,
            "load_node_executor_runtime_settings",
            return_value={"provider": "kubernetes"},
        ), patch.object(
            studio_tasks,
            "emit_contract_event",
            side_effect=_capture_emit,
        ):
            studio_tasks.run_quick_rag_task.run(task_id)

        with session_scope() as session:
            stored = session.get(AgentTask, task_id)
            assert stored is not None
            self.assertEqual("failed", stored.status)
            self.assertEqual("pod terminated", stored.error)
            output_payload = json.loads(stored.output or "{}")
            runtime_evidence = output_payload.get("runtime_evidence") or {}
            self.assertEqual("job-quick-2", runtime_evidence.get("k8s_job_name"))
            self.assertEqual("pod-quick-2", runtime_evidence.get("k8s_pod_name"))
            self.assertEqual(
                "create_failed",
                runtime_evidence.get("k8s_terminal_reason"),
            )

        completed_payloads = [
            event.get("payload")
            for event in captured_events
            if event.get("event_type") == "node.task.completed"
        ]
        self.assertTrue(completed_payloads)
        completed_payload = completed_payloads[-1] or {}
        self.assertEqual("failed", completed_payload.get("terminal_status"))
        runtime_evidence = completed_payload.get("runtime_evidence") or {}
        self.assertEqual(
            "create_failed",
            runtime_evidence.get("k8s_terminal_reason"),
        )


class NodeExecutorStage4QuickTaskTests(StudioDbTestCase):
    @staticmethod
    def _quick_prompt_payload() -> str:
        return serialize_prompt_envelope(
            build_prompt_envelope(
                user_request="Review local code.",
                task_context={"kind": QUICK_TASK_KIND},
                output_contract={"format": "markdown"},
            )
        )

    def _create_quick_task(self) -> int:
        with session_scope() as session:
            task = AgentTask.create(
                session,
                status="queued",
                kind=QUICK_TASK_KIND,
                prompt=self._quick_prompt_payload(),
            )
            return int(task.id)

    def test_quick_task_dispatches_via_executor_router(self) -> None:
        task_id = self._create_quick_task()

        class _StubRoutedRequest:
            def run_metadata_payload(self) -> dict[str, object]:
                return {
                    "selected_provider": "kubernetes",
                    "final_provider": "kubernetes",
                    "provider_dispatch_id": "",
                    "workspace_identity": "default",
                    "dispatch_status": "dispatch_pending",
                    "fallback_attempted": False,
                    "fallback_reason": None,
                    "dispatch_uncertain": False,
                    "api_failure_category": None,
                    "cli_fallback_used": False,
                    "cli_preflight_passed": None,
                }

        class _StubExecutionRouter:
            last_callback_name = ""

            def __init__(self, runtime_settings=None) -> None:
                self.runtime_settings = runtime_settings or {}

            def route_request(self, _request):
                return _StubRoutedRequest()

            def execute_routed(self, _request, execute_callback):
                _StubExecutionRouter.last_callback_name = execute_callback.__name__
                return SimpleNamespace(
                    status="success",
                    output_state={},
                    routing_state={},
                    error=None,
                    run_metadata={
                        "selected_provider": "kubernetes",
                        "final_provider": "kubernetes",
                        "provider_dispatch_id": "kubernetes:default/job-quick-task-1",
                        "workspace_identity": "default",
                        "dispatch_status": "dispatch_confirmed",
                        "fallback_attempted": False,
                        "fallback_reason": None,
                        "dispatch_uncertain": False,
                        "api_failure_category": None,
                        "cli_fallback_used": False,
                        "cli_preflight_passed": None,
                    },
                    provider_metadata={
                        "k8s_job_name": "job-quick-task-1",
                        "k8s_pod_name": "pod-quick-task-1",
                        "k8s_terminal_reason": "complete",
                    },
                )

        with patch.object(studio_tasks, "ExecutionRouter", _StubExecutionRouter), patch.object(
            studio_tasks,
            "load_node_executor_runtime_settings",
            return_value={"provider": "kubernetes"},
        ), patch.object(
            studio_tasks,
            "_execute_agent_task",
            side_effect=AssertionError("worker compute should not run"),
        ) as execute_task_mock, patch.object(
            studio_tasks,
            "emit_contract_event",
            return_value={},
        ):
            studio_tasks.run_agent_task.run(task_id)

        execute_task_mock.assert_not_called()
        self.assertEqual(
            "_agent_task_worker_compute_disabled",
            _StubExecutionRouter.last_callback_name,
        )

        with session_scope() as session:
            stored = session.get(AgentTask, task_id)
            assert stored is not None
            self.assertEqual("running", stored.status)
            self.assertEqual("dispatch_confirmed", stored.dispatch_status)
            self.assertEqual("kubernetes", stored.selected_provider)
            self.assertEqual("kubernetes", stored.final_provider)
            self.assertEqual(
                "kubernetes:default/job-quick-task-1",
                stored.provider_dispatch_id,
            )


if __name__ == "__main__":
    unittest.main()

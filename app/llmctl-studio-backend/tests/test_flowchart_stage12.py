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
    FLOWCHART_NODE_TYPE_START,
    Flowchart,
    FlowchartNode,
    FlowchartRun,
    FlowchartRunNode,
    NodeArtifact,
    NODE_ARTIFACT_TYPE_MEMORY,
)
from services import tasks as studio_tasks
import web.views as studio_views


class FlowchartStage12Tests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp_dir = Path(self._tmp.name)
        self._base_db_uri = os.environ["LLMCTL_STUDIO_DATABASE_URI"]
        self._schema_name = f"flowchart_stage12_{uuid.uuid4().hex}"
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
        template_dir = STUDIO_SRC / "web" / "templates"
        self.app = Flask("stage12-api-tests", template_folder=str(template_dir))
        self.app.config["TESTING"] = True
        self.app.secret_key = "stage12-tests"
        self.app.register_blueprint(studio_views.bp)
        self.client = self.app.test_client()

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

    def _create_flowchart_run(
        self,
        *,
        status: str = "queued",
    ) -> tuple[int, int, int]:
        with session_scope() as session:
            flowchart = Flowchart.create(session, name="stage12-flowchart")
            start = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                title="Start",
                x=0.0,
                y=0.0,
                config_json=json.dumps({}),
            )
            run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status=status,
            )
            return int(flowchart.id), int(start.id), int(run.id)

    def test_control_pause_resume_are_idempotent(self) -> None:
        _, _, run_id = self._create_flowchart_run(status="queued")

        pause = self.client.post(
            f"/flowcharts/runs/{run_id}/control",
            json={"action": "pause"},
        )
        self.assertEqual(200, pause.status_code)
        pause_payload = pause.get_json() or {}
        self.assertTrue(bool(pause_payload.get("updated")))
        self.assertEqual("paused", (pause_payload.get("flowchart_run") or {}).get("status"))

        pause_again = self.client.post(
            f"/flowcharts/runs/{run_id}/control",
            json={"action": "pause"},
        )
        self.assertEqual(200, pause_again.status_code)
        pause_again_payload = pause_again.get_json() or {}
        self.assertFalse(bool(pause_again_payload.get("updated")))
        self.assertTrue(bool(pause_again_payload.get("idempotent")))

        resume = self.client.post(
            f"/flowcharts/runs/{run_id}/control",
            json={"action": "resume"},
        )
        self.assertEqual(200, resume.status_code)
        resume_payload = resume.get_json() or {}
        self.assertTrue(bool(resume_payload.get("updated")))
        self.assertEqual("running", (resume_payload.get("flowchart_run") or {}).get("status"))

    def test_control_retry_uses_idempotency_key_for_single_replay(self) -> None:
        _, _, run_id = self._create_flowchart_run(status="failed")
        with patch.object(
            studio_views.run_flowchart,
            "delay",
            return_value=SimpleNamespace(id="stage12-replay-task"),
        ) as replay_delay:
            first = self.client.post(
                f"/flowcharts/runs/{run_id}/control",
                json={"action": "retry", "idempotency_key": "retry-k1"},
            )
            self.assertEqual(200, first.status_code)
            first_payload = first.get_json() or {}
            self.assertEqual("replay_queued", first_payload.get("applied_action"))
            replay_run = first_payload.get("replay_run") or {}
            self.assertGreater(int(replay_run.get("id") or 0), 0)

            second = self.client.post(
                f"/flowcharts/runs/{run_id}/control",
                json={"action": "retry", "idempotency_key": "retry-k1"},
            )
            self.assertEqual(200, second.status_code)
            second_payload = second.get_json() or {}
            self.assertEqual("replay_existing", second_payload.get("applied_action"))
            self.assertTrue(bool(second_payload.get("idempotent")))
            self.assertEqual(replay_run.get("id"), (second_payload.get("replay_run") or {}).get("id"))

        self.assertEqual(1, replay_delay.call_count)

    def test_trace_and_status_surface_warning_and_trace_ids(self) -> None:
        flowchart_id, node_id, run_id = self._create_flowchart_run(status="succeeded")
        with session_scope() as session:
            node_run = FlowchartRunNode.create(
                session,
                flowchart_run_id=run_id,
                flowchart_node_id=node_id,
                execution_index=1,
                status="succeeded",
                input_context_json=json.dumps({"request_id": "trace-req-1"}),
                output_state_json=json.dumps(
                    {
                        "node_type": "memory",
                        "request_id": "trace-req-1",
                        "correlation_id": "trace-corr-1",
                        "deterministic_tooling": {
                            "tool_name": "deterministic.memory",
                            "operation": "retrieve",
                            "execution_status": "success_with_warning",
                            "fallback_used": True,
                            "warnings": [{"message": "fallback path used"}],
                            "request_id": "trace-req-1",
                            "correlation_id": "trace-corr-1",
                        },
                    }
                ),
                routing_state_json=json.dumps({}),
                degraded_status=True,
                degraded_reason="deterministic_fallback_used",
            )
            NodeArtifact.create(
                session,
                flowchart_id=flowchart_id,
                flowchart_node_id=node_id,
                flowchart_run_id=run_id,
                flowchart_run_node_id=node_run.id,
                node_type="memory",
                artifact_type=NODE_ARTIFACT_TYPE_MEMORY,
                payload_json=json.dumps(
                    {"action": "retrieve", "action_results": [], "routing_state": {}}
                ),
                request_id="trace-req-1",
                correlation_id="trace-corr-1",
                variant_key="stage12-artifact",
            )

        trace_response = self.client.get(
            f"/flowcharts/runs/{run_id}/trace",
            query_string={
                "include": "node,tool,artifact,timeline",
                "degraded_only": "true",
                "trace_request_id": "trace-req-1",
                "limit": "25",
            },
        )
        self.assertEqual(200, trace_response.status_code)
        trace_payload = trace_response.get_json() or {}
        node_items = ((trace_payload.get("node_trace") or {}).get("items")) or []
        tool_items = ((trace_payload.get("tool_trace") or {}).get("items")) or []
        artifact_items = ((trace_payload.get("artifact_trace") or {}).get("items")) or []
        timeline_items = ((trace_payload.get("timeline") or {}).get("items")) or []
        self.assertEqual(1, len(node_items))
        self.assertEqual("trace-req-1", node_items[0].get("request_id"))
        self.assertTrue(bool(node_items[0].get("warnings")))
        self.assertEqual(1, len(tool_items))
        self.assertEqual("trace-corr-1", tool_items[0].get("correlation_id"))
        self.assertEqual(1, len(artifact_items))
        self.assertEqual("trace-req-1", artifact_items[0].get("request_id"))
        self.assertTrue(
            any(str(item.get("event_type") or "") == "flowchart_warning" for item in timeline_items)
        )

        status_response = self.client.get(f"/flowcharts/runs/{run_id}/status")
        self.assertEqual(200, status_response.status_code)
        status_payload = status_response.get_json() or {}
        self.assertEqual(1, int(status_payload.get("warning_count") or 0))
        warnings = status_payload.get("warnings") or []
        self.assertEqual("deterministic_fallback_used", warnings[0].get("message"))

    def test_emit_flowchart_run_event_defaults_request_and_correlation(self) -> None:
        run = SimpleNamespace(
            id=99,
            status="running",
            started_at=None,
            finished_at=None,
            updated_at=None,
        )
        captured: list[dict[str, object]] = []

        def _capture(**kwargs):
            captured.append(kwargs)

        with patch.object(studio_tasks, "emit_contract_event", side_effect=_capture):
            studio_tasks._emit_flowchart_run_event(
                "flowchart.run.updated",
                run=run,
                flowchart_id=7,
                payload={"transition": "started"},
            )

        self.assertEqual(1, len(captured))
        call = captured[0]
        payload = call.get("payload") or {}
        self.assertTrue(str(call.get("request_id") or "").startswith("flowchart-run-99"))
        self.assertEqual("flowchart-run-99", call.get("correlation_id"))
        self.assertEqual("flowchart-run-99", payload.get("correlation_id"))


if __name__ == "__main__":
    unittest.main()

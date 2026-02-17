from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

from services.realtime_events import (
    build_event_envelope,
    emit_contract_event,
    normalize_runtime_metadata,
    task_scope_rooms,
)

try:
    import sqlalchemy  # noqa: F401

    HAS_SQLALCHEMY = True
except Exception:
    HAS_SQLALCHEMY = False


class RealtimeEventsStage6Tests(unittest.TestCase):
    def test_build_event_envelope_includes_sequence_and_idempotency(self) -> None:
        first = build_event_envelope(
            event_type="node.task.updated",
            entity_kind="task",
            entity_id=42,
            room_keys=["task:42", "run:7", "task:42"],
            payload={"status": "running"},
            runtime={"selected_provider": "workspace", "fallback_attempted": "false"},
        )
        second = build_event_envelope(
            event_type="node.task.updated",
            entity_kind="task",
            entity_id=42,
            room_keys=["task:42"],
            payload={"status": "succeeded"},
            runtime={"selected_provider": "workspace", "fallback_attempted": False},
        )

        self.assertEqual("v1", first["contract_version"])
        self.assertEqual(first["event_id"], first["idempotency_key"])
        self.assertEqual(["task:42", "run:7"], first["room_keys"])
        self.assertEqual("task:42", first["sequence_stream"])
        self.assertEqual(1, int(first["sequence"]))
        self.assertEqual(2, int(second["sequence"]))

    def test_emit_contract_event_emits_once_per_room(self) -> None:
        captured: list[tuple[str, dict[str, object], str | None]] = []

        def _capture(
            event_name: str,
            payload: dict[str, object] | None = None,
            *,
            room: str | None = None,
            namespace: str = "/rt",
        ) -> None:
            del namespace
            captured.append((event_name, payload or {}, room))

        with patch("services.realtime_events.emit_realtime", side_effect=_capture):
            envelope = emit_contract_event(
                event_type="flowchart.run.updated",
                entity_kind="flowchart_run",
                entity_id=9,
                room_keys=["flowchart_run:9", "flowchart:5", "flowchart_run:9"],
                payload={"status": "running"},
                runtime=None,
            )

        self.assertEqual(2, len(captured))
        self.assertEqual("flowchart.run.updated", captured[0][0])
        self.assertEqual("flowchart_run:9", captured[0][2])
        self.assertEqual("flowchart:5", captured[1][2])
        self.assertEqual(envelope["event_id"], captured[0][1]["event_id"])
        self.assertEqual(envelope["event_id"], captured[1][1]["event_id"])

    def test_runtime_metadata_normalization(self) -> None:
        normalized = normalize_runtime_metadata(
            {
                "selected_provider": "docker",
                "final_provider": "workspace",
                "provider_dispatch_id": "docker:abc123",
                "workspace_identity": "workspace-main",
                "dispatch_status": "dispatch_confirmed",
                "fallback_attempted": "true",
                "fallback_reason": "provider_unavailable",
                "dispatch_uncertain": "false",
                "api_failure_category": "socket_missing",
                "cli_fallback_used": "false",
                "cli_preflight_passed": None,
            }
        )
        self.assertIsNotNone(normalized)
        assert normalized is not None
        self.assertTrue(bool(normalized["fallback_attempted"]))
        self.assertFalse(bool(normalized["dispatch_uncertain"]))
        self.assertFalse(bool(normalized["cli_fallback_used"]))
        self.assertEqual("docker", normalized["selected_provider"])
        self.assertEqual("workspace", normalized["final_provider"])
        self.assertEqual("docker:abc123", normalized["provider_dispatch_id"])
        self.assertEqual(["task:1", "run:2", "flowchart:3"], task_scope_rooms(
            task_id=1,
            run_id=2,
            flowchart_id=3,
            flowchart_run_id=None,
            flowchart_node_id=None,
        ))


@unittest.skipUnless(HAS_SQLALCHEMY, "sqlalchemy is required for runtime parity integration tests")
class RealtimeRuntimeParityStage6Tests(unittest.TestCase):
    def setUp(self) -> None:
        import core.db as core_db
        from core.config import Config
        from core.db import session_scope
        from core.models import (
            FLOWCHART_NODE_TYPE_END,
            FLOWCHART_NODE_TYPE_START,
            Flowchart,
            FlowchartEdge,
            FlowchartNode,
            FlowchartRun,
        )
        from services import tasks as studio_tasks
        from services.integrations import save_node_executor_settings

        self.core_db = core_db
        self.Config = Config
        self.session_scope = session_scope
        self.FLOWCHART_NODE_TYPE_END = FLOWCHART_NODE_TYPE_END
        self.FLOWCHART_NODE_TYPE_START = FLOWCHART_NODE_TYPE_START
        self.Flowchart = Flowchart
        self.FlowchartEdge = FlowchartEdge
        self.FlowchartNode = FlowchartNode
        self.FlowchartRun = FlowchartRun
        self.studio_tasks = studio_tasks
        self.save_node_executor_settings = save_node_executor_settings
        self._tmp = tempfile.TemporaryDirectory()
        self._tmp_path = Path(self._tmp.name)
        self._orig_db_uri = self.Config.SQLALCHEMY_DATABASE_URI
        self.Config.SQLALCHEMY_DATABASE_URI = (
            f"sqlite:///{self._tmp_path / 'realtime-stage6.sqlite3'}"
        )
        self._dispose_engine()
        self.core_db.init_engine(self.Config.SQLALCHEMY_DATABASE_URI)
        self.core_db.init_db()

    def tearDown(self) -> None:
        self._dispose_engine()
        self.Config.SQLALCHEMY_DATABASE_URI = self._orig_db_uri
        self._tmp.cleanup()

    def _dispose_engine(self) -> None:
        if self.core_db._engine is not None:
            self.core_db._engine.dispose()
        self.core_db._engine = None
        self.core_db.SessionLocal = None

    def _create_simple_flowchart_run(self) -> tuple[int, int]:
        with self.session_scope() as session:
            flowchart = self.Flowchart.create(session, name="stage6-realtime-flowchart")
            start_node = self.FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=self.FLOWCHART_NODE_TYPE_START,
                title="Start",
                x=0.0,
                y=0.0,
            )
            end_node = self.FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=self.FLOWCHART_NODE_TYPE_END,
                title="End",
                x=200.0,
                y=0.0,
            )
            self.FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=end_node.id,
            )
            run = self.FlowchartRun.create(
                session, flowchart_id=flowchart.id, status="queued"
            )
            return int(flowchart.id), int(run.id)

    def _capture_node_completed_runtime(self, provider: str) -> list[dict[str, object]]:
        self.save_node_executor_settings(
            {
                "provider": provider,
                "workspace_identity_key": "workspace-main",
            }
        )
        flowchart_id, run_id = self._create_simple_flowchart_run()
        captured: list[dict[str, object]] = []

        def _capture_emit(**kwargs):
            if kwargs.get("event_type") == "node.task.completed":
                runtime = kwargs.get("runtime")
                if isinstance(runtime, dict):
                    captured.append(dict(runtime))
            return {}

        with patch.object(
            self.studio_tasks, "emit_contract_event", side_effect=_capture_emit
        ):
            self.studio_tasks.run_flowchart.run(flowchart_id, run_id)
        return captured

    def test_runtime_schema_matches_across_workspace_and_docker_selection(self) -> None:
        workspace_events = self._capture_node_completed_runtime("workspace")
        docker_events = self._capture_node_completed_runtime("docker")
        self.assertGreaterEqual(len(workspace_events), 1)
        self.assertGreaterEqual(len(docker_events), 1)

        expected_keys = {
            "selected_provider",
            "final_provider",
            "provider_dispatch_id",
            "workspace_identity",
            "dispatch_status",
            "fallback_attempted",
            "fallback_reason",
            "dispatch_uncertain",
            "api_failure_category",
            "cli_fallback_used",
            "cli_preflight_passed",
        }
        for payload in workspace_events + docker_events:
            self.assertEqual(expected_keys, set(payload.keys()))

        self.assertEqual(
            {"workspace"},
            {str(item["selected_provider"]) for item in workspace_events},
        )
        self.assertEqual(
            {"workspace"},
            {str(item["final_provider"]) for item in workspace_events},
        )
        self.assertEqual(
            {"docker"},
            {str(item["selected_provider"]) for item in docker_events},
        )
        self.assertEqual(
            {"workspace"},
            {str(item["final_provider"]) for item in docker_events},
        )


if __name__ == "__main__":
    unittest.main()

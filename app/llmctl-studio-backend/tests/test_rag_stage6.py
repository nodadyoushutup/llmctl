from __future__ import annotations

import sys
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

from rag.worker.queues import (
    RAG_QUEUE_BY_SOURCE_KIND,
    queue_for_source_kind,
)

try:
    from rag.worker import tasks as rag_tasks
    from rag.web import scheduler as rag_scheduler

    RAG_WORKER_AVAILABLE = True
except ModuleNotFoundError:
    rag_tasks = None
    rag_scheduler = None
    RAG_WORKER_AVAILABLE = False


class RagQueueRoutingTests(unittest.TestCase):
    def test_queue_mapping_by_source_kind(self) -> None:
        self.assertEqual("llmctl_studio.rag.index", queue_for_source_kind("local"))
        self.assertEqual("llmctl_studio.rag.git", queue_for_source_kind("github"))
        self.assertEqual("llmctl_studio.rag.drive", queue_for_source_kind("google_drive"))
        self.assertEqual("llmctl_studio.rag.index", queue_for_source_kind("unknown"))
        self.assertIn("drive", RAG_QUEUE_BY_SOURCE_KIND)
        self.assertIn("git", RAG_QUEUE_BY_SOURCE_KIND)


@unittest.skipUnless(RAG_WORKER_AVAILABLE, "RAG worker dependencies are required")
class RagWorkerOrchestrationTests(unittest.TestCase):
    def test_start_source_index_job_is_decommissioned_for_existing_source(self) -> None:
        source = SimpleNamespace(id=11, kind="github")
        with patch.object(rag_tasks, "get_source", return_value=source):
            result = rag_tasks.start_source_index_job(
                11,
                reset=False,
                index_mode="delta",
                trigger_mode="scheduled",
            )

        self.assertIsNone(result)

    def test_start_source_index_job_raises_for_missing_source(self) -> None:
        with patch.object(rag_tasks, "get_source", return_value=None):
            with self.assertRaisesRegex(ValueError, "Source not found"):
                rag_tasks.start_source_index_job(9999)

    def test_resume_source_index_job_is_decommissioned(self) -> None:
        result = rag_tasks.resume_source_index_job(3)
        self.assertIsNone(result)

    def test_pause_source_index_job_is_decommissioned(self) -> None:
        result = rag_tasks.pause_source_index_job(44)
        self.assertIsNone(result)

    def test_cancel_source_index_job_is_decommissioned(self) -> None:
        result = rag_tasks.cancel_source_index_job(9)
        self.assertIsNone(result)

    def test_run_index_task_returns_deprecated_payload(self) -> None:
        payload = rag_tasks.run_index_task.run(None, 1, 1)
        self.assertFalse(payload.get("ok", True))
        self.assertTrue(payload.get("deprecated"))
        self.assertIn("decommissioned", str(payload.get("error") or "").lower())

    def test_source_index_job_snapshot_reports_decommissioned_state(self) -> None:
        source = SimpleNamespace(id=7, last_error="boom", last_indexed_at=None)
        with patch.object(rag_tasks, "get_source", return_value=source):
            snapshot = rag_tasks.source_index_job_snapshot(7)

        self.assertFalse(snapshot.get("running"))
        self.assertTrue(snapshot.get("decommissioned"))
        self.assertFalse(snapshot.get("can_resume"))
        self.assertIsNone(snapshot.get("status"))
        self.assertEqual("boom", snapshot.get("last_error"))

    def test_source_index_job_snapshot_raises_for_missing_source(self) -> None:
        with patch.object(rag_tasks, "get_source", return_value=None):
            with self.assertRaisesRegex(ValueError, "Source not found"):
                rag_tasks.source_index_job_snapshot(100)


@unittest.skipUnless(RAG_WORKER_AVAILABLE, "RAG worker dependencies are required")
class RagSourceSchedulerTests(unittest.TestCase):
    def test_source_scheduler_is_disabled(self) -> None:
        self.assertFalse(rag_scheduler.source_scheduler_enabled())

    def test_scheduler_poll_seconds_is_zero(self) -> None:
        self.assertEqual(0.0, rag_scheduler.source_scheduler_poll_seconds())

    def test_scheduler_run_once_returns_zero(self) -> None:
        self.assertEqual(0, rag_scheduler.run_scheduled_source_indexes_once())

    def test_scheduler_start_stop_are_noops(self) -> None:
        self.assertIsNone(rag_scheduler.start_source_scheduler())
        self.assertIsNone(rag_scheduler.stop_source_scheduler())


if __name__ == "__main__":
    unittest.main()

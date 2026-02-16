from __future__ import annotations

import sys
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio" / "src"
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
    def test_start_source_index_job_creates_and_enqueues(self) -> None:
        source = SimpleNamespace(id=11, kind="github")
        created = SimpleNamespace(id=31)
        queued = SimpleNamespace(id=31, status="queued")
        with (
            patch.object(rag_tasks, "get_source", return_value=source),
            patch.object(rag_tasks, "has_active_index_job", return_value=False),
            patch.object(rag_tasks, "create_index_job", return_value=created) as create_job,
            patch.object(rag_tasks, "_enqueue_index_task", return_value=True) as enqueue,
            patch.object(rag_tasks, "get_task", return_value=queued),
        ):
            result = rag_tasks.start_source_index_job(
                11,
                reset=False,
                index_mode="delta",
                trigger_mode="scheduled",
            )

        self.assertIsNotNone(result)
        create_job.assert_called_once()
        kwargs = create_job.call_args.kwargs
        self.assertEqual(11, kwargs["source_id"])
        self.assertEqual("delta", kwargs["mode"])
        self.assertEqual("scheduled", kwargs["trigger_mode"])
        enqueue.assert_called_once_with(31, 11, False, "delta")

    def test_start_source_index_job_skips_when_duplicate_active(self) -> None:
        with (
            patch.object(rag_tasks, "get_source", return_value=SimpleNamespace(id=5)),
            patch.object(rag_tasks, "has_active_index_job", return_value=True),
            patch.object(rag_tasks, "create_index_job") as create_job,
        ):
            result = rag_tasks.start_source_index_job(5)

        self.assertIsNone(result)
        create_job.assert_not_called()

    def test_resume_source_index_job_requeues_paused_job(self) -> None:
        paused = SimpleNamespace(id=9, status="paused", mode="fresh")
        resumed = SimpleNamespace(id=9, status="queued", mode="fresh")
        with (
            patch.object(rag_tasks, "has_active_index_job", return_value=False),
            patch.object(rag_tasks, "latest_index_job", return_value=paused),
            patch.object(rag_tasks, "resume_index_job", return_value=resumed),
            patch.object(rag_tasks, "task_meta", return_value={"reset": True, "index_mode": "delta"}),
            patch.object(rag_tasks, "_enqueue_index_task", return_value=True) as enqueue,
            patch.object(rag_tasks, "get_task", return_value=resumed),
        ):
            result = rag_tasks.resume_source_index_job(3)

        self.assertIsNotNone(result)
        enqueue.assert_called_once_with(9, 3, True, "delta")

    def test_pause_source_index_job_requests_non_terminating_revoke_for_queued(self) -> None:
        active = SimpleNamespace(id=12, status="queued", celery_task_id="celery-1")
        paused = SimpleNamespace(id=12, status="paused")
        with (
            patch.object(rag_tasks, "active_index_job", return_value=active),
            patch.object(rag_tasks, "pause_index_job", return_value=paused),
            patch.object(rag_tasks.celery_app.control, "revoke") as revoke,
            patch.object(rag_tasks, "get_task", return_value=paused),
        ):
            result = rag_tasks.pause_source_index_job(44)

        self.assertIsNotNone(result)
        revoke.assert_called_once_with("celery-1", terminate=False)

    def test_cancel_source_index_job_terminates_worker_task(self) -> None:
        active = SimpleNamespace(id=22, status="running", celery_task_id="celery-22")
        cancelled = SimpleNamespace(id=22, status="cancelled")
        with (
            patch.object(rag_tasks, "active_index_job", return_value=active),
            patch.object(rag_tasks.celery_app.control, "revoke") as revoke,
            patch.object(rag_tasks, "cancel_index_job") as cancel_job,
            patch.object(rag_tasks, "get_task", return_value=cancelled),
        ):
            result = rag_tasks.cancel_source_index_job(9)

        self.assertIsNotNone(result)
        revoke.assert_called_once_with("celery-22", terminate=True, signal="SIGTERM")
        cancel_job.assert_called_once_with(22)


@unittest.skipUnless(RAG_WORKER_AVAILABLE, "RAG worker dependencies are required")
class RagSourceSchedulerTests(unittest.TestCase):
    def test_scheduler_starts_due_sources_with_scheduled_trigger(self) -> None:
        due_local = SimpleNamespace(id=1, index_schedule_mode="fresh")
        due_git = SimpleNamespace(id=2, index_schedule_mode="delta")
        with (
            patch.object(rag_scheduler, "list_due_sources", return_value=[due_local, due_git]),
            patch.object(rag_scheduler, "has_active_index_job", side_effect=[False, True]),
            patch.object(rag_scheduler, "start_source_index_job", return_value=SimpleNamespace(id=100)) as start_job,
            patch.object(rag_scheduler, "schedule_source_next_index") as schedule_next,
        ):
            started = rag_scheduler.run_scheduled_source_indexes_once()

        self.assertEqual(1, started)
        start_job.assert_called_once_with(
            1,
            reset=False,
            index_mode="fresh",
            trigger_mode="scheduled",
        )
        schedule_next.assert_called_once()


if __name__ == "__main__":
    unittest.main()

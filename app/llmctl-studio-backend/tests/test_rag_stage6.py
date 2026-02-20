from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

from rag.worker.queues import (
    RAG_QUEUE_BY_SOURCE_KIND,
    queue_for_source_kind,
)

try:
    from rag.web import scheduler as rag_scheduler

    RAG_SCHEDULER_AVAILABLE = True
except ModuleNotFoundError:
    rag_scheduler = None
    RAG_SCHEDULER_AVAILABLE = False


class RagQueueRoutingTests(unittest.TestCase):
    def test_queue_mapping_by_source_kind(self) -> None:
        self.assertEqual("llmctl_studio.rag.index", queue_for_source_kind("local"))
        self.assertEqual("llmctl_studio.rag.git", queue_for_source_kind("github"))
        self.assertEqual("llmctl_studio.rag.drive", queue_for_source_kind("google_drive"))
        self.assertEqual("llmctl_studio.rag.index", queue_for_source_kind("unknown"))
        self.assertIn("drive", RAG_QUEUE_BY_SOURCE_KIND)
        self.assertIn("git", RAG_QUEUE_BY_SOURCE_KIND)


@unittest.skipUnless(RAG_SCHEDULER_AVAILABLE, "RAG scheduler dependencies are required")
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

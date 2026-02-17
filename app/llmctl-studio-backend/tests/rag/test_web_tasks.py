from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))


class WebTaskProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.views_source = (
            STUDIO_SRC / "rag" / "web" / "views.py"
        ).read_text(encoding="utf-8")
        cls.sources_template = (
            STUDIO_SRC / "web" / "templates" / "rag" / "sources.html"
        ).read_text(encoding="utf-8")
        cls.app_js_source = (
            STUDIO_SRC / "web" / "static" / "rag" / "app.js"
        ).read_text(encoding="utf-8")

    def test_quick_run_routes_queue_quick_rag_tasks(self) -> None:
        self.assertIn("run_quick_rag_task.delay(task_id)", self.views_source)
        self.assertIn("A quick {mode_text} run is already active for this source.", self.views_source)
        self.assertIn("}, 202", self.views_source)
        self.assertNotIn('"deprecated": True', self.views_source)
        self.assertNotIn("}, 410", self.views_source)

    def test_source_status_api_reflects_active_quick_runs(self) -> None:
        self.assertIn("active_source_ids = _active_quick_rag_source_ids()", self.views_source)
        self.assertIn("has_active_job=int(source.id) in active_source_ids", self.views_source)
        self.assertIn("return {\"sources\": payload}", self.views_source)

    def test_sources_ui_exposes_quick_run_actions_without_legacy_jobs(self) -> None:
        self.assertIn("quick_index_source_page", self.sources_template)
        self.assertIn("quick_delta_index_source_page", self.sources_template)
        self.assertNotIn("rag-job-detail-progress", self.app_js_source)
        self.assertNotIn("index_jobs_page", self.views_source)


if __name__ == "__main__":
    unittest.main()

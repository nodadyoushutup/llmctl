from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio" / "src"
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

    def test_quick_run_routes_are_decommissioned(self) -> None:
        self.assertIn("Quick source {mode_text} runs now execute through flowchart RAG nodes.", self.views_source)
        self.assertIn('"deprecated": True', self.views_source)
        self.assertIn("}, 410", self.views_source)

    def test_source_status_api_forces_inactive_jobs(self) -> None:
        self.assertIn("has_active_job=False", self.views_source)
        self.assertIn("return {\"sources\": payload}", self.views_source)

    def test_legacy_index_job_ui_is_removed(self) -> None:
        self.assertNotIn("data-rag-quick-run", self.sources_template)
        self.assertNotIn("rag-job-detail-progress", self.app_js_source)
        self.assertNotIn("index_jobs_page", self.views_source)


if __name__ == "__main__":
    unittest.main()

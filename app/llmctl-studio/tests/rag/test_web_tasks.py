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
        cls.task_detail_template = (
            STUDIO_SRC / "web" / "templates" / "rag" / "index_job_detail.html"
        ).read_text(encoding="utf-8")
        cls.app_js_source = (
            STUDIO_SRC / "web" / "static" / "rag" / "app.js"
        ).read_text(encoding="utf-8")

    def test_task_payload_includes_progress(self) -> None:
        self.assertIn('"progress": progress', self.views_source)

    def test_task_status_api_serializes_task_payload(self) -> None:
        self.assertIn("return {\"tasks\": tasks}", self.views_source)
        self.assertIn("tasks.append(_task_payload(job))", self.views_source)

    def test_task_detail_template_renders_progress(self) -> None:
        self.assertIn('id="rag-job-detail-progress"', self.task_detail_template)
        self.assertIn("No progress details yet.", self.task_detail_template)
        self.assertIn("progressEl.textContent = summary || \"No progress details yet.\"", self.app_js_source)


if __name__ == "__main__":
    unittest.main()

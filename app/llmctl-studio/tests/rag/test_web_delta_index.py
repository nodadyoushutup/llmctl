from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))


class WebDeltaIndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.views_source = (
            STUDIO_SRC / "rag" / "web" / "views.py"
        ).read_text(encoding="utf-8")
        cls.sources_template = (
            STUDIO_SRC / "web" / "templates" / "rag" / "sources.html"
        ).read_text(encoding="utf-8")
        cls.source_detail_template = (
            STUDIO_SRC / "web" / "templates" / "rag" / "source_detail.html"
        ).read_text(encoding="utf-8")

    def test_web_app_supports_index_modes(self) -> None:
        self.assertIn("_normalize_quick_rag_mode", self.views_source)
        self.assertIn('"delta_index"', self.views_source)
        self.assertIn("run_quick_rag_task.delay(task_id)", self.views_source)

    def test_sources_templates_include_delta_actions(self) -> None:
        self.assertIn("quick_delta_index_source_page", self.sources_template)
        self.assertIn("quick_delta_index_source_page", self.source_detail_template)
        self.assertIn("Delta index source", self.sources_template)
        self.assertIn("Delta index source", self.source_detail_template)


if __name__ == "__main__":
    unittest.main()

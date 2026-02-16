from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))


class FlowchartRagMigrationStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.template_source = (
            STUDIO_SRC / "web" / "templates" / "flowchart_detail.html"
        ).read_text(encoding="utf-8")
        cls.tasks_source = (STUDIO_SRC / "services" / "tasks.py").read_text(
            encoding="utf-8"
        )
        cls.views_source = (STUDIO_SRC / "web" / "views.py").read_text(
            encoding="utf-8"
        )

    def test_flowchart_template_has_rag_palette_gating(self) -> None:
        self.assertIn("const ragPaletteState =", self.template_source)
        self.assertIn("ragPaletteVisible", self.template_source)
        self.assertIn("ragPaletteEnabled", self.template_source)
        self.assertIn("RAG node is hidden", self.template_source)

    def test_flowchart_template_has_rag_inspector_fields(self) -> None:
        self.assertIn("cfgRagMode", self.template_source)
        self.assertIn("cfgRagQuestionPrompt", self.template_source)
        self.assertIn("cfgRagTopK", self.template_source)
        self.assertIn("data-role-rag-collection", self.template_source)

    def test_tasks_module_has_rag_node_runtime_and_precheck(self) -> None:
        self.assertIn("def _execute_flowchart_rag_node", self.tasks_source)
        self.assertIn("RAG pre-run validation failed", self.tasks_source)
        self.assertIn("FLOWCHART_NODE_TYPE_RAG", self.tasks_source)

    def test_web_views_has_rag_config_validation(self) -> None:
        self.assertIn("def _sanitize_rag_node_config", self.views_source)
        self.assertIn("config.question_prompt is required for query mode", self.views_source)
        self.assertIn("FLOWCHART_NODE_TYPE_RAG", self.views_source)


if __name__ == "__main__":
    unittest.main()

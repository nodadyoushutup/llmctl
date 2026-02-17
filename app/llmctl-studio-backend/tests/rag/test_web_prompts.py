from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))


class WebPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.views_source = (
            STUDIO_SRC / "rag" / "web" / "views.py"
        ).read_text(encoding="utf-8")

    def test_system_prompt_mentions_markdown_support(self) -> None:
        self.assertIn(
            "Markdown formatting is supported in the chat UI",
            self.views_source,
        )

    def test_high_prompt_mentions_markdown_table(self) -> None:
        self.assertIn("return a markdown table", self.views_source.lower())

    def test_user_prompt_mentions_markdown(self) -> None:
        self.assertIn(
            "Use markdown formatting when it helps readability.",
            self.views_source,
        )


if __name__ == "__main__":
    unittest.main()

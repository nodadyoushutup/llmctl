import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class WebAppPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.web_app_source = (ROOT / "web_app.py").read_text(encoding="utf-8")

    def test_system_prompt_mentions_markdown_support(self):
        self.assertIn(
            "Markdown formatting is supported in the chat UI",
            self.web_app_source,
        )

    def test_high_prompt_mentions_markdown_table(self):
        self.assertIn("return a markdown table", self.web_app_source.lower())

    def test_user_prompt_mentions_markdown(self):
        self.assertIn(
            "Use markdown formatting when it helps readability.",
            self.web_app_source,
        )


if __name__ == "__main__":
    unittest.main()

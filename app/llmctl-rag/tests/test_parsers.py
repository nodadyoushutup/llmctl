import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from parsers import build_parser_registry, is_doc_type_enabled
from tests.helpers import test_config


class ParserTests(unittest.TestCase):
    def test_markdown_parser(self):
        registry = build_parser_registry()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "doc.md")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("# Title\n\nBody\n\n```python\nprint('x')\n```")
            parsed = registry.resolve(Path(path))(Path(path), test_config(Path(tmpdir)))
            self.assertIsNotNone(parsed)
            self.assertEqual(parsed.doc_type, "markdown")
            self.assertTrue(parsed.structural_hints.get("spans"))

    def test_html_parser(self):
        registry = build_parser_registry()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "doc.html")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("<h1>Title</h1><p>Hello</p>")
            parsed = registry.resolve(Path(path))(Path(path), test_config(Path(tmpdir)))
            self.assertIsNotNone(parsed)
            self.assertEqual(parsed.doc_type, "html")
            self.assertTrue(parsed.structural_hints.get("spans"))

    def test_doc_type_enabled(self):
        config = test_config()
        self.assertTrue(is_doc_type_enabled(config, "code"))
        config = replace(test_config(), enabled_doc_types={"pdf"})
        self.assertFalse(is_doc_type_enabled(config, "code"))
        self.assertTrue(is_doc_type_enabled(config, "pdf"))


if __name__ == "__main__":
    unittest.main()

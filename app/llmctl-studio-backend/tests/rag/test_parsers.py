import os
import sys
import tempfile
import unittest
import importlib.util
from dataclasses import replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
STUDIO_APP_ROOT = REPO_ROOT / "app" / "llmctl-studio-backend"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))
if str(STUDIO_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(STUDIO_APP_ROOT))

from rag.engine.parsers import build_parser_registry, is_doc_type_enabled

_HELPERS_SPEC = importlib.util.spec_from_file_location(
    "rag_test_helpers",
    STUDIO_APP_ROOT / "tests" / "rag" / "helpers.py",
)
if _HELPERS_SPEC is None or _HELPERS_SPEC.loader is None:  # pragma: no cover
    raise RuntimeError("Failed to load rag test helpers.")
_HELPERS_MODULE = importlib.util.module_from_spec(_HELPERS_SPEC)
_HELPERS_SPEC.loader.exec_module(_HELPERS_MODULE)
test_config = _HELPERS_MODULE.test_config


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

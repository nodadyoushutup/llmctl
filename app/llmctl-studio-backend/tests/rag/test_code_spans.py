import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

from rag.engine.code_spans import bash_spans, detect_language, js_ts_spans, python_spans


class CodeSpansTests(unittest.TestCase):
    def test_python_spans(self):
        text = (
            '"""Module doc"""\n\n'
            "class Foo:\n"
            "    def bar(self):\n"
            "        return 1\n\n"
            "async def baz():\n"
            "    return 2\n"
        )
        spans = python_spans(text)
        symbols = {(span["metadata"]["symbol"], span["metadata"]["symbol_type"]) for span in spans}
        self.assertIn(("__module_docstring__", "module_docstring"), symbols)
        self.assertIn(("Foo", "class"), symbols)
        self.assertIn(("bar", "function"), symbols)
        self.assertIn(("baz", "async_function"), symbols)

    def test_js_spans(self):
        text = """export function alpha() { return 1; }
class Beta { constructor() {} }
const gamma = () => { return 3; }
const delta = function() { return 4; }
"""
        spans = js_ts_spans(text)
        symbols = {span["metadata"]["symbol"] for span in spans}
        self.assertTrue({"alpha", "Beta", "gamma", "delta"}.issubset(symbols))

    def test_bash_spans(self):
        text = """#!/bin/bash
foo() { echo hi; }
function bar() { echo bye; }
"""
        spans = bash_spans(text)
        symbols = {span["metadata"]["symbol"] for span in spans}
        self.assertEqual({"foo", "bar"}, symbols)

    def test_detect_language(self):
        self.assertEqual(detect_language("#!/usr/bin/env python\nprint('x')"), "python")
        self.assertEqual(detect_language("function test() { return 1; }"), "javascript")
        self.assertEqual(detect_language("foo() { echo hi; }"), "bash")


if __name__ == "__main__":
    unittest.main()

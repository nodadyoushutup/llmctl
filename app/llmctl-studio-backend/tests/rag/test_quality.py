from __future__ import annotations

import os
import sys
import unittest
import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio" / "src"
STUDIO_APP_ROOT = REPO_ROOT / "app" / "llmctl-studio"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))
if str(STUDIO_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(STUDIO_APP_ROOT))

from rag.engine.chunkers import token_chunker
from rag.engine.pipeline import ParsedDocument

_HELPERS_SPEC = importlib.util.spec_from_file_location(
    "rag_test_helpers",
    STUDIO_APP_ROOT / "tests" / "rag" / "helpers.py",
)
if _HELPERS_SPEC is None or _HELPERS_SPEC.loader is None:  # pragma: no cover
    raise RuntimeError("Failed to load rag test helpers.")
_HELPERS_MODULE = importlib.util.module_from_spec(_HELPERS_SPEC)
_HELPERS_SPEC.loader.exec_module(_HELPERS_MODULE)
test_config = _HELPERS_MODULE.test_config


class QualityTests(unittest.TestCase):
    @unittest.skipUnless(
        os.getenv("RAG_QUALITY_TESTS"),
        "Set RAG_QUALITY_TESTS=1 to enable quality tests.",
    )
    def test_query_term_present_in_chunks(self) -> None:
        config = test_config()
        text = "The valve length is 5 inches and the bolt is 3 mm."
        doc = ParsedDocument(
            content=text,
            doc_type="text",
            language=None,
            source={},
        )
        chunks = token_chunker(doc, config)
        joined = " ".join(chunk.text for chunk in chunks)
        self.assertIn("5 inches", joined)
        self.assertIn("3 mm", joined)


if __name__ == "__main__":
    unittest.main()

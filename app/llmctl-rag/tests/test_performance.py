import os
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chunkers import token_chunker
from pipeline import ParsedDocument
from tests.helpers import test_config


class PerformanceTests(unittest.TestCase):
    @unittest.skipUnless(
        os.getenv("RAG_PERF_TESTS"),
        "Set RAG_PERF_TESTS=1 to enable performance tests.",
    )
    def test_token_chunker_speed(self):
        config = test_config()
        text = "word " * 200000
        doc = ParsedDocument(
            content=text,
            doc_type="text",
            language=None,
            source={},
        )
        start = time.time()
        chunks = token_chunker(doc, config)
        duration = time.time() - start
        self.assertTrue(chunks)
        self.assertLess(duration, 5.0)


if __name__ == "__main__":
    unittest.main()

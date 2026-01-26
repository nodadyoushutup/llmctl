import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chunkers import build_chunker_registry
from parsers import build_parser_registry
from tests.helpers import test_config


class RegressionTests(unittest.TestCase):
    @unittest.skipUnless(
        os.getenv("RAG_GOLDEN_MANIFEST") and os.getenv("RAG_GOLDEN_REPO"),
        "Set RAG_GOLDEN_MANIFEST and RAG_GOLDEN_REPO to enable regression tests.",
    )
    def test_golden_chunk_counts(self):
        manifest_path = Path(os.environ["RAG_GOLDEN_MANIFEST"]).expanduser()
        repo_root = Path(os.environ["RAG_GOLDEN_REPO"]).expanduser()
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected_files = data.get("files", {})

        config = test_config(repo_root)
        parser_registry = build_parser_registry()
        chunker_registry = build_chunker_registry()

        for rel_path, expected_count in expected_files.items():
            path = repo_root / rel_path
            parser = parser_registry.resolve(path)
            self.assertIsNotNone(parser, f"No parser for {rel_path}")
            parsed = parser(path, config)
            self.assertIsNotNone(parsed, f"Failed to parse {rel_path}")
            chunker = chunker_registry.resolve(parsed.doc_type)
            self.assertIsNotNone(chunker, f"No chunker for {rel_path}")
            chunks = chunker(parsed, config)
            self.assertEqual(
                expected_count,
                len(chunks),
                f"Chunk count mismatch for {rel_path}",
            )


if __name__ == "__main__":
    unittest.main()

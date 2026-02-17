from __future__ import annotations

import json
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

_HELPERS_SPEC = importlib.util.spec_from_file_location(
    "rag_test_helpers",
    STUDIO_APP_ROOT / "tests" / "rag" / "helpers.py",
)
if _HELPERS_SPEC is None or _HELPERS_SPEC.loader is None:  # pragma: no cover
    raise RuntimeError("Failed to load rag test helpers.")
_HELPERS_MODULE = importlib.util.module_from_spec(_HELPERS_SPEC)
_HELPERS_SPEC.loader.exec_module(_HELPERS_MODULE)
test_config = _HELPERS_MODULE.test_config


class RegressionTests(unittest.TestCase):
    @unittest.skipUnless(
        os.getenv("RAG_GOLDEN_MANIFEST") and os.getenv("RAG_GOLDEN_REPO"),
        "Set RAG_GOLDEN_MANIFEST and RAG_GOLDEN_REPO to enable regression tests.",
    )
    def test_golden_chunk_counts(self) -> None:
        from rag.engine.chunkers import build_chunker_registry
        from rag.engine.parsers import build_parser_registry

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

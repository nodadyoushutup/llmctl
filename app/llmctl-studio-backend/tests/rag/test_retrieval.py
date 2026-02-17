from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

from rag.engine.retrieval import build_context, build_query_text, query_collections


class _FakeCollection:
    def __init__(self, payload):
        self._payload = payload

    def query(self, query_texts, n_results):
        _ = query_texts
        _ = n_results
        return self._payload


class _FakeSource:
    def __init__(self, source_id: int, name: str, kind: str):
        self.id = source_id
        self.name = name
        self.kind = kind


class RetrievalTests(unittest.TestCase):
    def test_query_collections_merges_and_sorts_by_distance(self):
        source_a = _FakeSource(1, "alpha", "local")
        source_b = _FakeSource(2, "beta", "github")

        collections = [
            {
                "source": source_a,
                "collection": _FakeCollection(
                    {
                        "documents": [["doc-a1", "doc-a2"]],
                        "metadatas": [[{"path": "a1.md"}, {"path": "a2.md"}]],
                        "distances": [[0.9, 0.4]],
                    }
                ),
            },
            {
                "source": source_b,
                "collection": _FakeCollection(
                    {
                        "documents": [["doc-b1"]],
                        "metadatas": [[{"path": "b1.md"}]],
                        "distances": [[0.2]],
                    }
                ),
            },
        ]

        documents, metadatas = query_collections("question", collections, top_k=2)
        self.assertEqual(["doc-b1", "doc-a2"], documents)
        self.assertEqual("beta", metadatas[0].get("source_name"))
        self.assertEqual("alpha", metadatas[1].get("source_name"))

    def test_build_query_text_uses_recent_user_history(self):
        history = [
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "first answer"},
            {"role": "user", "content": "second question"},
        ]
        text = build_query_text("latest question", history, max_history=8)
        self.assertIn("first question", text)
        self.assertIn("second question", text)
        self.assertIn("latest question", text)

    def test_build_context_formats_labels_and_sources(self):
        context, sources = build_context(
            documents=["Alpha content", "Beta content"],
            metadatas=[
                {
                    "source_name": "alpha",
                    "path": "docs/a.md",
                    "start_line": 4,
                    "end_line": 8,
                },
                {"path": "docs/b.md"},
            ],
            max_chars=2000,
            snippet_chars=12,
        )
        self.assertIn("[1] alpha", context)
        self.assertIn("docs/a.md:4-8", context)
        self.assertEqual(2, len(sources))
        self.assertEqual("docs/b.md", sources[1]["path"])


if __name__ == "__main__":
    unittest.main()

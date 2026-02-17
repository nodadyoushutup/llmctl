from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))


class WebCollectionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.web_views_source = (
            STUDIO_SRC / "web" / "views.py"
        ).read_text(encoding="utf-8")
        cls.collections_template = (
            STUDIO_SRC / "web" / "templates" / "chroma_collections.html"
        ).read_text(encoding="utf-8")

    def test_collections_routes_exist(self) -> None:
        self.assertIn('@bp.get("/chroma/collections")', self.web_views_source)
        self.assertIn("def chroma_collections():", self.web_views_source)
        self.assertIn('@bp.get("/chroma/collections/detail")', self.web_views_source)
        self.assertIn("def chroma_collection_detail():", self.web_views_source)
        self.assertIn('@bp.post("/chroma/collections/delete")', self.web_views_source)
        self.assertIn("def delete_chroma_collection():", self.web_views_source)

    def test_collections_template_has_row_link_and_delete(self) -> None:
        self.assertIn('class="table-row-link"', self.collections_template)
        self.assertIn(
            "data-href=\"{{ url_for('agents.chroma_collection_detail', name=collection.name) }}\"",
            self.collections_template,
        )
        self.assertIn("url_for('agents.delete_chroma_collection')", self.collections_template)
        self.assertIn("fa-solid fa-trash", self.collections_template)


if __name__ == "__main__":
    unittest.main()

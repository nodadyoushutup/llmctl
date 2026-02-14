import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class WebAppCollectionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.web_app_source = (ROOT / "web_app.py").read_text(encoding="utf-8")
        cls.collections_template = (
            ROOT / "web" / "templates" / "collections.html"
        ).read_text(encoding="utf-8")

    def test_collections_routes_exist(self):
        self.assertIn('@app.get("/collections")', self.web_app_source)
        self.assertIn("def collections_index() -> str:", self.web_app_source)
        self.assertIn('@app.get("/collections/detail")', self.web_app_source)
        self.assertIn("def collections_detail() -> str:", self.web_app_source)
        self.assertIn('@app.post("/collections/delete")', self.web_app_source)
        self.assertIn("def remove_collection():", self.web_app_source)

    def test_collections_template_has_row_link_and_delete(self):
        self.assertIn('class="table-row-link"', self.collections_template)
        self.assertIn(
            'data-href="{{ url_for(\'collections_detail\', name=collection.name) }}"',
            self.collections_template,
        )
        self.assertIn("url_for('remove_collection')", self.collections_template)
        self.assertIn("fa-solid fa-trash", self.collections_template)


if __name__ == "__main__":
    unittest.main()

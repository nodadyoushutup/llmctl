import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class WebAppSourceRoutesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.web_app_source = (ROOT / "web_app.py").read_text(encoding="utf-8")
        cls.source_detail_template = (
            ROOT / "web" / "templates" / "source_detail.html"
        ).read_text(encoding="utf-8")
        cls.source_new_template = (
            ROOT / "web" / "templates" / "source_new.html"
        ).read_text(encoding="utf-8")
        cls.source_edit_template = (
            ROOT / "web" / "templates" / "source_edit.html"
        ).read_text(encoding="utf-8")

    def test_clear_collection_route_exists(self):
        self.assertIn(
            '@app.post("/sources/<int:source_id>/clear")',
            self.web_app_source,
        )
        self.assertIn("def clear_source_collection(source_id: int):", self.web_app_source)

    def test_clear_collection_route_resets_source_index_stats(self):
        self.assertIn(
            "client.delete_collection(name=source.collection)",
            self.web_app_source,
        )
        self.assertIn("client.get_or_create_collection(", self.web_app_source)
        self.assertIn("indexed_file_count=0", self.web_app_source)
        self.assertIn("indexed_chunk_count=0", self.web_app_source)
        self.assertIn("indexed_file_types=json.dumps({})", self.web_app_source)

    def test_clear_collection_route_has_task_guards_and_notices(self):
        self.assertIn('notice="source_busy"', self.web_app_source)
        self.assertIn('notice="source_resume_pending"', self.web_app_source)
        self.assertIn('notice="source_collection_cleared"', self.web_app_source)
        self.assertIn('notice="source_clear_error"', self.web_app_source)

    def test_source_detail_template_has_clear_collection_button(self):
        self.assertIn(
            "url_for('clear_source_collection', source_id=source.id)",
            self.source_detail_template,
        )
        self.assertIn("fa-solid fa-eraser", self.source_detail_template)
        self.assertIn("Clear collection data", self.source_detail_template)
        self.assertIn("source_notice", self.source_detail_template)

    def test_source_forms_include_schedule_inputs(self):
        self.assertIn("source_index_schedule_value", self.source_new_template)
        self.assertIn("source_index_schedule_unit", self.source_new_template)
        self.assertIn("source_index_schedule_value", self.source_edit_template)
        self.assertIn("source_index_schedule_unit", self.source_edit_template)

    def test_source_index_snapshot_includes_schedule_fields(self):
        self.assertIn('"schedule_value": getattr(source, "index_schedule_value"', self.web_app_source)
        self.assertIn('"next_index_at": _isoformat_datetime', self.web_app_source)

    def test_start_index_blocks_incomplete_source_tasks(self):
        self.assertIn("def _source_has_incomplete_index_task(source_id: int) -> bool:", self.web_app_source)
        self.assertIn("if _source_has_incomplete_index_task(source_id):", self.web_app_source)


if __name__ == "__main__":
    unittest.main()

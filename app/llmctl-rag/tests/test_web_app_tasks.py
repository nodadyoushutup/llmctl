import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class WebAppTaskProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.web_app_source = (ROOT / "web_app.py").read_text(encoding="utf-8")
        cls.task_detail_template = (
            ROOT / "web" / "templates" / "task_detail.html"
        ).read_text(encoding="utf-8")

    def test_task_payload_includes_progress(self):
        self.assertIn('"progress": _task_progress_payload(task)', self.web_app_source)

    def test_index_snapshot_includes_progress(self):
        self.assertIn('"progress": progress', self.web_app_source)

    def test_task_detail_template_renders_progress(self):
        self.assertIn('id="task-progress-summary"', self.task_detail_template)
        self.assertIn("No progress details yet.", self.task_detail_template)
        self.assertIn("updateProgress(data.progress);", self.task_detail_template)


if __name__ == "__main__":
    unittest.main()

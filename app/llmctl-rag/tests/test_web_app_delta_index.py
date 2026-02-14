import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class WebAppDeltaIndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.web_app_source = (ROOT / "web_app.py").read_text(encoding="utf-8")
        cls.app_js_source = (
            ROOT / "web" / "static" / "app.js"
        ).read_text(encoding="utf-8")
        cls.sources_template = (
            ROOT / "web" / "templates" / "sources.html"
        ).read_text(encoding="utf-8")
        cls.source_detail_template = (
            ROOT / "web" / "templates" / "source_detail.html"
        ).read_text(encoding="utf-8")

    def test_web_app_supports_index_modes(self):
        self.assertIn('INDEX_MODE_DELTA = "delta"', self.web_app_source)
        self.assertIn("_normalize_index_mode(payload.get(\"mode\"))", self.web_app_source)
        self.assertIn("\"index_mode\": normalized_mode", self.web_app_source)

    def test_sources_templates_include_delta_actions(self):
        self.assertIn("source-delta-btn", self.sources_template)
        self.assertIn("source-delta-btn", self.source_detail_template)
        self.assertIn("Delta index", self.sources_template)
        self.assertIn("Delta index", self.source_detail_template)

    def test_app_js_triggers_delta_mode(self):
        self.assertIn("const sourceDeltaButtons", self.app_js_source)
        self.assertIn("mode: \"delta\"", self.app_js_source)
        self.assertIn("startSourceDelta(sourceId);", self.app_js_source)


if __name__ == "__main__":
    unittest.main()

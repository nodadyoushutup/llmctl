from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))


class WebSourceRoutesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.views_source = (STUDIO_SRC / "rag" / "web" / "views.py").read_text(
            encoding="utf-8"
        )
        cls.routes_source = (STUDIO_SRC / "rag" / "web" / "routes.py").read_text(
            encoding="utf-8"
        )
        cls.source_new_template = (
            STUDIO_SRC / "web" / "templates" / "rag" / "source_new.html"
        ).read_text(encoding="utf-8")
        cls.source_edit_template = (
            STUDIO_SRC / "web" / "templates" / "rag" / "source_edit.html"
        ).read_text(encoding="utf-8")
        cls.sources_template = (
            STUDIO_SRC / "web" / "templates" / "rag" / "sources.html"
        ).read_text(encoding="utf-8")
        cls.source_detail_template = (
            STUDIO_SRC / "web" / "templates" / "rag" / "source_detail.html"
        ).read_text(encoding="utf-8")

    def test_source_forms_include_schedule_inputs(self) -> None:
        self.assertIn("source_index_schedule_value", self.source_new_template)
        self.assertIn("source_index_schedule_unit", self.source_new_template)
        self.assertIn("source_index_schedule_mode", self.source_new_template)
        self.assertIn("source_index_schedule_value", self.source_edit_template)
        self.assertIn("source_index_schedule_unit", self.source_edit_template)
        self.assertIn("source_index_schedule_mode", self.source_edit_template)

    def test_sources_page_uses_row_link_and_quick_run_actions(self) -> None:
        self.assertIn("table-row-link", self.sources_template)
        self.assertIn("data-href", self.sources_template)
        self.assertNotIn("data-rag-quick-run", self.sources_template)
        self.assertNotIn('data-rag-quick-run-mode="fresh"', self.sources_template)
        self.assertNotIn('data-rag-quick-run-mode="delta"', self.sources_template)
        self.assertNotIn("index_source_page", self.sources_template)
        self.assertNotIn("pause_source_page", self.sources_template)
        self.assertNotIn("resume_source_page", self.sources_template)
        self.assertNotIn("cancel_source_page", self.sources_template)

    def test_source_detail_uses_quick_run_actions_and_no_legacy_links(self) -> None:
        self.assertNotIn("data-rag-quick-run", self.source_detail_template)
        self.assertNotIn('data-rag-quick-run-mode="fresh"', self.source_detail_template)
        self.assertNotIn('data-rag-quick-run-mode="delta"', self.source_detail_template)
        self.assertNotIn("index_jobs_page", self.source_detail_template)
        self.assertNotIn("index_source_page", self.source_detail_template)

    def test_contract_routes_use_contract_prefix(self) -> None:
        self.assertIn('RAG_API_CONTRACT_PREFIX = f"{RAG_API_ROUTE_PREFIX}/contract"', self.routes_source)
        self.assertIn('RAG_API_HEALTH = f"{RAG_API_CONTRACT_PREFIX}/health"', self.routes_source)
        self.assertIn('RAG_API_COLLECTIONS = f"{RAG_API_CONTRACT_PREFIX}/collections"', self.routes_source)
        self.assertIn('RAG_API_RETRIEVE = f"{RAG_API_CONTRACT_PREFIX}/retrieve"', self.routes_source)

    def test_views_expose_contract_and_legacy_alias_endpoints(self) -> None:
        self.assertIn("@bp.get(RAG_API_HEALTH)", self.views_source)
        self.assertIn("@bp.get(RAG_API_HEALTH_LEGACY)", self.views_source)
        self.assertIn("@bp.get(RAG_API_COLLECTIONS)", self.views_source)
        self.assertIn("@bp.get(RAG_API_COLLECTIONS_LEGACY)", self.views_source)
        self.assertIn("@bp.post(RAG_API_RETRIEVE)", self.views_source)
        self.assertIn("@bp.post(RAG_API_RETRIEVE_LEGACY)", self.views_source)


if __name__ == "__main__":
    unittest.main()

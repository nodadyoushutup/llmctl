from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

import core.db as core_db
from core.config import Config
from rag.repositories.sources import RAGSourceInput, create_source
from rag.web import views as rag_views
from web import views as studio_views


class StudioDbTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp_dir = Path(self._tmp.name)
        self._orig_db_uri = Config.SQLALCHEMY_DATABASE_URI
        self._orig_data_dir = Config.DATA_DIR
        Config.SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_dir / 'stage7.sqlite3'}"
        Config.DATA_DIR = str(tmp_dir / "data")
        Path(Config.DATA_DIR).mkdir(parents=True, exist_ok=True)
        self._reset_engine()

    def tearDown(self) -> None:
        self._dispose_engine()
        Config.SQLALCHEMY_DATABASE_URI = self._orig_db_uri
        Config.DATA_DIR = self._orig_data_dir
        self._tmp.cleanup()

    def _dispose_engine(self) -> None:
        if core_db._engine is not None:
            core_db._engine.dispose()
        core_db._engine = None
        core_db.SessionLocal = None

    def _reset_engine(self) -> None:
        self._dispose_engine()
        core_db.init_engine(Config.SQLALCHEMY_DATABASE_URI)
        core_db.init_db()


class RagStage7ContractApiTests(StudioDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        template_dir = STUDIO_SRC / "web" / "templates"
        app = Flask("rag-stage7-tests", template_folder=str(template_dir))
        app.config["TESTING"] = True
        app.secret_key = "rag-stage7-tests"
        app.register_blueprint(studio_views.bp)
        app.register_blueprint(rag_views.bp)
        self.client = app.test_client()

    def _create_local_source(self, name: str = "Docs"):
        return create_source(
            RAGSourceInput(
                name=name,
                kind="local",
                local_path="/tmp/docs",
            )
        )

    def test_contract_health_endpoints_exposed(self) -> None:
        with patch.object(
            rag_views,
            "rag_health_snapshot",
            return_value={"state": "configured_healthy", "provider": "chroma"},
        ):
            contract_response = self.client.get("/api/rag/contract/health")
            legacy_response = self.client.get("/api/rag/health")

        self.assertEqual(200, contract_response.status_code)
        self.assertEqual(200, legacy_response.status_code)
        payload = contract_response.get_json() or {}
        self.assertEqual("configured_healthy", payload.get("state"))
        self.assertEqual("chroma", payload.get("provider"))
        self.assertEqual("v1", payload.get("contract_version"))

    def test_contract_collections_shape_from_sources(self) -> None:
        source = self._create_local_source("Reference Docs")

        response = self.client.get("/api/rag/contract/collections")
        self.assertEqual(200, response.status_code)
        payload = response.get_json() or {}

        self.assertEqual("chroma", payload.get("provider"))
        collections = payload.get("collections") or []
        self.assertTrue(collections)
        self.assertEqual(source.collection, collections[0].get("id"))
        self.assertEqual(source.collection, collections[0].get("name"))
        self.assertIn("status", collections[0])

    def test_contract_retrieve_unavailable_reason_code(self) -> None:
        source = self._create_local_source("Outage Docs")
        with patch.object(
            rag_views,
            "rag_health_snapshot",
            return_value={
                "state": "configured_unhealthy",
                "provider": "chroma",
                "error": "dial tcp timeout",
            },
        ):
            response = self.client.post(
                "/api/rag/contract/retrieve",
                json={
                    "question": "What changed?",
                    "collections": [source.collection],
                    "top_k": 3,
                },
            )

        self.assertEqual(503, response.status_code)
        payload = response.get_json() or {}
        error = payload.get("error") or {}
        self.assertEqual(
            "RAG_UNAVAILABLE_FOR_SELECTED_COLLECTIONS",
            error.get("reason_code"),
        )
        metadata = error.get("metadata") or {}
        self.assertIn(metadata.get("rag_health_state"), {"configured_unhealthy", "unconfigured"})
        self.assertEqual([source.collection], metadata.get("selected_collections"))
        self.assertEqual("chroma", metadata.get("provider"))

    def test_sources_page_uses_row_link_pattern_and_hides_index_jobs(self) -> None:
        self._create_local_source()
        response = self.client.get("/rag/sources")
        self.assertEqual(200, response.status_code)
        html = response.get_data(as_text=True)
        self.assertIn("table-row-link", html)
        self.assertIn("data-href=", html)
        self.assertNotIn("Index Jobs", html)

    def test_quick_index_endpoint_queues_task(self) -> None:
        source = self._create_local_source("Quick Source")
        with patch.object(
            rag_views.run_quick_rag_task,
            "delay",
            return_value=SimpleNamespace(id="quick-rag-1"),
        ):
            response = self.client.post(
                f"/rag/sources/{source.id}/quick-index",
                headers={"Accept": "application/json"},
            )
        self.assertEqual(202, response.status_code)
        payload = response.get_json() or {}
        self.assertTrue(payload.get("ok"))
        self.assertEqual("fresh", payload.get("mode"))
        self.assertTrue(int(payload.get("task_id") or 0) > 0)

    def test_quick_delta_endpoint_queues_task(self) -> None:
        source = self._create_local_source("Quick Delta Source")
        with patch.object(
            rag_views.run_quick_rag_task,
            "delay",
            return_value=SimpleNamespace(id="quick-rag-2"),
        ):
            response = self.client.post(
                f"/rag/sources/{source.id}/quick-delta-index",
                headers={"Accept": "application/json"},
            )
        self.assertEqual(202, response.status_code)
        payload = response.get_json() or {}
        self.assertTrue(payload.get("ok"))
        self.assertEqual("delta", payload.get("mode"))
        self.assertTrue(int(payload.get("task_id") or 0) > 0)

    def test_quick_index_endpoint_returns_404_for_missing_source(self) -> None:
        response = self.client.post(
            "/rag/sources/99999/quick-index",
            headers={"Accept": "application/json"},
        )
        self.assertEqual(404, response.status_code)
        payload = response.get_json() or {}
        self.assertFalse(payload.get("ok", True))
        self.assertEqual("Source not found.", payload.get("error"))

    def test_source_status_endpoint_reports_inactive_state(self) -> None:
        source = self._create_local_source("Status Source")
        response = self.client.get(f"/api/rag/sources/status?ids={source.id}")

        self.assertEqual(200, response.status_code)
        payload = response.get_json() or {}
        rows = payload.get("sources") or []
        self.assertEqual(1, len(rows))
        self.assertFalse(rows[0].get("has_active_job"))
        self.assertEqual("Not indexed", rows[0].get("status"))


if __name__ == "__main__":
    unittest.main()

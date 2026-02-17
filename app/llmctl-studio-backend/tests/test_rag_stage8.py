from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

import core.db as core_db
from core.config import Config
from core.db import session_scope
from core.models import (
    FLOWCHART_NODE_TYPE_START,
    Flowchart,
    FlowchartNode,
    LLMModel,
)
from rag.web import views as rag_views
from web import views as studio_views


class StudioDbTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp_dir = Path(self._tmp.name)
        self._orig_db_uri = Config.SQLALCHEMY_DATABASE_URI
        self._orig_data_dir = Config.DATA_DIR
        Config.SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_dir / 'stage8.sqlite3'}"
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


class RagStage8FlowchartValidationTests(StudioDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        template_dir = STUDIO_SRC / "web" / "templates"
        app = Flask("rag-stage8-tests", template_folder=str(template_dir))
        app.config["TESTING"] = True
        app.secret_key = "rag-stage8-tests"
        app.register_blueprint(studio_views.bp)
        app.register_blueprint(rag_views.bp)
        self.client = app.test_client()
        self.flowchart_id, self.start_node_id = self._create_flowchart_with_start()

    def _create_flowchart_with_start(self) -> tuple[int, int]:
        with session_scope() as session:
            flowchart = Flowchart.create(session, name="RAG Graph")
            start_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                title="Start",
                x=0.0,
                y=0.0,
                config_json=json.dumps({}, sort_keys=True),
            )
            return flowchart.id, start_node.id

    def _graph_payload(self, rag_node: dict[str, object]) -> dict[str, object]:
        return {
            "nodes": [
                {
                    "id": self.start_node_id,
                    "node_type": "start",
                    "title": "Start",
                    "ref_id": None,
                    "x": 0,
                    "y": 0,
                    "config": {},
                },
                rag_node,
            ],
            "edges": [
                {
                    "source_node_id": self.start_node_id,
                    "target_node_id": "new-rag",
                    "edge_mode": "solid",
                    "condition_key": None,
                    "label": None,
                }
            ],
        }

    def test_graph_rejects_rag_node_without_collections(self) -> None:
        payload = self._graph_payload(
            {
                "id": None,
                "client_id": "new-rag",
                "node_type": "rag",
                "title": "RAG",
                "ref_id": None,
                "x": 140,
                "y": 140,
                "config": {"mode": "query", "question_prompt": "Q"},
            }
        )

        response = self.client.post(
            f"/flowcharts/{self.flowchart_id}/graph",
            json=payload,
        )
        self.assertEqual(400, response.status_code)
        payload = response.get_json() or {}
        self.assertIn("config.collections", str(payload.get("error", "")))

    def test_graph_rejects_rag_query_without_question_prompt(self) -> None:
        payload = self._graph_payload(
            {
                "id": None,
                "client_id": "new-rag",
                "node_type": "rag",
                "title": "RAG",
                "ref_id": None,
                "x": 140,
                "y": 140,
                "config": {"mode": "query", "collections": ["docs"]},
            }
        )

        response = self.client.post(
            f"/flowcharts/{self.flowchart_id}/graph",
            json=payload,
        )
        self.assertEqual(400, response.status_code)
        payload = response.get_json() or {}
        self.assertIn("config.question_prompt", str(payload.get("error", "")))

    def test_graph_rejects_index_mode_for_non_embedding_model(self) -> None:
        with session_scope() as session:
            model = LLMModel.create(
                session,
                name="claude-non-embed",
                provider="claude",
                config_json="{}",
            )

        payload = self._graph_payload(
            {
                "id": None,
                "client_id": "new-rag",
                "node_type": "rag",
                "title": "RAG",
                "ref_id": None,
                "x": 140,
                "y": 140,
                "model_id": model.id,
                "config": {
                    "mode": "fresh_index",
                    "collections": ["docs"],
                },
            }
        )

        response = self.client.post(
            f"/flowcharts/{self.flowchart_id}/graph",
            json=payload,
        )
        self.assertEqual(400, response.status_code)
        payload = response.get_json() or {}
        self.assertIn("embedding-capable model provider", str(payload.get("error", "")))

    def test_graph_roundtrip_persists_rag_query_config(self) -> None:
        payload = self._graph_payload(
            {
                "id": None,
                "client_id": "new-rag",
                "node_type": "rag",
                "title": "RAG Query",
                "ref_id": None,
                "x": 140,
                "y": 140,
                "config": {
                    "mode": "query",
                    "collections": ["docs", "ops"],
                    "question_prompt": "What changed this week?",
                    "top_k": 7,
                },
            }
        )

        save_response = self.client.post(
            f"/flowcharts/{self.flowchart_id}/graph",
            json=payload,
        )
        self.assertEqual(200, save_response.status_code)
        save_payload = save_response.get_json() or {}
        saved_rag_node = next(
            node
            for node in (save_payload.get("nodes") or [])
            if str(node.get("node_type") or "").strip().lower() == "rag"
        )
        saved_config = saved_rag_node.get("config") or {}
        self.assertEqual("query", saved_config.get("mode"))
        self.assertEqual(["docs", "ops"], saved_config.get("collections"))
        self.assertEqual("What changed this week?", saved_config.get("question_prompt"))
        self.assertEqual(7, saved_config.get("top_k"))

        load_response = self.client.get(f"/flowcharts/{self.flowchart_id}/graph")
        self.assertEqual(200, load_response.status_code)
        load_payload = load_response.get_json() or {}
        loaded_rag_node = next(
            node
            for node in (load_payload.get("nodes") or [])
            if str(node.get("node_type") or "").strip().lower() == "rag"
        )
        loaded_config = loaded_rag_node.get("config") or {}
        self.assertEqual("query", loaded_config.get("mode"))
        self.assertEqual(["docs", "ops"], loaded_config.get("collections"))
        self.assertEqual("What changed this week?", loaded_config.get("question_prompt"))
        self.assertEqual(7, loaded_config.get("top_k"))

    def test_flowchart_page_exposes_rag_palette_state(self) -> None:
        with patch.object(
            studio_views,
            "rag_domain_health_snapshot",
            return_value={"state": "configured_unhealthy", "provider": "chroma", "error": "dial"},
        ):
            response = self.client.get(f"/flowcharts/{self.flowchart_id}")

        self.assertEqual(200, response.status_code)
        html = response.get_data(as_text=True)
        self.assertIn('const ragPaletteState = "configured_unhealthy";', html)


if __name__ == "__main__":
    unittest.main()

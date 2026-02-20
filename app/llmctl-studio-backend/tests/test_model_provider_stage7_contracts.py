from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from flask import Flask
import psycopg

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

os.environ.setdefault(
    "LLMCTL_STUDIO_DATABASE_URI",
    "postgresql+psycopg://llmctl:llmctl@127.0.0.1:15432/llmctl_studio",
)

import core.db as core_db
from core.config import Config
from core.db import session_scope
from core.models import LLMModel
from rag.web.views import bp as rag_bp
import web.views as studio_views


class ModelProviderStage7ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp_dir = Path(self._tmp.name)
        data_dir = tmp_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        self._orig_data_dir = Config.DATA_DIR
        self._orig_workspaces_dir = Config.WORKSPACES_DIR
        self._orig_db_uri = Config.SQLALCHEMY_DATABASE_URI
        self._base_db_uri = os.environ["LLMCTL_STUDIO_DATABASE_URI"]
        self._schema_name = f"model_provider_stage7_{uuid.uuid4().hex}"

        Config.DATA_DIR = str(data_dir)
        Config.WORKSPACES_DIR = str(tmp_dir / "workspaces")
        Path(Config.WORKSPACES_DIR).mkdir(parents=True, exist_ok=True)
        self._create_schema(self._schema_name)
        Config.SQLALCHEMY_DATABASE_URI = self._with_search_path(
            self._base_db_uri,
            self._schema_name,
        )

        self._dispose_engine()
        core_db.init_engine(Config.SQLALCHEMY_DATABASE_URI)
        core_db.init_db()

        app = Flask("model-provider-stage7-tests", template_folder=str(STUDIO_SRC / "web" / "templates"))
        app.config["TESTING"] = True
        app.secret_key = "model-provider-stage7"
        app.register_blueprint(studio_views.bp)
        app.register_blueprint(rag_bp)
        app.register_blueprint(studio_views.bp, url_prefix="/api", name="agents_api")
        self.client = app.test_client()

    def tearDown(self) -> None:
        self._dispose_engine()
        self._drop_schema(self._schema_name)
        Config.DATA_DIR = self._orig_data_dir
        Config.WORKSPACES_DIR = self._orig_workspaces_dir
        Config.SQLALCHEMY_DATABASE_URI = self._orig_db_uri
        self._tmp.cleanup()

    def _dispose_engine(self) -> None:
        if core_db._engine is not None:
            core_db._engine.dispose()
        core_db._engine = None
        core_db.SessionLocal = None

    @staticmethod
    def _as_psycopg_uri(database_uri: str) -> str:
        if database_uri.startswith("postgresql+psycopg://"):
            return "postgresql://" + database_uri.split("://", 1)[1]
        return database_uri

    @staticmethod
    def _with_search_path(database_uri: str, schema_name: str) -> str:
        parts = urlsplit(database_uri)
        query_items = parse_qsl(parts.query, keep_blank_values=True)
        updated_items: list[tuple[str, str]] = []
        options_value = f"-csearch_path={schema_name}"
        options_updated = False
        for key, value in query_items:
            if key == "options":
                merged = value.strip()
                if options_value not in merged:
                    merged = f"{merged} {options_value}".strip()
                updated_items.append((key, merged))
                options_updated = True
            else:
                updated_items.append((key, value))
        if not options_updated:
            updated_items.append(("options", options_value))
        query = urlencode(updated_items, doseq=True)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))

    def _create_schema(self, schema_name: str) -> None:
        with psycopg.connect(self._as_psycopg_uri(self._base_db_uri), autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"')

    def _drop_schema(self, schema_name: str) -> None:
        with psycopg.connect(self._as_psycopg_uri(self._base_db_uri), autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')

    def _create_model(self, *, name: str, provider: str, config: dict[str, object]) -> LLMModel:
        with session_scope() as session:
            return LLMModel.create(
                session,
                name=name,
                description=f"{name} description",
                provider=provider,
                config_json=json.dumps(config),
            )

    def test_models_list_supports_query_contract(self) -> None:
        self._create_model(name="Bravo Model", provider="codex", config={"model": "gpt-5.2-codex"})
        self._create_model(name="Alpha Model", provider="codex", config={"model": "gpt-5.2-codex"})
        self._create_model(name="Gamma Model", provider="gemini", config={"model": "gemini-2.5-pro"})

        response = self.client.get(
            "/api/models?provider=codex&search=model&sort_by=name&sort_order=asc&page=1&per_page=1",
            headers={"X-Request-ID": "req-stage7-model-list", "X-Correlation-ID": "corr-stage7-model-list"},
        )

        self.assertEqual(200, response.status_code)
        payload = response.get_json() or {}
        self.assertTrue(bool(payload.get("ok")))
        self.assertEqual("req-stage7-model-list", payload.get("request_id"))
        self.assertEqual("corr-stage7-model-list", payload.get("correlation_id"))
        self.assertEqual(2, int(payload.get("total_count") or 0))
        self.assertEqual(1, int(payload.get("count") or 0))
        first = (payload.get("models") or [None])[0] or {}
        self.assertEqual("Alpha Model", first.get("name"))
        pagination = payload.get("pagination") or {}
        self.assertTrue(bool(pagination.get("has_next")))

    def test_model_detail_reports_compatibility_drift(self) -> None:
        model = self._create_model(
            name="Drifted Codex Model",
            provider="codex",
            config={"model": "gpt-5.2-codex"},
        )

        response = self.client.get(
            f"/api/models/{model.id}",
            headers={"X-Request-ID": "req-stage7-model-detail", "X-Correlation-ID": "corr-stage7-model-detail"},
        )

        self.assertEqual(200, response.status_code)
        payload = response.get_json() or {}
        model_payload = payload.get("model") or {}
        compatibility = model_payload.get("compatibility") or {}
        self.assertTrue(bool(compatibility.get("drift_detected")))
        self.assertIn("approval_policy", compatibility.get("missing_keys") or [])

    def test_model_create_validation_uses_error_envelope(self) -> None:
        response = self.client.post(
            "/api/models",
            json={
                "provider": "codex",
                "config": {"model": "gpt-5.2-codex"},
            },
            headers={"X-Request-ID": "req-stage7-model-create-error", "X-Correlation-ID": "corr-stage7-model-create-error"},
        )

        self.assertEqual(400, response.status_code)
        payload = response.get_json() or {}
        error = payload.get("error") or {}
        self.assertEqual("invalid_request", error.get("code"))
        self.assertEqual("req-stage7-model-create-error", error.get("request_id"))
        self.assertEqual("corr-stage7-model-create-error", payload.get("correlation_id"))

    def test_providers_list_supports_filter_sort_contract(self) -> None:
        studio_views._save_integration_settings(
            "llm",
            {
                "provider": "codex",
                "provider_enabled_codex": "true",
                "provider_enabled_gemini": "true",
                "provider_enabled_claude": "",
                "provider_enabled_vllm_local": "",
                "provider_enabled_vllm_remote": "",
            },
        )

        response = self.client.get(
            "/api/providers?enabled=true&sort_by=label&sort_order=asc&page=1&per_page=2",
            headers={"X-Request-ID": "req-stage7-provider-list", "X-Correlation-ID": "corr-stage7-provider-list"},
        )

        self.assertEqual(200, response.status_code)
        payload = response.get_json() or {}
        self.assertTrue(bool(payload.get("ok")))
        self.assertEqual("req-stage7-provider-list", payload.get("request_id"))
        providers = payload.get("providers") or []
        self.assertGreaterEqual(len(providers), 1)
        self.assertTrue(all(bool(item.get("enabled")) for item in providers))

    def test_model_create_emits_contract_event_with_request_and_correlation_ids(self) -> None:
        with patch("web.views.emit_contract_event") as emit_contract_event:
            response = self.client.post(
                "/api/models",
                json={
                    "name": "Evented Model",
                    "description": "event contract",
                    "provider": "codex",
                    "config": {"model": "gpt-5.2-codex"},
                },
                headers={"X-Request-ID": "req-stage7-model-event", "X-Correlation-ID": "corr-stage7-model-event"},
            )

        self.assertEqual(201, response.status_code)
        emit_contract_event.assert_called_once()
        call = emit_contract_event.call_args
        kwargs = call.kwargs
        self.assertEqual("config:model:created", kwargs.get("event_type"))
        self.assertEqual("req-stage7-model-event", kwargs.get("request_id"))
        self.assertEqual("corr-stage7-model-event", kwargs.get("correlation_id"))


if __name__ == "__main__":
    unittest.main()

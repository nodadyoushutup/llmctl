from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

from flask import Flask

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
from rag.web.views import bp as rag_bp
import web.views as studio_views


class Stage6SettingsRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp_dir = Path(self._tmp.name)
        data_dir = tmp_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        self._orig_data_dir = Config.DATA_DIR
        self._orig_workspaces_dir = Config.WORKSPACES_DIR

        Config.DATA_DIR = str(data_dir)
        Config.WORKSPACES_DIR = str(tmp_dir / "workspaces")
        Path(Config.WORKSPACES_DIR).mkdir(parents=True, exist_ok=True)

        self._dispose_engine()
        core_db.init_engine(Config.SQLALCHEMY_DATABASE_URI)
        core_db.init_db()

        template_dir = STUDIO_SRC / "web" / "templates"
        app = Flask("stage6-settings-tests", template_folder=str(template_dir))
        app.config["TESTING"] = True
        app.secret_key = "stage6-settings"
        app.register_blueprint(studio_views.bp)
        app.register_blueprint(rag_bp)
        app.register_blueprint(studio_views.bp, url_prefix="/api", name="agents_api")
        self.client = app.test_client()

    def tearDown(self) -> None:
        self._dispose_engine()
        Config.DATA_DIR = self._orig_data_dir
        Config.WORKSPACES_DIR = self._orig_workspaces_dir
        self._tmp.cleanup()

    def _dispose_engine(self) -> None:
        if core_db._engine is not None:
            core_db._engine.dispose()
        core_db._engine = None
        core_db.SessionLocal = None

    def test_settings_core_api_returns_core_config(self) -> None:
        response = self.client.get("/api/settings/core")
        self.assertEqual(200, response.status_code)
        payload = response.get_json() or {}
        core_config = payload.get("core_config") or {}
        self.assertIn("DATABASE_FILENAME", core_config)
        self.assertTrue(str(core_config.get("DATABASE_FILENAME") or "").strip())

    def test_settings_core_html_renders(self) -> None:
        response = self.client.get("/settings/core", headers={"Accept": "text/html"})
        self.assertEqual(200, response.status_code)
        body = response.get_data(as_text=True)
        self.assertIn("Core Settings", body)


if __name__ == "__main__":
    unittest.main()

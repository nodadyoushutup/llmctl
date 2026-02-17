from __future__ import annotations

import os
import sys
import tempfile
import unittest
import uuid
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
from core.db import session_scope
from core.models import Attachment
from rag.web.views import bp as rag_bp
import web.views as studio_views


class Stage7ApiRouteTests(unittest.TestCase):
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
        app = Flask("stage7-api-tests", template_folder=str(template_dir))
        app.config["TESTING"] = True
        app.secret_key = "stage7-api"
        app.register_blueprint(studio_views.bp)
        app.register_blueprint(rag_bp)
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

    def test_models_json_create_and_default_toggle(self) -> None:
        create = self.client.post(
            "/models",
            json={
                "name": "Stage7 Model",
                "description": "model from json",
                "provider": "claude",
                "config": {"model": "claude-sonnet-4-5"},
            },
        )
        self.assertEqual(201, create.status_code)
        created_payload = create.get_json() or {}
        model_id = int(((created_payload.get("model") or {}).get("id") or 0))
        self.assertGreater(model_id, 0)

        listing = self.client.get("/models", headers={"Accept": "application/json"})
        self.assertEqual(200, listing.status_code)
        listing_payload = listing.get_json() or {}
        self.assertTrue(
            any(int(item.get("id") or 0) == model_id for item in (listing_payload.get("models") or []))
        )

        set_default = self.client.post(
            "/models/default",
            json={"model_id": model_id, "is_default": True},
        )
        self.assertEqual(200, set_default.status_code)
        self.assertEqual(model_id, (set_default.get_json() or {}).get("default_model_id"))

        detail = self.client.get(f"/models/{model_id}", headers={"Accept": "application/json"})
        self.assertEqual(200, detail.status_code)
        self.assertTrue(bool((detail.get_json() or {}).get("is_default")))

    def test_mcp_json_create_and_detail(self) -> None:
        server_key = f"stage7_mcp_{uuid.uuid4().hex[:8]}"
        create = self.client.post(
            "/mcps",
            json={
                "name": "Stage7 MCP",
                "server_key": server_key,
                "description": "custom",
                "config": {"command": "python3", "args": ["-V"]},
            },
        )
        self.assertEqual(201, create.status_code)
        payload = create.get_json() or {}
        mcp_id = int(((payload.get("mcp_server") or {}).get("id") or 0))
        self.assertGreater(mcp_id, 0)

        detail = self.client.get(f"/mcps/{mcp_id}", headers={"Accept": "application/json"})
        self.assertEqual(200, detail.status_code)
        detail_payload = detail.get_json() or {}
        self.assertEqual(mcp_id, int((detail_payload.get("mcp_server") or {}).get("id") or 0))

    def test_scripts_json_create_update_and_delete(self) -> None:
        create = self.client.post(
            "/scripts",
            json={
                "file_name": "stage7_script.py",
                "description": "script",
                "script_type": "pre_init",
                "content": "print('stage7')",
            },
        )
        self.assertEqual(201, create.status_code)
        script_id = int((((create.get_json() or {}).get("script") or {}).get("id") or 0))
        self.assertGreater(script_id, 0)

        update = self.client.post(
            f"/scripts/{script_id}",
            json={
                "file_name": "stage7_script.py",
                "description": "updated",
                "script_type": "post_run",
                "content": "print('updated')",
            },
        )
        self.assertEqual(200, update.status_code)
        self.assertEqual("updated", ((update.get_json() or {}).get("script") or {}).get("description"))

        delete = self.client.post(f"/scripts/{script_id}/delete", json={})
        self.assertEqual(200, delete.status_code)
        self.assertTrue(bool((delete.get_json() or {}).get("ok")))

    def test_skills_json_create_update_and_list(self) -> None:
        skill_name = f"stage7-skill-{uuid.uuid4().hex[:8]}"
        create = self.client.post(
            "/skills",
            json={
                "name": skill_name,
                "display_name": "Stage7 Skill",
                "description": "skill from json",
                "version": "1.0.0",
                "status": "active",
                "skill_md": "# Stage7 Skill\n\nInitial version.",
                "extra_files": [],
            },
        )
        self.assertEqual(201, create.status_code)
        skill_id = int((create.get_json() or {}).get("skill_id") or 0)
        self.assertGreater(skill_id, 0)

        update = self.client.post(
            f"/skills/{skill_id}",
            json={
                "display_name": "Stage7 Skill Updated",
                "description": "updated skill",
                "status": "active",
                "new_version": "2.0.0",
                "new_skill_md": "# Stage7 Skill\n\nSecond version.",
                "existing_files": [],
                "extra_files": [],
            },
        )
        self.assertEqual(200, update.status_code)
        self.assertEqual(
            "Stage7 Skill Updated",
            ((update.get_json() or {}).get("skill") or {}).get("display_name"),
        )

        listing = self.client.get("/skills", headers={"Accept": "application/json"})
        self.assertEqual(200, listing.status_code)
        listing_payload = listing.get_json() or {}
        self.assertTrue(
            any(int(item.get("id") or 0) == skill_id for item in (listing_payload.get("skills") or []))
        )

    def test_attachments_json_list_detail_and_delete(self) -> None:
        with session_scope() as session:
            attachment = Attachment.create(
                session,
                file_name="stage7.txt",
                file_path=None,
                content_type="text/plain",
                size_bytes=12,
            )
            attachment_id = int(attachment.id)

        listing = self.client.get("/attachments", headers={"Accept": "application/json"})
        self.assertEqual(200, listing.status_code)
        listing_payload = listing.get_json() or {}
        self.assertTrue(
            any(
                int(item.get("id") or 0) == attachment_id
                for item in (listing_payload.get("attachments") or [])
            )
        )

        detail = self.client.get(
            f"/attachments/{attachment_id}",
            headers={"Accept": "application/json"},
        )
        self.assertEqual(200, detail.status_code)
        detail_payload = detail.get_json() or {}
        self.assertEqual(attachment_id, int((detail_payload.get("attachment") or {}).get("id") or 0))

        delete = self.client.post(f"/attachments/{attachment_id}/delete", json={})
        self.assertEqual(200, delete.status_code)
        self.assertTrue(bool((delete.get_json() or {}).get("ok")))


if __name__ == "__main__":
    unittest.main()

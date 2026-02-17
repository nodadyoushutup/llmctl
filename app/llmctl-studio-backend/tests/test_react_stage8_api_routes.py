from __future__ import annotations

import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

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


class _FakeChromaCollection:
    def __init__(self, name: str):
        self.name = name
        self.metadata = {"owner": "stage8"}

    def count(self) -> int:
        return 12


class _FakeChromaClient:
    def list_collections(self):
        return ["docs", "runbooks"]

    def get_collection(self, name: str):
        return _FakeChromaCollection(name)

    def delete_collection(self, name: str):
        return None


class Stage8ApiRouteTests(unittest.TestCase):
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
        app = Flask("stage8-api-tests", template_folder=str(template_dir))
        app.config["TESTING"] = True
        app.secret_key = "stage8-api"
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

    def test_github_workspace_and_pull_request_json(self) -> None:
        def _integration_settings(provider: str):
            if provider == "github":
                return {"repo": "org/repo", "pat": "ghp_test"}
            return {}

        with (
            patch("web.views._load_integration_settings", side_effect=_integration_settings),
            patch("web.views._fetch_github_pull_requests", return_value=[{"number": 9, "title": "Update API", "author": "alice"}]),
            patch("web.views._fetch_github_actions", return_value=[{"name": "CI", "status": "success"}]),
            patch("web.views._fetch_github_contents", return_value={"entries": [{"path": "README.md", "type": "file"}], "file": None}),
            patch("web.views._fetch_github_pull_request_detail", return_value={"number": 9, "title": "Update API", "requested_reviewers": ["bob"]}),
            patch("web.views._fetch_github_pull_request_timeline", return_value=([{"id": 1, "body": "Looks good"}], ["alice"])),
        ):
            listing = self.client.get("/api/github")
            self.assertEqual(200, listing.status_code)
            listing_payload = listing.get_json() or {}
            self.assertTrue(bool(listing_payload.get("pull_requests")))

            detail = self.client.get("/api/github/pulls/9")
            self.assertEqual(200, detail.status_code)
            detail_payload = detail.get_json() or {}
            self.assertEqual(9, int((detail_payload.get("pull_request") or {}).get("number") or 0))

    def test_jira_and_confluence_json(self) -> None:
        def _integration_settings(provider: str):
            if provider == "jira":
                return {
                    "api_key": "jira-key",
                    "email": "owner@example.com",
                    "site": "https://example.atlassian.net",
                    "board": "Platform",
                }
            if provider == "confluence":
                return {
                    "api_key": "conf-key",
                    "email": "owner@example.com",
                    "site": "https://example.atlassian.net/wiki",
                    "space": "ENG",
                }
            return {}

        with (
            patch("web.views._load_integration_settings", side_effect=_integration_settings),
            patch("web.views._fetch_jira_board_by_name", return_value={"id": 11, "type": "scrum", "location": {"projectKey": "OPS"}}),
            patch("web.views._fetch_jira_board_configuration", return_value={"columns": []}),
            patch("web.views._fetch_jira_board_issues", return_value=[{"key": "OPS-1", "summary": "Fix alerts"}]),
            patch("web.views._build_jira_board_columns", return_value=([{"name": "To Do", "issues": [{"key": "OPS-1", "summary": "Fix alerts"}]}], [])),
            patch("web.views._fetch_jira_issue", return_value={"key": "OPS-1", "summary": "Fix alerts"}),
            patch("web.views._fetch_jira_issue_comments", return_value=[{"id": "1", "body": "Investigating"}]),
            patch("web.views._confluence_space_options", return_value=[{"value": "ENG", "label": "ENG - Engineering"}]),
            patch("web.views._fetch_confluence_pages", return_value=[{"id": "123", "title": "Runbook"}]),
            patch("web.views._fetch_confluence_page", return_value={"id": "123", "title": "Runbook", "body_text": "Checklist"}),
        ):
            jira_listing = self.client.get("/api/jira")
            self.assertEqual(200, jira_listing.status_code)
            jira_payload = jira_listing.get_json() or {}
            self.assertTrue(bool(jira_payload.get("board_columns")))

            jira_issue = self.client.get("/api/jira/issues/OPS-1")
            self.assertEqual(200, jira_issue.status_code)
            issue_payload = jira_issue.get_json() or {}
            self.assertEqual("OPS-1", (issue_payload.get("issue") or {}).get("key"))

            confluence_listing = self.client.get("/api/confluence")
            self.assertEqual(200, confluence_listing.status_code)
            confluence_payload = confluence_listing.get_json() or {}
            self.assertEqual("ENG", confluence_payload.get("space_key"))

    def test_chroma_collections_json(self) -> None:
        with (
            patch("web.views._resolved_chroma_settings", return_value={"host": "llmctl-chromadb", "port": "8000", "ssl": "false"}),
            patch("web.views._chroma_connected", return_value=True),
            patch("web.views._chroma_http_client", return_value=(_FakeChromaClient(), "llmctl-chromadb", 8000, None, None)),
        ):
            listing = self.client.get("/api/chroma/collections?page=1&per_page=20")
            self.assertEqual(200, listing.status_code)
            listing_payload = listing.get_json() or {}
            self.assertTrue(bool(listing_payload.get("collections")))

            detail = self.client.get("/api/chroma/collections/detail?name=docs")
            self.assertEqual(200, detail.status_code)
            detail_payload = detail.get_json() or {}
            self.assertEqual("docs", detail_payload.get("collection_name"))

            delete = self.client.post(
                "/api/chroma/collections/delete",
                json={"collection_name": "docs", "next": "detail"},
            )
            self.assertEqual(200, delete.status_code)
            self.assertTrue(bool((delete.get_json() or {}).get("ok")))

    def test_rag_chat_and_sources_json_routes(self) -> None:
        headers = {"Accept": "application/json"}
        meta = self.client.get("/api/rag/chat", headers=headers)
        self.assertEqual(200, meta.status_code)
        meta_payload = meta.get_json() or {}
        self.assertIn("chat_top_k", meta_payload)

        source_name = f"stage8-source-{uuid.uuid4().hex[:8]}"
        create = self.client.post(
            "/api/rag/sources",
            json={
                "name": source_name,
                "kind": "local",
                "local_path": "/workspace/docs",
                "index_schedule_value": "",
                "index_schedule_unit": "",
                "index_schedule_mode": "fresh",
            },
            headers=headers,
        )
        self.assertEqual(201, create.status_code)
        source_id = int(((create.get_json() or {}).get("source") or {}).get("id") or 0)
        self.assertGreater(source_id, 0)

        listing = self.client.get("/api/rag/sources", headers=headers)
        self.assertEqual(200, listing.status_code)
        listing_payload = listing.get_json() or {}
        self.assertTrue(
            any(int(item.get("id") or 0) == source_id for item in (listing_payload.get("sources") or []))
        )

        detail = self.client.get(f"/api/rag/sources/{source_id}", headers=headers)
        self.assertEqual(200, detail.status_code)
        detail_payload = detail.get_json() or {}
        self.assertEqual(source_id, int((detail_payload.get("source") or {}).get("id") or 0))

        edit = self.client.get(f"/api/rag/sources/{source_id}/edit", headers=headers)
        self.assertEqual(200, edit.status_code)

        update = self.client.post(
            f"/api/rag/sources/{source_id}",
            json={
                "name": f"{source_name}-updated",
                "kind": "local",
                "local_path": "/workspace/docs-updated",
                "index_schedule_value": 1,
                "index_schedule_unit": "days",
                "index_schedule_mode": "delta",
            },
            headers=headers,
        )
        self.assertEqual(200, update.status_code)

        delete = self.client.post(f"/api/rag/sources/{source_id}/delete", json={}, headers=headers)
        self.assertEqual(200, delete.status_code)
        self.assertTrue(bool((delete.get_json() or {}).get("ok")))


if __name__ == "__main__":
    unittest.main()

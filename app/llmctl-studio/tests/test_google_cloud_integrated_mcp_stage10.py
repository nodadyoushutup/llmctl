from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import select

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

import core.db as core_db
from core.config import Config
from core.db import session_scope
from core.integrated_mcp import (
    GOOGLE_CLOUD_SERVICE_ACCOUNT_FILE,
    INTEGRATED_MCP_GOOGLE_CLOUD_KEY,
    INTEGRATED_MCP_GOOGLE_WORKSPACE_KEY,
    sync_integrated_mcp_servers,
)
from core.models import MCP_SERVER_TYPE_INTEGRATED, IntegrationSetting, MCPServer


class GoogleCloudIntegratedMcpStage10Tests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._tmp_path = Path(self._tmp.name)
        self._orig_db_uri = Config.SQLALCHEMY_DATABASE_URI
        self._orig_google_cloud_creds = GOOGLE_CLOUD_SERVICE_ACCOUNT_FILE
        Config.SQLALCHEMY_DATABASE_URI = f"sqlite:///{self._tmp_path / 'stage10.sqlite3'}"
        self._dispose_engine()
        core_db.init_engine(Config.SQLALCHEMY_DATABASE_URI)
        core_db.init_db()

        import core.integrated_mcp as integrated_mcp

        integrated_mcp.GOOGLE_CLOUD_SERVICE_ACCOUNT_FILE = (
            self._tmp_path / "credentials" / "google-cloud-service-account.json"
        )

    def tearDown(self) -> None:
        import core.integrated_mcp as integrated_mcp

        integrated_mcp.GOOGLE_CLOUD_SERVICE_ACCOUNT_FILE = self._orig_google_cloud_creds
        self._dispose_engine()
        Config.SQLALCHEMY_DATABASE_URI = self._orig_db_uri
        self._tmp.cleanup()

    def _dispose_engine(self) -> None:
        if core_db._engine is not None:
            core_db._engine.dispose()
        core_db._engine = None
        core_db.SessionLocal = None

    def _set_integration_settings(self, provider: str, values: dict[str, str]) -> None:
        with session_scope() as session:
            existing = (
                session.execute(
                    select(IntegrationSetting).where(IntegrationSetting.provider == provider)
                )
                .scalars()
                .all()
            )
            existing_map = {row.key: row for row in existing}
            for key, value in values.items():
                cleaned = (value or "").strip()
                if not cleaned:
                    if key in existing_map:
                        session.delete(existing_map[key])
                    continue
                row = existing_map.get(key)
                if row is None:
                    IntegrationSetting.create(
                        session,
                        provider=provider,
                        key=key,
                        value=cleaned,
                    )
                    continue
                row.value = cleaned

    def test_sync_creates_google_cloud_integrated_server(self) -> None:
        service_account = {
            "type": "service_account",
            "project_id": "demo-project",
            "private_key_id": "abc123",
            "private_key": "-----BEGIN PRIVATE KEY-----\\nabc\\n-----END PRIVATE KEY-----\\n",
            "client_email": "svc@demo-project.iam.gserviceaccount.com",
            "client_id": "123",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
        self._set_integration_settings(
            "google_cloud",
            {
                "service_account_json": json.dumps(service_account),
                "google_cloud_project_id": "demo-project",
                "google_cloud_mcp_enabled": "true",
            },
        )

        summary = sync_integrated_mcp_servers()
        self.assertGreaterEqual(summary["created"], 1)

        with session_scope() as session:
            server = (
                session.execute(
                    select(MCPServer).where(
                        MCPServer.server_key == INTEGRATED_MCP_GOOGLE_CLOUD_KEY
                    )
                )
                .scalars()
                .first()
            )
            self.assertIsNotNone(server)
            assert server is not None
            self.assertEqual(MCP_SERVER_TYPE_INTEGRATED, server.server_type)
            self.assertIn('command = "gcloud-mcp"', server.config_json)
            self.assertIn('GOOGLE_CLOUD_PROJECT = "demo-project"', server.config_json)
            self.assertIn(
                'CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE =',
                server.config_json,
            )

        import core.integrated_mcp as integrated_mcp

        self.assertTrue(integrated_mcp.GOOGLE_CLOUD_SERVICE_ACCOUNT_FILE.exists())
        creds_payload = json.loads(
            integrated_mcp.GOOGLE_CLOUD_SERVICE_ACCOUNT_FILE.read_text(encoding="utf-8")
        )
        self.assertEqual(service_account["client_email"], creds_payload["client_email"])

    def test_sync_does_not_create_google_cloud_server_when_disabled(self) -> None:
        self._set_integration_settings(
            "google_cloud",
            {
                "service_account_json": json.dumps(
                    {
                        "type": "service_account",
                        "project_id": "demo-project",
                        "private_key": "-----BEGIN PRIVATE KEY-----\\nabc\\n-----END PRIVATE KEY-----\\n",
                        "client_email": "svc@demo-project.iam.gserviceaccount.com",
                        "token_uri": "https://oauth2.googleapis.com/token",
                    }
                ),
                "google_cloud_mcp_enabled": "false",
            },
        )

        sync_integrated_mcp_servers()

        with session_scope() as session:
            server = (
                session.execute(
                    select(MCPServer).where(
                        MCPServer.server_key == INTEGRATED_MCP_GOOGLE_CLOUD_KEY
                    )
                )
                .scalars()
                .first()
            )
            self.assertIsNone(server)
        import core.integrated_mcp as integrated_mcp

        self.assertFalse(integrated_mcp.GOOGLE_CLOUD_SERVICE_ACCOUNT_FILE.exists())

    def test_sync_does_not_create_google_workspace_server_when_guarded(self) -> None:
        self._set_integration_settings(
            "google_workspace",
            {
                "service_account_json": json.dumps(
                    {
                        "type": "service_account",
                        "project_id": "workspace-project",
                        "private_key": "-----BEGIN PRIVATE KEY-----\\nabc\\n-----END PRIVATE KEY-----\\n",
                        "client_email": "svc@workspace-project.iam.gserviceaccount.com",
                        "token_uri": "https://oauth2.googleapis.com/token",
                    }
                ),
                "workspace_delegated_user_email": "user@example.com",
                "google_workspace_mcp_enabled": "true",
            },
        )

        sync_integrated_mcp_servers()

        with session_scope() as session:
            server = (
                session.execute(
                    select(MCPServer).where(
                        MCPServer.server_key == INTEGRATED_MCP_GOOGLE_WORKSPACE_KEY
                    )
                )
                .scalars()
                .first()
            )
            self.assertIsNone(server)

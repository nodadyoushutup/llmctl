from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as OrmSession, sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

import core.db as core_db
from core.config import Config
from core.db import session_scope
from core.integrated_mcp import (
    GOOGLE_CLOUD_SERVICE_ACCOUNT_FILE,
    GOOGLE_WORKSPACE_IMPERSONATE_USER_FILE,
    GOOGLE_WORKSPACE_SERVICE_ACCOUNT_FILE,
    INTEGRATED_MCP_ATLASSIAN_KEY,
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
        self._orig_k8s_namespace = Config.NODE_EXECUTOR_K8S_NAMESPACE
        self._orig_google_cloud_creds = GOOGLE_CLOUD_SERVICE_ACCOUNT_FILE
        self._orig_google_workspace_creds = GOOGLE_WORKSPACE_SERVICE_ACCOUNT_FILE
        self._orig_google_workspace_impersonate = GOOGLE_WORKSPACE_IMPERSONATE_USER_FILE
        Config.SQLALCHEMY_DATABASE_URI = f"sqlite:///{self._tmp_path / 'stage10.sqlite3'}"
        Config.NODE_EXECUTOR_K8S_NAMESPACE = "llmctl"
        self._dispose_engine()
        core_db._engine = create_engine(Config.SQLALCHEMY_DATABASE_URI, future=True)
        core_db.SessionLocal = sessionmaker(
            bind=core_db._engine,
            expire_on_commit=False,
            class_=OrmSession,
        )
        core_db.init_db()

        import core.integrated_mcp as integrated_mcp

        integrated_mcp.GOOGLE_CLOUD_SERVICE_ACCOUNT_FILE = (
            self._tmp_path / "credentials" / "google-cloud-service-account.json"
        )
        integrated_mcp.GOOGLE_WORKSPACE_SERVICE_ACCOUNT_FILE = (
            self._tmp_path / "credentials" / "google-workspace-service-account.json"
        )
        integrated_mcp.GOOGLE_WORKSPACE_IMPERSONATE_USER_FILE = (
            self._tmp_path / "credentials" / "google-workspace-impersonate-user.txt"
        )

    def tearDown(self) -> None:
        import core.integrated_mcp as integrated_mcp

        integrated_mcp.GOOGLE_CLOUD_SERVICE_ACCOUNT_FILE = self._orig_google_cloud_creds
        integrated_mcp.GOOGLE_WORKSPACE_SERVICE_ACCOUNT_FILE = (
            self._orig_google_workspace_creds
        )
        integrated_mcp.GOOGLE_WORKSPACE_IMPERSONATE_USER_FILE = (
            self._orig_google_workspace_impersonate
        )
        self._dispose_engine()
        Config.SQLALCHEMY_DATABASE_URI = self._orig_db_uri
        Config.NODE_EXECUTOR_K8S_NAMESPACE = self._orig_k8s_namespace
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
            self.assertEqual(
                "http://llmctl-mcp-google-cloud.llmctl.svc.cluster.local:8000/mcp/",
                server.config_json.get("url"),
            )
            self.assertEqual("streamable-http", server.config_json.get("transport"))

        import core.integrated_mcp as integrated_mcp

        self.assertTrue(integrated_mcp.GOOGLE_CLOUD_SERVICE_ACCOUNT_FILE.exists())
        creds_payload = json.loads(
            integrated_mcp.GOOGLE_CLOUD_SERVICE_ACCOUNT_FILE.read_text(encoding="utf-8")
        )
        self.assertEqual(service_account["client_email"], creds_payload["client_email"])

    def test_sync_does_not_create_google_cloud_server_when_credentials_invalid(self) -> None:
        self._set_integration_settings(
            "google_cloud",
            {
                "service_account_json": "{not-json",
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

    def test_sync_creates_google_workspace_integrated_server(self) -> None:
        service_account = {
            "type": "service_account",
            "project_id": "workspace-project",
            "private_key": "-----BEGIN PRIVATE KEY-----\\nabc\\n-----END PRIVATE KEY-----\\n",
            "client_email": "svc@workspace-project.iam.gserviceaccount.com",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
        self._set_integration_settings(
            "google_workspace",
            {
                "service_account_json": json.dumps(service_account),
                "workspace_delegated_user_email": "user@example.com",
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
            self.assertIsNotNone(server)
            assert server is not None
            self.assertEqual(MCP_SERVER_TYPE_INTEGRATED, server.server_type)
            self.assertEqual(
                "http://llmctl-mcp-google-workspace.llmctl.svc.cluster.local:8000/mcp/",
                server.config_json.get("url"),
            )
            self.assertEqual("streamable-http", server.config_json.get("transport"))

        import core.integrated_mcp as integrated_mcp

        self.assertTrue(integrated_mcp.GOOGLE_WORKSPACE_SERVICE_ACCOUNT_FILE.exists())
        creds_payload = json.loads(
            integrated_mcp.GOOGLE_WORKSPACE_SERVICE_ACCOUNT_FILE.read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(service_account["client_email"], creds_payload["client_email"])
        self.assertTrue(integrated_mcp.GOOGLE_WORKSPACE_IMPERSONATE_USER_FILE.exists())
        delegated_user = integrated_mcp.GOOGLE_WORKSPACE_IMPERSONATE_USER_FILE.read_text(
            encoding="utf-8"
        ).strip()
        self.assertEqual("user@example.com", delegated_user)

    def test_sync_rewrites_existing_integrated_row_to_kubernetes_url_idempotently(self) -> None:
        with session_scope() as session:
            MCPServer.create(
                session,
                name="LLMCTL MCP",
                server_key="llmctl-mcp",
                description="legacy",
                config_json={"command": "python3", "args": ["app/llmctl-mcp/run.py"]},
                server_type="custom",
            )

        first_summary = sync_integrated_mcp_servers()
        self.assertGreaterEqual(first_summary["updated"], 1)

        with session_scope() as session:
            server = (
                session.execute(select(MCPServer).where(MCPServer.server_key == "llmctl-mcp"))
                .scalars()
                .one()
            )
            self.assertEqual(MCP_SERVER_TYPE_INTEGRATED, server.server_type)
            self.assertEqual(
                "http://llmctl-mcp.llmctl.svc.cluster.local:9020/mcp/",
                server.config_json.get("url"),
            )
            self.assertEqual("streamable-http", server.config_json.get("transport"))

        second_summary = sync_integrated_mcp_servers()
        self.assertEqual(0, second_summary["updated"])
        self.assertEqual(0, second_summary["created"])
        self.assertEqual(0, second_summary["deleted"])

    def test_sync_normalizes_legacy_jira_key_with_kubernetes_config(self) -> None:
        self._set_integration_settings(
            "jira",
            {
                "site": "https://example.atlassian.net",
                "email": "user@example.com",
                "api_key": "token-value",
            },
        )
        with session_scope() as session:
            MCPServer.create(
                session,
                name="Jira MCP",
                server_key="jira",
                description="legacy jira key",
                config_json={"command": "mcp-atlassian"},
                server_type=MCP_SERVER_TYPE_INTEGRATED,
            )

        sync_integrated_mcp_servers()

        with session_scope() as session:
            legacy = (
                session.execute(select(MCPServer).where(MCPServer.server_key == "jira"))
                .scalars()
                .first()
            )
            self.assertIsNone(legacy)
            atlassian = (
                session.execute(
                    select(MCPServer).where(
                        MCPServer.server_key == INTEGRATED_MCP_ATLASSIAN_KEY
                    )
                )
                .scalars()
                .first()
            )
            self.assertIsNotNone(atlassian)
            assert atlassian is not None
            self.assertEqual("Atlassian MCP", atlassian.name)
            self.assertEqual(
                "http://llmctl-mcp-atlassian.llmctl.svc.cluster.local:8000/mcp/",
                atlassian.config_json.get("url"),
            )
            self.assertEqual("streamable-http", atlassian.config_json.get("transport"))

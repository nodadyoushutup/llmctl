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
from core.models import IntegrationSetting
from services.integrations import (
    GOOGLE_CLOUD_PROVIDER,
    GOOGLE_DRIVE_LEGACY_PROVIDER,
    GOOGLE_WORKSPACE_PROVIDER,
    load_integration_settings,
    migrate_legacy_google_integration_settings,
)


class GoogleIntegrationSplitStage11Tests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._tmp_path = Path(self._tmp.name)
        self._orig_db_uri = Config.SQLALCHEMY_DATABASE_URI
        Config.SQLALCHEMY_DATABASE_URI = f"sqlite:///{self._tmp_path / 'stage11.sqlite3'}"
        self._dispose_engine()
        core_db.init_engine(Config.SQLALCHEMY_DATABASE_URI)
        core_db.init_db()

    def tearDown(self) -> None:
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

    def test_legacy_google_drive_settings_migrate_to_split_providers(self) -> None:
        service_account = {
            "type": "service_account",
            "project_id": "legacy-project",
            "private_key": "-----BEGIN PRIVATE KEY-----\\nabc\\n-----END PRIVATE KEY-----\\n",
            "client_email": "svc@legacy-project.iam.gserviceaccount.com",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
        self._set_integration_settings(
            GOOGLE_DRIVE_LEGACY_PROVIDER,
            {
                "service_account_json": json.dumps(service_account),
                "google_cloud_project_id": "legacy-project",
                "google_cloud_mcp_enabled": "true",
            },
        )

        changed = migrate_legacy_google_integration_settings()
        self.assertTrue(changed)

        cloud = load_integration_settings(GOOGLE_CLOUD_PROVIDER)
        workspace = load_integration_settings(GOOGLE_WORKSPACE_PROVIDER)
        self.assertEqual("legacy-project", cloud.get("google_cloud_project_id"))
        self.assertEqual("true", cloud.get("google_cloud_mcp_enabled"))
        self.assertEqual(cloud.get("service_account_json"), workspace.get("service_account_json"))

        with session_scope() as session:
            legacy_rows = (
                session.execute(
                    select(IntegrationSetting).where(
                        IntegrationSetting.provider == GOOGLE_DRIVE_LEGACY_PROVIDER
                    )
                )
                .scalars()
                .all()
            )
        self.assertEqual([], legacy_rows)

    def test_existing_split_service_accounts_are_not_overwritten(self) -> None:
        self._set_integration_settings(
            GOOGLE_CLOUD_PROVIDER,
            {"service_account_json": '{"client_email":"cloud@example.com"}'},
        )
        self._set_integration_settings(
            GOOGLE_WORKSPACE_PROVIDER,
            {"service_account_json": '{"client_email":"workspace@example.com"}'},
        )
        self._set_integration_settings(
            GOOGLE_DRIVE_LEGACY_PROVIDER,
            {
                "service_account_json": '{"client_email":"legacy@example.com"}',
                "google_cloud_project_id": "legacy-project",
            },
        )

        migrate_legacy_google_integration_settings()

        cloud = load_integration_settings(GOOGLE_CLOUD_PROVIDER)
        workspace = load_integration_settings(GOOGLE_WORKSPACE_PROVIDER)
        self.assertEqual('{"client_email":"cloud@example.com"}', cloud.get("service_account_json"))
        self.assertEqual(
            '{"client_email":"workspace@example.com"}',
            workspace.get("service_account_json"),
        )
        self.assertEqual("legacy-project", cloud.get("google_cloud_project_id"))


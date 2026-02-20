from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session as OrmSession, sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

import core.db as core_db
from core.config import Config
from core.db import session_scope
from core.models import (
    MCP_SERVER_TYPE_INTEGRATED,
    MCPServer,
    Skill,
    SkillFile,
    SkillVersion,
)
from core.seed import seed_defaults


class SeedStage11Tests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp_dir = Path(self._tmp.name)
        self._data_dir = tmp_dir / "data"
        self._workspaces_dir = self._data_dir / "workspaces"
        self._scripts_dir = self._data_dir / "scripts"
        self._attachments_dir = self._data_dir / "attachments"
        self._ssh_keys_dir = self._data_dir / "ssh-keys"
        for directory in (
            self._data_dir,
            self._workspaces_dir,
            self._scripts_dir,
            self._attachments_dir,
            self._ssh_keys_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

        self._db_name = "seed-stage11.sqlite3"
        self._db_path = self._data_dir / self._db_name

        self._orig_data_dir = Config.DATA_DIR
        self._orig_workspaces_dir = Config.WORKSPACES_DIR
        self._orig_scripts_dir = Config.SCRIPTS_DIR
        self._orig_attachments_dir = Config.ATTACHMENTS_DIR
        self._orig_ssh_keys_dir = Config.SSH_KEYS_DIR
        self._orig_db_uri = Config.SQLALCHEMY_DATABASE_URI
        self._orig_k8s_namespace = Config.NODE_EXECUTOR_K8S_NAMESPACE

        Config.DATA_DIR = str(self._data_dir)
        Config.WORKSPACES_DIR = str(self._workspaces_dir)
        Config.SCRIPTS_DIR = str(self._scripts_dir)
        Config.ATTACHMENTS_DIR = str(self._attachments_dir)
        Config.SSH_KEYS_DIR = str(self._ssh_keys_dir)
        Config.SQLALCHEMY_DATABASE_URI = f"sqlite:///{self._db_path}"
        Config.NODE_EXECUTOR_K8S_NAMESPACE = "llmctl"

        self._dispose_engine()
        core_db._engine = create_engine(Config.SQLALCHEMY_DATABASE_URI, future=True)
        core_db.SessionLocal = sessionmaker(
            bind=core_db._engine,
            expire_on_commit=False,
            class_=OrmSession,
        )
        core_db.init_db()

    def tearDown(self) -> None:
        self._dispose_engine()
        Config.DATA_DIR = self._orig_data_dir
        Config.WORKSPACES_DIR = self._orig_workspaces_dir
        Config.SCRIPTS_DIR = self._orig_scripts_dir
        Config.ATTACHMENTS_DIR = self._orig_attachments_dir
        Config.SSH_KEYS_DIR = self._orig_ssh_keys_dir
        Config.SQLALCHEMY_DATABASE_URI = self._orig_db_uri
        Config.NODE_EXECUTOR_K8S_NAMESPACE = self._orig_k8s_namespace
        self._tmp.cleanup()

    def _dispose_engine(self) -> None:
        if core_db._engine is not None:
            core_db._engine.dispose()
        core_db._engine = None
        core_db.SessionLocal = None

    def test_seed_defaults_imports_studio_chromium_skill(self) -> None:
        seed_defaults()
        seed_defaults()

        with session_scope() as session:
            skill = (
                session.execute(
                    select(Skill).where(Skill.name == "chromium-screenshot")
                )
                .scalars()
                .first()
            )
            self.assertIsNotNone(skill)
            assert skill is not None
            self.assertEqual("seed", skill.source_type)
            self.assertEqual(
                "app/llmctl-studio-backend/seed-skills/chromium-screenshot",
                skill.source_ref,
            )

            seed_version = (
                session.execute(
                    select(SkillVersion)
                    .where(
                        SkillVersion.skill_id == skill.id,
                        SkillVersion.version == "1.1.0",
                    )
                )
                .scalars()
                .first()
            )
            self.assertIsNotNone(seed_version)
            assert seed_version is not None

            version_count = session.execute(
                select(func.count())
                .select_from(SkillVersion)
                .where(
                    SkillVersion.skill_id == skill.id,
                    SkillVersion.version == "1.1.0",
                )
            ).scalar_one()
            self.assertEqual(1, int(version_count))

            files = (
                session.execute(
                    select(SkillFile)
                    .where(SkillFile.skill_version_id == seed_version.id)
                    .order_by(SkillFile.path.asc())
                )
                .scalars()
                .all()
            )
            by_path = {entry.path: entry.content for entry in files}
            self.assertIn("SKILL.md", by_path)
            self.assertIn("scripts/capture_screenshot.sh", by_path)
            self.assertIn(
                "${LLMCTL_STUDIO_DATA_DIR:-/app/data}/screenshots",
                by_path["SKILL.md"],
            )
            self.assertIn(
                'default_data_dir="${LLMCTL_STUDIO_DATA_DIR:-/app/data}"',
                by_path["scripts/capture_screenshot.sh"],
            )

    def test_seed_defaults_creates_llmctl_integrated_mcp_server(self) -> None:
        seed_defaults()

        with session_scope() as session:
            server = (
                session.execute(
                    select(MCPServer).where(MCPServer.server_key == "llmctl-mcp")
                )
                .scalars()
                .first()
            )
            self.assertIsNotNone(server)
            assert server is not None
            self.assertEqual(MCP_SERVER_TYPE_INTEGRATED, server.server_type)
            self.assertEqual(
                "http://llmctl-mcp.llmctl.svc.cluster.local:9020/mcp",
                server.config_json.get("url"),
            )
            self.assertEqual("streamable-http", server.config_json.get("transport"))

    def test_seed_defaults_does_not_churn_existing_integrated_url_row(self) -> None:
        config_json = {
            "url": "http://llmctl-mcp.llmctl.svc.cluster.local:9020/mcp",
            "transport": "streamable-http",
        }
        with session_scope() as session:
            MCPServer.create(
                session,
                name="LLMCTL MCP",
                server_key="llmctl-mcp",
                description="System-managed llmctl MCP server hosted in Kubernetes.",
                config_json=dict(config_json),
                server_type=MCP_SERVER_TYPE_INTEGRATED,
            )

        seed_defaults()

        with session_scope() as session:
            server = (
                session.execute(
                    select(MCPServer).where(MCPServer.server_key == "llmctl-mcp")
                )
                .scalars()
                .one()
            )
            self.assertEqual(MCP_SERVER_TYPE_INTEGRATED, server.server_type)
            self.assertEqual(config_json, server.config_json)


if __name__ == "__main__":
    unittest.main()

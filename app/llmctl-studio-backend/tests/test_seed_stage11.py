from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import func, select

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

import core.db as core_db
from core.config import Config
from core.db import session_scope
from core.models import Skill, SkillFile, SkillVersion
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
        self._orig_db_name = Config.DATABASE_FILENAME
        self._orig_db_uri = Config.SQLALCHEMY_DATABASE_URI

        Config.DATA_DIR = str(self._data_dir)
        Config.WORKSPACES_DIR = str(self._workspaces_dir)
        Config.SCRIPTS_DIR = str(self._scripts_dir)
        Config.ATTACHMENTS_DIR = str(self._attachments_dir)
        Config.SSH_KEYS_DIR = str(self._ssh_keys_dir)
        Config.DATABASE_FILENAME = self._db_name
        Config.SQLALCHEMY_DATABASE_URI = f"sqlite:///{self._db_path}"

        self._dispose_engine()
        core_db.init_engine(Config.SQLALCHEMY_DATABASE_URI)
        core_db.init_db()

    def tearDown(self) -> None:
        self._dispose_engine()
        Config.DATA_DIR = self._orig_data_dir
        Config.WORKSPACES_DIR = self._orig_workspaces_dir
        Config.SCRIPTS_DIR = self._orig_scripts_dir
        Config.ATTACHMENTS_DIR = self._orig_attachments_dir
        Config.SSH_KEYS_DIR = self._orig_ssh_keys_dir
        Config.DATABASE_FILENAME = self._orig_db_name
        Config.SQLALCHEMY_DATABASE_URI = self._orig_db_uri
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


if __name__ == "__main__":
    unittest.main()

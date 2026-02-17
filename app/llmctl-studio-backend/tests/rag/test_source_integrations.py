from __future__ import annotations

from datetime import datetime, timezone
import json
import sys
import tempfile
import types
import unittest
import importlib.util
from pathlib import Path
from unittest.mock import call, patch

REPO_ROOT = Path(__file__).resolve().parents[4]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio" / "src"
STUDIO_APP_ROOT = REPO_ROOT / "app" / "llmctl-studio"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))
if str(STUDIO_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(STUDIO_APP_ROOT))

from core.config import Config
from rag.engine.config import build_source_config
from rag.integrations.git_sync import (
    KNOWN_HOSTS_PATH,
    ensure_git_repo,
    git_env,
    git_fetch_and_reset,
    safe_git_url,
)

_HELPERS_SPEC = importlib.util.spec_from_file_location(
    "rag_test_helpers",
    STUDIO_APP_ROOT / "tests" / "rag" / "helpers.py",
)
if _HELPERS_SPEC is None or _HELPERS_SPEC.loader is None:  # pragma: no cover
    raise RuntimeError("Failed to load rag test helpers.")
_HELPERS_MODULE = importlib.util.module_from_spec(_HELPERS_SPEC)
_HELPERS_SPEC.loader.exec_module(_HELPERS_MODULE)
test_config = _HELPERS_MODULE.test_config

try:
    import core.db as core_db
    from rag.repositories.sources import (
        RAGSourceInput,
        create_source,
        get_source,
        update_source_index,
    )

    SQLALCHEMY_AVAILABLE = True
except ModuleNotFoundError:
    core_db = None
    RAGSourceInput = None
    create_source = None
    get_source = None
    update_source_index = None
    SQLALCHEMY_AVAILABLE = False


@unittest.skipUnless(SQLALCHEMY_AVAILABLE, "sqlalchemy is required")
class StudioDbTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp_dir = Path(self._tmp.name)
        self._orig_db_uri = Config.SQLALCHEMY_DATABASE_URI
        self._orig_data_dir = Config.DATA_DIR
        Config.DATA_DIR = str(tmp_dir / "data")
        Path(Config.DATA_DIR).mkdir(parents=True, exist_ok=True)
        Config.SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_dir / 'stage5.sqlite3'}"
        self._reset_engine()

    def tearDown(self) -> None:
        self._dispose_engine()
        Config.DATA_DIR = self._orig_data_dir
        Config.SQLALCHEMY_DATABASE_URI = self._orig_db_uri
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


class SourceRepositoryIntegrationTests(StudioDbTestCase):
    def test_source_creation_maps_collection_and_storage_by_kind(self):
        local_source = create_source(
            RAGSourceInput(name="Local Docs", kind="local", local_path="/tmp/docs")
        )
        github_source = create_source(
            RAGSourceInput(name="Git Repo", kind="github", git_repo="org/repo")
        )
        drive_source = create_source(
            RAGSourceInput(
                name="Drive Folder",
                kind="google_drive",
                drive_folder_id="folder-123",
            )
        )

        self.assertEqual("local_docs_1", local_source.collection)
        self.assertEqual("git_repo_2", github_source.collection)
        self.assertEqual("drive_folder_3", drive_source.collection)

        self.assertEqual("/tmp/docs", local_source.local_path)

        self.assertTrue(github_source.git_dir.endswith("/rag/sources/source-2"))
        self.assertIsNone(github_source.local_path)
        self.assertIsNone(github_source.drive_folder_id)

        self.assertTrue(
            drive_source.local_path.endswith("/rag/sources/source-3-drive")
        )
        self.assertEqual("folder-123", drive_source.drive_folder_id)
        self.assertIsNone(drive_source.git_dir)

    def test_update_source_index_persists_stats(self):
        source = create_source(
            RAGSourceInput(name="Stats Source", kind="local", local_path="/tmp/stats")
        )
        now = datetime.now(timezone.utc)
        indexed_file_types = json.dumps({"markdown": 2, "code": 1}, sort_keys=True)

        update_source_index(
            source.id,
            last_indexed_at=now,
            last_error=None,
            indexed_file_count=3,
            indexed_chunk_count=42,
            indexed_file_types=indexed_file_types,
        )

        refreshed = get_source(source.id)
        assert refreshed is not None
        self.assertEqual(3, refreshed.indexed_file_count)
        self.assertEqual(42, refreshed.indexed_chunk_count)
        self.assertEqual(indexed_file_types, refreshed.indexed_file_types)
        self.assertIsNotNone(refreshed.last_indexed_at)


class SourceConfigAndGitSyncTests(unittest.TestCase):
    def test_build_source_config_local_and_drive_use_local_roots(self):
        base = test_config(Path("/tmp/base"))

        local_source = types.SimpleNamespace(
            kind="local",
            local_path="/tmp/local-source",
            collection="local_collection",
        )
        local_config = build_source_config(base, local_source, {})
        self.assertEqual("local", local_config.rag_mode)
        self.assertEqual(Path("/tmp/local-source"), local_config.repo_root)
        self.assertEqual("local_collection", local_config.collection)

        drive_source = types.SimpleNamespace(
            kind="google_drive",
            local_path="/tmp/drive-source",
            collection="drive_collection",
        )
        drive_config = build_source_config(base, drive_source, {})
        self.assertEqual("local", drive_config.rag_mode)
        self.assertEqual(Path("/tmp/drive-source"), drive_config.repo_root)
        self.assertEqual("drive_collection", drive_config.collection)

    def test_build_source_config_github_supports_pat_and_ssh(self):
        base = test_config(Path("/tmp/base"))
        source = types.SimpleNamespace(
            kind="github",
            git_repo="org/repo",
            git_branch="dev",
            git_dir="/tmp/custom-git-dir",
            collection="github_collection",
        )

        with patch("rag.engine.config.shutil.which", return_value=None):
            pat_config = build_source_config(
                base,
                source,
                {
                    "pat": "pat-secret",
                    "ssh_key_path": "/tmp/id_ed25519",
                },
            )

        self.assertEqual("git", pat_config.rag_mode)
        self.assertEqual(Path("/tmp/custom-git-dir"), pat_config.repo_root)
        self.assertEqual(Path("/tmp/custom-git-dir"), pat_config.git_dir)
        self.assertEqual("dev", pat_config.git_branch)
        self.assertEqual(
            "https://x-access-token:pat-secret@github.com/org/repo.git",
            pat_config.git_url,
        )

        with patch("rag.engine.config.shutil.which", return_value="/usr/bin/ssh"):
            ssh_config = build_source_config(
                base,
                source,
                {
                    "pat": "pat-secret",
                    "ssh_key_path": "/tmp/id_ed25519",
                },
            )
        self.assertEqual("git@github.com:org/repo.git", ssh_config.git_url)

    def test_git_env_builds_ssh_command_and_known_hosts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            key_path = Path(temp_dir) / "id_ed25519"
            key_path.write_text("fake-key", encoding="utf-8")
            config = types.SimpleNamespace(git_ssh_key_path=str(key_path))
            env = git_env(config)

        self.assertEqual("0", env.get("GIT_TERMINAL_PROMPT"))
        ssh_command = env.get("GIT_SSH_COMMAND") or ""
        self.assertIn("BatchMode=yes", ssh_command)
        self.assertIn(f"UserKnownHostsFile={KNOWN_HOSTS_PATH}", ssh_command)
        self.assertIn(f"-i {key_path}", ssh_command)

    def test_git_clone_and_fetch_reset_flows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir) / "repo"
            config = types.SimpleNamespace(
                git_url="https://github.com/org/repo.git",
                git_branch="main",
                repo_root=repo_root,
                git_ssh_key_path=None,
            )

            with patch("rag.integrations.git_sync.run_git") as run_git_mock:
                ensure_git_repo(config)

            run_git_mock.assert_called_once()
            clone_args = run_git_mock.call_args.args[0]
            self.assertEqual("clone", clone_args[0])
            self.assertIn("--single-branch", clone_args)
            self.assertEqual(str(repo_root), clone_args[-1])

            repo_root.mkdir(parents=True, exist_ok=True)
            (repo_root / ".git").mkdir(parents=True, exist_ok=True)

            with patch("rag.integrations.git_sync.run_git") as run_git_mock:
                git_fetch_and_reset(config)

            self.assertEqual(3, run_git_mock.call_count)
            self.assertEqual(
                [
                    call(["fetch", "origin", "main"], cwd=repo_root, env=unittest.mock.ANY),
                    call(
                        ["checkout", "-B", "main", "origin/main"],
                        cwd=repo_root,
                        env=unittest.mock.ANY,
                    ),
                    call(
                        ["reset", "--hard", "origin/main"],
                        cwd=repo_root,
                        env=unittest.mock.ANY,
                    ),
                ],
                run_git_mock.call_args_list,
            )

    def test_safe_git_url_masks_pat(self):
        value = "https://x-access-token:super-secret@github.com/org/repo.git"
        self.assertEqual(
            "https://x-access-token:***@github.com/org/repo.git",
            safe_git_url(value),
        )


if __name__ == "__main__":
    unittest.main()

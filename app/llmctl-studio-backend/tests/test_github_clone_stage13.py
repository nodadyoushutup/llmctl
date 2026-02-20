from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

import services.tasks as studio_tasks


class GitHubCloneStage13Tests(unittest.TestCase):
    def test_clone_uses_ssh_binary_found_via_default_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            dest = temp_path / "task-51"
            key_path = temp_path / "github_ssh_key.pem"
            key_path.write_text("fake-key", encoding="utf-8")
            logs: list[str] = []

            with patch(
                "services.tasks.shutil.which",
                side_effect=[None, "/usr/bin/ssh"],
            ), patch(
                "services.tasks.subprocess.run",
                side_effect=[
                    subprocess.CompletedProcess(
                        ["git", "clone"], 0, "clone-ok", ""
                    ),
                    subprocess.CompletedProcess(
                        ["git", "fetch"], 0, "fetch-ok", ""
                    ),
                ],
            ) as run_mock:
                studio_tasks._clone_github_repo(
                    "nodadyoushutup/example",
                    dest,
                    on_log=logs.append,
                    ssh_key_path=str(key_path),
                )

        clone_call = run_mock.call_args_list[0]
        self.assertEqual(
            [
                "git",
                "clone",
                "git@github.com:nodadyoushutup/example.git",
                str(dest),
            ],
            clone_call.args[0],
        )
        clone_env = clone_call.kwargs.get("env") or {}
        self.assertTrue((clone_env.get("GIT_SSH_COMMAND") or "").startswith("/usr/bin/ssh "))
        self.assertIn("Using uploaded SSH key for GitHub clone.", logs)

    def test_clone_falls_back_to_https_when_ssh_client_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            dest = temp_path / "task-52"
            key_path = temp_path / "github_ssh_key.pem"
            key_path.write_text("fake-key", encoding="utf-8")
            logs: list[str] = []

            with patch(
                "services.tasks.shutil.which",
                side_effect=[None, None],
            ), patch(
                "services.tasks.subprocess.run",
                side_effect=[
                    subprocess.CompletedProcess(
                        ["git", "clone"], 0, "clone-ok", ""
                    ),
                    subprocess.CompletedProcess(
                        ["git", "fetch"], 0, "fetch-ok", ""
                    ),
                ],
            ) as run_mock:
                studio_tasks._clone_github_repo(
                    "nodadyoushutup/example",
                    dest,
                    on_log=logs.append,
                    pat="pat-secret",
                    ssh_key_path=str(key_path),
                )

        clone_call = run_mock.call_args_list[0]
        self.assertEqual(
            [
                "git",
                "clone",
                "https://x-access-token:pat-secret@github.com/nodadyoushutup/example.git",
                str(dest),
            ],
            clone_call.args[0],
        )
        clone_env = clone_call.kwargs.get("env") or {}
        self.assertNotIn("GIT_SSH_COMMAND", clone_env)
        self.assertIn(
            "SSH client not found in runtime; falling back to HTTPS for GitHub clone.",
            logs,
        )

    def test_maybe_checkout_repo_clones_into_task_scoped_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            workspaces_root = temp_path / "workspaces"
            workspaces_root.mkdir(parents=True, exist_ok=True)
            clone_calls: list[tuple[str, Path, str, str]] = []

            def _fake_clone(repo, dest, *, on_log=None, pat="", ssh_key_path=""):
                del on_log
                clone_calls.append((str(repo), Path(dest), str(pat), str(ssh_key_path)))

            with patch.object(
                studio_tasks.Config,
                "WORKSPACES_DIR",
                str(workspaces_root),
            ), patch(
                "services.tasks.load_integration_settings",
                return_value={
                    "repo": "nodadyoushutup/example",
                    "pat": "pat-secret",
                    "ssh_key_path": "",
                },
            ), patch.object(studio_tasks, "_clone_github_repo", side_effect=_fake_clone):
                workspace = studio_tasks._maybe_checkout_repo(77)

        self.assertEqual(workspaces_root / "task-77", workspace)
        self.assertEqual(1, len(clone_calls))
        repo, dest, pat, ssh_key_path = clone_calls[0]
        self.assertEqual("nodadyoushutup/example", repo)
        self.assertEqual(workspaces_root / "task-77", dest)
        self.assertEqual("pat-secret", pat)
        self.assertEqual("", ssh_key_path)

    def test_maybe_checkout_repo_skips_when_repo_not_selected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            workspaces_root = temp_path / "workspaces"
            workspaces_root.mkdir(parents=True, exist_ok=True)
            logs: list[str] = []

            with patch.object(
                studio_tasks.Config,
                "WORKSPACES_DIR",
                str(workspaces_root),
            ), patch(
                "services.tasks.load_integration_settings",
                return_value={
                    "repo": "",
                    "pat": "pat-secret",
                    "ssh_key_path": "",
                },
            ), patch.object(studio_tasks, "_clone_github_repo") as clone_mock:
                workspace = studio_tasks._maybe_checkout_repo(91, on_log=logs.append)

        self.assertIsNone(workspace)
        clone_mock.assert_not_called()
        self.assertIn("GitHub integration has no repo selected; skipping checkout.", logs)

    def test_prepare_task_runtime_home_cleans_previous_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            workspaces_root = temp_path / "workspaces"
            runtime_home = workspaces_root / "task-88-home"
            runtime_home.mkdir(parents=True, exist_ok=True)
            stale_file = runtime_home / "stale.txt"
            stale_file.write_text("stale", encoding="utf-8")

            with patch.object(studio_tasks.Config, "WORKSPACES_DIR", str(workspaces_root)):
                prepared = studio_tasks._prepare_task_runtime_home(88)

            self.assertEqual(runtime_home, prepared)
            self.assertFalse(stale_file.exists())
            self.assertTrue((runtime_home / ".config").is_dir())
            self.assertTrue((runtime_home / ".cache").is_dir())
            self.assertTrue((runtime_home / ".local" / "share").is_dir())


if __name__ == "__main__":
    unittest.main()

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


if __name__ == "__main__":
    unittest.main()

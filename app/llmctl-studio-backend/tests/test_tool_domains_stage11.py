from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault(
    "LLMCTL_STUDIO_DATABASE_URI",
    "postgresql+psycopg://llmctl:llmctl@127.0.0.1:15432/llmctl_studio",
)

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

from services.execution.tool_domains import (  # noqa: E402
    ToolDomainContext,
    run_command_tool,
    run_git_tool,
    run_rag_tool,
    run_workspace_tool,
)


class ToolDomainsStage11Tests(unittest.TestCase):
    def _context(self, root: Path) -> ToolDomainContext:
        return ToolDomainContext(
            workspace_root=root,
            execution_id=11,
            request_id="req-stage11",
            correlation_id="corr-stage11",
        )

    def _run_git(self, root: Path, *command: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *command],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )

    def _init_git_repo(self, root: Path) -> None:
        self._run_git(root, "init")
        self._run_git(root, "config", "user.email", "stage11@example.com")
        self._run_git(root, "config", "user.name", "Stage Eleven")

    def test_workspace_tool_suite_operations(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage11-workspace-") as tmpdir:
            workspace = Path(tmpdir)
            context = self._context(workspace)

            run_workspace_tool(
                context=context,
                operation="mkdir",
                args={"path": "docs/stage11", "parents": True},
            )
            write_outcome = run_workspace_tool(
                context=context,
                operation="write",
                args={
                    "path": "docs/stage11/notes.txt",
                    "content": "hello\n",
                    "create_parents": True,
                },
            )
            self.assertEqual("workspace", write_outcome.output_state.get("tool_domain"))
            self.assertEqual("write", write_outcome.output_state.get("operation"))

            read_outcome = run_workspace_tool(
                context=context,
                operation="read",
                args={"path": "docs/stage11/notes.txt"},
            )
            self.assertEqual(
                "hello\n",
                read_outcome.output_state["result"].get("content"),
            )

            search_outcome = run_workspace_tool(
                context=context,
                operation="search",
                args={"path": "docs", "query": "hello", "max_results": 5},
            )
            self.assertTrue(search_outcome.output_state["result"].get("matches"))

            copy_outcome = run_workspace_tool(
                context=context,
                operation="copy",
                args={
                    "source": "docs/stage11/notes.txt",
                    "target": "docs/stage11/notes-copy.txt",
                },
            )
            self.assertTrue(copy_outcome.output_state["result"].get("copied"))

            move_outcome = run_workspace_tool(
                context=context,
                operation="move",
                args={
                    "source": "docs/stage11/notes-copy.txt",
                    "target": "docs/stage11/notes-moved.txt",
                },
            )
            self.assertTrue(move_outcome.output_state["result"].get("moved"))

            chmod_outcome = run_workspace_tool(
                context=context,
                operation="chmod",
                args={"path": "docs/stage11/notes-moved.txt", "mode": "640"},
            )
            self.assertEqual("0o640", chmod_outcome.output_state["result"].get("mode"))

            self._init_git_repo(workspace)
            patch_text = "\n".join(
                [
                    "--- docs/stage11/notes.txt",
                    "+++ docs/stage11/notes.txt",
                    "@@ -1 +1 @@",
                    "-hello",
                    "+hello world",
                    "",
                ]
            )
            patch_outcome = run_workspace_tool(
                context=context,
                operation="apply_patch",
                args={"patch": patch_text},
            )
            self.assertTrue(patch_outcome.output_state["result"].get("applied"))

            patched = (workspace / "docs/stage11/notes.txt").read_text(encoding="utf-8")
            self.assertEqual("hello world\n", patched)

            list_outcome = run_workspace_tool(
                context=context,
                operation="list",
                args={"path": "docs/stage11", "recursive": True},
            )
            entries = list_outcome.output_state["result"].get("entries") or []
            self.assertTrue(any(item.get("path") == "docs/stage11/notes.txt" for item in entries))

            delete_outcome = run_workspace_tool(
                context=context,
                operation="delete",
                args={"path": "docs/stage11/notes-moved.txt"},
            )
            self.assertTrue(delete_outcome.output_state["result"].get("deleted"))

    def test_git_tool_suite_operations(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage11-git-local-") as local_tmpdir:
            with tempfile.TemporaryDirectory(prefix="stage11-git-remote-") as remote_tmpdir:
                local_repo = Path(local_tmpdir)
                remote_repo = Path(remote_tmpdir) / "remote.git"
                self._run_git(Path(remote_tmpdir), "init", "--bare", str(remote_repo))
                self._init_git_repo(local_repo)
                self._run_git(local_repo, "remote", "add", "origin", str(remote_repo))
                (local_repo / "README.md").write_text("base\n", encoding="utf-8")
                self._run_git(local_repo, "add", "README.md")
                self._run_git(local_repo, "commit", "-m", "Initial commit")
                default_branch = (
                    self._run_git(local_repo, "rev-parse", "--abbrev-ref", "HEAD")
                    .stdout.strip()
                )

                context = self._context(local_repo)

                switch_feature = run_git_tool(
                    context=context,
                    operation="branch",
                    args={"action": "switch", "name": "feature/stage11", "create": True},
                )
                self.assertEqual(
                    "switch",
                    switch_feature.output_state["result"].get("action"),
                )

                (local_repo / "README.md").write_text("base\nfeature\n", encoding="utf-8")
                commit_outcome = run_git_tool(
                    context=context,
                    operation="commit",
                    args={"message": "Feature commit", "add_all": True},
                )
                self.assertTrue(commit_outcome.output_state["result"].get("committed"))
                feature_commit = str(commit_outcome.output_state["result"].get("commit") or "")
                self.assertTrue(feature_commit)

                rebase_outcome = run_git_tool(
                    context=context,
                    operation="rebase_noninteractive",
                    args={"upstream": default_branch},
                )
                self.assertEqual(
                    default_branch,
                    rebase_outcome.output_state["result"].get("upstream"),
                )

                run_git_tool(
                    context=context,
                    operation="branch",
                    args={"action": "switch", "name": default_branch},
                )
                cherry_pick_outcome = run_git_tool(
                    context=context,
                    operation="cherry_pick",
                    args={"commit": feature_commit},
                )
                self.assertEqual(
                    feature_commit,
                    cherry_pick_outcome.output_state["result"].get("commit"),
                )

                tag_outcome = run_git_tool(
                    context=context,
                    operation="tag",
                    args={"action": "create", "name": "v0.0.11"},
                )
                self.assertEqual("v0.0.11", tag_outcome.output_state["result"].get("tag"))

                push_outcome = run_git_tool(
                    context=context,
                    operation="push",
                    args={
                        "remote": "origin",
                        "branch": default_branch,
                        "set_upstream": True,
                    },
                )
                self.assertEqual("origin", push_outcome.output_state["result"].get("remote"))

                pr_outcome = run_git_tool(
                    context=context,
                    operation="pull_request",
                    args={
                        "base": default_branch,
                        "head": "feature/stage11",
                        "title": "Stage 11 PR",
                        "body": "non-interactive PR operation",
                    },
                )
                self.assertIn("created", pr_outcome.output_state["result"])

                branch_list_outcome = run_git_tool(
                    context=context,
                    operation="branch",
                    args={"action": "list"},
                )
                branches = branch_list_outcome.output_state["result"].get("branches") or []
                self.assertIn("feature/stage11", branches)

                tag_list_outcome = run_git_tool(
                    context=context,
                    operation="tag",
                    args={"action": "list"},
                )
                tags = tag_list_outcome.output_state["result"].get("tags") or []
                self.assertIn("v0.0.11", tags)

    def test_command_tool_suite_operations(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage11-command-") as tmpdir:
            workspace = Path(tmpdir)
            context = self._context(workspace)

            run_outcome = run_command_tool(
                context=context,
                operation="run",
                args={"command": ["bash", "-lc", "echo stage11-run"], "timeout_seconds": 10},
            )
            self.assertEqual(0, run_outcome.output_state["result"].get("exit_code"))
            self.assertIn("stage11-run", run_outcome.output_state["result"].get("stdout") or "")
            artifacts = run_outcome.output_state["result"].get("artifacts") or {}
            self.assertIn("stdout", artifacts)
            self.assertIn("stderr", artifacts)

            start_outcome = run_command_tool(
                context=context,
                operation="session_start",
                args={"command": ["bash", "-lc", "cat"]},
            )
            session_id = str(start_outcome.output_state["result"].get("session_id") or "")
            self.assertTrue(session_id)

            run_command_tool(
                context=context,
                operation="session_write",
                args={"session_id": session_id, "input": "hello-session", "append_newline": True},
            )
            read_outcome = run_command_tool(
                context=context,
                operation="session_read",
                args={"session_id": session_id, "wait_ms": 200, "max_bytes": 4096},
            )
            self.assertIn(
                "hello-session",
                read_outcome.output_state["result"].get("output") or "",
            )
            stop_outcome = run_command_tool(
                context=context,
                operation="session_stop",
                args={"session_id": session_id},
            )
            self.assertTrue(stop_outcome.output_state["result"].get("stopped"))

            background_start = run_command_tool(
                context=context,
                operation="background_start",
                args={"command": ["bash", "-lc", "sleep 0.2; echo stage11-background"]},
            )
            job_id = str(background_start.output_state["result"].get("job_id") or "")
            self.assertTrue(job_id)

            status_outcome = run_command_tool(
                context=context,
                operation="background_status",
                args={"job_id": job_id},
            )
            self.assertIn("running", status_outcome.output_state["result"])

            wait_outcome = run_command_tool(
                context=context,
                operation="background_wait",
                args={"job_id": job_id, "timeout_seconds": 10},
            )
            self.assertEqual(0, wait_outcome.output_state["result"].get("exit_code"))
            self.assertIn(
                "stage11-background",
                wait_outcome.output_state["result"].get("stdout_tail") or "",
            )

            stop_outcome = run_command_tool(
                context=context,
                operation="background_stop",
                args={"job_id": job_id},
            )
            self.assertIn("stopped", stop_outcome.output_state["result"])

            limits_outcome = run_command_tool(
                context=context,
                operation="resource_limits",
                args={},
            )
            limits_result = limits_outcome.output_state["result"]
            self.assertGreaterEqual(int(limits_result.get("cpu_count") or 0), 1)
            self.assertIn("limits", limits_result)

    def test_rag_tool_suite_contracts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage11-rag-") as tmpdir:
            context = self._context(Path(tmpdir))

            with patch(
                "services.execution.tool_domains.run_index_for_collections",
                return_value={
                    "mode": "fresh_index",
                    "collections": ["docs"],
                    "source_count": 1,
                    "total_files": 4,
                    "total_chunks": 18,
                    "sources": [{"source_id": 1, "source_name": "Docs", "collection": "docs"}],
                },
            ) as index_mock:
                index_outcome = run_rag_tool(
                    context=context,
                    operation="index",
                    args={
                        "mode": "full",
                        "collections": ["docs"],
                        "model_provider": "codex",
                    },
                )
                self.assertEqual("rag", index_outcome.output_state.get("tool_domain"))
                self.assertEqual("index", index_outcome.output_state.get("operation"))
                self.assertEqual(
                    "fresh_index",
                    index_outcome.output_state["result"].get("mode"),
                )
                index_mock.assert_called_once()
                self.assertEqual("fresh_index", index_mock.call_args.kwargs.get("mode"))

            with patch(
                "services.execution.tool_domains.execute_query_contract",
                return_value={
                    "mode": "query",
                    "answer": "hello",
                    "collections": ["docs"],
                    "retrieval_context": [{"text": "chunk"}],
                    "retrieval_stats": {"retrieved_count": 1},
                    "citation_records": [{"path": "docs/readme.md"}],
                    "synthesis_error": None,
                },
            ) as query_mock:
                query_outcome = run_rag_tool(
                    context=context,
                    operation="query",
                    args={
                        "question": "What changed?",
                        "collections": ["docs"],
                        "top_k": 3,
                    },
                )
                self.assertEqual("query", query_outcome.output_state["result"].get("mode"))
                self.assertEqual("hello", query_outcome.output_state["result"].get("answer"))
                query_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()

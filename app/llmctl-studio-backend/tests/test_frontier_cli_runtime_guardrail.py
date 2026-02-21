from __future__ import annotations

import importlib.util
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = REPO_ROOT / "scripts" / "audit" / "frontier_cli_runtime_guardrail.py"
SPEC = importlib.util.spec_from_file_location("frontier_cli_runtime_guardrail", MODULE_PATH)
assert SPEC and SPEC.loader
frontier_cli_runtime_guardrail = importlib.util.module_from_spec(SPEC)
sys.modules["frontier_cli_runtime_guardrail"] = frontier_cli_runtime_guardrail
SPEC.loader.exec_module(frontier_cli_runtime_guardrail)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")


class FrontierCliRuntimeGuardrailTests(unittest.TestCase):
    def test_passes_when_frontier_providers_are_not_used_as_cli_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_file = root / "app" / "llmctl-studio-backend" / "src" / "services" / "tasks.py"
            _write_text(
                runtime_file,
                """
                import subprocess

                FRONTIER_PROVIDERS = ["codex", "gemini", "claude"]

                def run_safe():
                    return subprocess.run(["echo", "ok"], check=False)
                """,
            )
            failures = frontier_cli_runtime_guardrail.run_guardrail(
                repo_root=root,
                paths=[str(runtime_file)],
            )
            self.assertEqual([], failures)

    def test_fails_for_literal_subprocess_cli_invocation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_file = root / "app" / "llmctl-studio-backend" / "src" / "services" / "tasks.py"
            _write_text(
                runtime_file,
                """
                import subprocess

                def run_bad():
                    return subprocess.run(["codex", "exec"], check=False)
                """,
            )
            failures = frontier_cli_runtime_guardrail.run_guardrail(
                repo_root=root,
                paths=[str(runtime_file)],
            )
            self.assertTrue(any("forbidden frontier CLI binary 'codex'" in failure for failure in failures))

    def test_fails_for_command_variable_subprocess_cli_invocation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_file = root / "app" / "llmctl-studio-backend" / "src" / "services" / "execution" / "agent_runtime.py"
            _write_text(
                runtime_file,
                """
                import subprocess

                def run_bad():
                    command = ["gemini", "run"]
                    return subprocess.Popen(command)
                """,
            )
            failures = frontier_cli_runtime_guardrail.run_guardrail(
                repo_root=root,
                paths=[str(runtime_file)],
            )
            self.assertTrue(any("forbidden frontier CLI binary 'gemini'" in failure for failure in failures))

    def test_fails_for_helper_command_keyword_cli_invocation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_file = root / "app" / "llmctl-studio-backend" / "src" / "services" / "execution" / "agent_runtime.py"
            _write_text(
                runtime_file,
                """
                def _run_subprocess(*, command):
                    return command

                def run_bad():
                    return _run_subprocess(command=["claude", "chat"])
                """,
            )
            failures = frontier_cli_runtime_guardrail.run_guardrail(
                repo_root=root,
                paths=[str(runtime_file)],
            )
            self.assertTrue(any("forbidden frontier CLI binary 'claude'" in failure for failure in failures))


if __name__ == "__main__":
    unittest.main()

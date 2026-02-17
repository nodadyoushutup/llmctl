from __future__ import annotations

import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

from services.instruction_adapters.base import (
    InstructionAdapterDescriptor,
    InstructionAdapterMaterializationResult,
)
from services.instructions.compiler import (
    InstructionCompileInput,
    compile_instruction_package,
)
from services.instructions.package import materialize_instruction_package
from services import tasks as studio_tasks


class _FakeNativeAdapter:
    def __init__(self) -> None:
        self.materialize_calls = 0

    def materialize(self, compiled, *, workspace, runtime_home, codex_home=None):
        del compiled, workspace, runtime_home, codex_home
        self.materialize_calls += 1
        raise RuntimeError("native write failed")

    def fallback_payload(self, compiled):
        del compiled
        return {"instructions_markdown": "fallback instructions"}

    def describe(self):
        return InstructionAdapterDescriptor(
            provider="codex",
            adapter="fake_native",
            native_filename="AGENTS.md",
            supports_native=True,
        )


class AgentRoleMarkdownStage5Tests(unittest.TestCase):
    def _compiled(self, *, provider: str = "codex", role_markdown: str = "# Role\n\nrole\n"):
        return compile_instruction_package(
            InstructionCompileInput(
                run_mode="task",
                provider=provider,
                role_markdown=role_markdown,
                agent_markdown="# Agent\n\nagent\n",
                source_ids={"agent_id": 1, "role_id": 2},
                source_versions={},
                generated_at="2026-02-16T00:00:00+00:00",
            )
        )

    def test_instruction_flag_defaults_and_overrides(self) -> None:
        defaults: dict[str, str] = {}
        self.assertTrue(studio_tasks._instruction_native_enabled("codex", defaults))
        self.assertTrue(studio_tasks._instruction_native_enabled("gemini", defaults))
        self.assertTrue(studio_tasks._instruction_native_enabled("claude", defaults))
        self.assertFalse(studio_tasks._instruction_native_enabled("vllm_local", defaults))
        self.assertTrue(studio_tasks._instruction_fallback_enabled("codex", defaults))

        overrides = {
            "instruction_native_enabled_codex": "false",
            "instruction_fallback_enabled_codex": "false",
        }
        self.assertFalse(studio_tasks._instruction_native_enabled("codex", overrides))
        self.assertFalse(studio_tasks._instruction_fallback_enabled("codex", overrides))

    def test_native_disabled_uses_fallback_without_materialize(self) -> None:
        fake = _FakeNativeAdapter()
        compiled = self._compiled()
        logs: list[str] = []

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workspace = root / "workspace"
            runtime_home = root / "home"
            workspace.mkdir(parents=True, exist_ok=True)
            runtime_home.mkdir(parents=True, exist_ok=True)
            with patch.object(studio_tasks, "resolve_instruction_adapter", return_value=fake):
                payload, mode, adapter_name, materialized_paths = (
                    studio_tasks._apply_instruction_adapter_policy(
                        provider="codex",
                        llm_settings={
                            "instruction_native_enabled_codex": "false",
                            "instruction_fallback_enabled_codex": "true",
                        },
                        compiled_instruction_package=compiled,
                        configured_agent_markdown_filename=None,
                        workspace=workspace,
                        runtime_home=runtime_home,
                        codex_home=None,
                        payload="hello",
                        task_kind="task",
                        on_log=logs.append,
                    )
                )
        self.assertEqual(0, fake.materialize_calls)
        self.assertEqual("fallback", mode)
        self.assertEqual("fake_native", adapter_name)
        self.assertEqual([], materialized_paths)
        self.assertIn("Runtime instructions (fallback context):", payload)
        self.assertTrue(any("native=off" in line for line in logs))

    def test_native_failure_respects_fallback_flag(self) -> None:
        fake = _FakeNativeAdapter()
        compiled = self._compiled()
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workspace = root / "workspace"
            runtime_home = root / "home"
            workspace.mkdir(parents=True, exist_ok=True)
            runtime_home.mkdir(parents=True, exist_ok=True)
            with patch.object(studio_tasks, "resolve_instruction_adapter", return_value=fake):
                payload, mode, _adapter_name, _paths = (
                    studio_tasks._apply_instruction_adapter_policy(
                        provider="codex",
                        llm_settings={"instruction_fallback_enabled_codex": "true"},
                        compiled_instruction_package=compiled,
                        configured_agent_markdown_filename=None,
                        workspace=workspace,
                        runtime_home=runtime_home,
                        codex_home=None,
                        payload="hello",
                        task_kind="task",
                        on_log=lambda _line: None,
                    )
                )
                self.assertEqual("fallback", mode)
                self.assertIn("Runtime instructions (fallback context):", payload)

                with self.assertRaises(RuntimeError):
                    studio_tasks._apply_instruction_adapter_policy(
                        provider="codex",
                        llm_settings={"instruction_fallback_enabled_codex": "false"},
                        compiled_instruction_package=compiled,
                        configured_agent_markdown_filename=None,
                        workspace=workspace,
                        runtime_home=runtime_home,
                        codex_home=None,
                        payload="hello",
                        task_kind="task",
                        on_log=lambda _line: None,
                    )

    def test_materialized_path_validation_blocks_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workspace = root / "workspace"
            runtime_home = root / "home"
            codex_home = root / "codex"
            workspace.mkdir(parents=True, exist_ok=True)
            runtime_home.mkdir(parents=True, exist_ok=True)
            codex_home.mkdir(parents=True, exist_ok=True)
            outside = root / "outside.txt"
            outside.write_text("x", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                studio_tasks._validate_instruction_materialized_paths(
                    paths=[str(outside)],
                    workspace=workspace,
                    runtime_home=runtime_home,
                    codex_home=codex_home,
                )

    def test_reference_risk_logging_observes_at_file_tokens(self) -> None:
        compiled = self._compiled(role_markdown="# Role\n\nUse @../secrets.txt when needed.\n")
        logs: list[str] = []
        studio_tasks._log_instruction_reference_risk(
            compiled_instruction_package=compiled,
            on_log=logs.append,
        )
        self.assertTrue(any("safety note" in line for line in logs))

    def test_parallel_materialization_100_runs_has_no_cross_run_leakage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workspace_root = root / "workspaces"
            home_root = root / "homes"
            workspace_root.mkdir(parents=True, exist_ok=True)
            home_root.mkdir(parents=True, exist_ok=True)

            def _worker(index: int) -> tuple[str, str, list[str], list[str]]:
                marker = f"marker-{index}"
                compiled = compile_instruction_package(
                    InstructionCompileInput(
                        run_mode="task",
                        provider="codex",
                        role_markdown=f"# Role\n\n{marker}\n",
                        agent_markdown=f"# Agent\n\n{marker}\n",
                        source_ids={"agent_id": index, "role_id": index},
                        source_versions={},
                        generated_at="2026-02-16T00:00:00+00:00",
                    )
                )
                workspace = workspace_root / f"run-{index}"
                runtime_home = home_root / f"run-{index}"
                codex_home = runtime_home / ".codex"
                workspace.mkdir(parents=True, exist_ok=True)
                runtime_home.mkdir(parents=True, exist_ok=True)
                codex_home.mkdir(parents=True, exist_ok=True)
                materialize_instruction_package(workspace, compiled)
                _payload, mode, _adapter_name, paths = studio_tasks._apply_instruction_adapter_policy(
                    provider="codex",
                    llm_settings={},
                    compiled_instruction_package=compiled,
                    configured_agent_markdown_filename=None,
                    workspace=workspace,
                    runtime_home=runtime_home,
                    codex_home=codex_home,
                    payload="hello",
                    task_kind="task",
                    on_log=lambda _line: None,
                )
                agents_md = (workspace / "AGENTS.md").read_text(encoding="utf-8")
                workspace_dirs = sorted(
                    path.name for path in workspace_root.iterdir() if path.is_dir()
                )
                home_dirs = sorted(path.name for path in home_root.iterdir() if path.is_dir())
                return marker, mode, paths, [agents_md, ",".join(workspace_dirs + home_dirs)]

            with ThreadPoolExecutor(max_workers=20) as executor:
                results = list(executor.map(_worker, range(100)))

            self.assertEqual(100, len(results))
            for marker, mode, paths, payload in results:
                agents_md = payload[0]
                self.assertEqual("native", mode)
                self.assertIn(marker, agents_md)
                self.assertTrue(any(str(path).endswith("/AGENTS.md") for path in paths))


if __name__ == "__main__":
    unittest.main()

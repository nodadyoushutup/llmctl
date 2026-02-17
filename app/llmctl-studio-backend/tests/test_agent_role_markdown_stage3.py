from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

from services.instruction_adapters import (
    FRONTIER_INSTRUCTION_FILENAMES,
    NON_FRONTIER_DEFAULT_INSTRUCTION_FILENAME,
    resolve_instruction_adapter,
    validate_agent_markdown_filename,
)
from services.instructions.compiler import (
    INSTRUCTIONS_FILENAME,
    InstructionCompileInput,
    compile_instruction_package,
)


class AgentRoleMarkdownStage3Tests(unittest.TestCase):
    def _compiled(self, provider: str):
        return compile_instruction_package(
            InstructionCompileInput(
                run_mode="task",
                provider=provider,
                role_markdown="# Role\n\nRole text.\n",
                agent_markdown="# Agent\n\nAgent text.\n",
                source_ids={"agent_id": 1, "role_id": 2},
                source_versions={},
                generated_at="2026-02-16T00:00:00+00:00",
            )
        )

    def test_validate_agent_markdown_filename(self) -> None:
        self.assertEqual(validate_agent_markdown_filename("AGENT.md"), "AGENT.md")
        with self.assertRaisesRegex(ValueError, "cannot start"):
            validate_agent_markdown_filename(".hidden.md")
        with self.assertRaisesRegex(ValueError, "must end with '.md'"):
            validate_agent_markdown_filename("AGENT.txt")
        with self.assertRaisesRegex(ValueError, "only contain"):
            validate_agent_markdown_filename("agent name.md")

    def test_frontier_adapters_write_provider_native_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workspace = root / "workspace"
            runtime_home = root / "home"
            workspace.mkdir(parents=True, exist_ok=True)
            runtime_home.mkdir(parents=True, exist_ok=True)
            for provider, expected_name in FRONTIER_INSTRUCTION_FILENAMES.items():
                compiled = self._compiled(provider)
                adapter = resolve_instruction_adapter(provider)
                result = adapter.materialize(
                    compiled,
                    workspace=workspace,
                    runtime_home=runtime_home,
                    codex_home=None,
                )
                self.assertEqual(result.mode, "native")
                materialized_path = workspace / expected_name
                self.assertIn(str(materialized_path), result.materialized_paths)
                self.assertTrue(materialized_path.is_file())
                self.assertEqual(
                    materialized_path.read_text(encoding="utf-8"),
                    compiled.artifacts[INSTRUCTIONS_FILENAME],
                )

    def test_vllm_adapter_materializes_configured_filename_and_fallback(self) -> None:
        compiled = self._compiled("vllm_local")
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workspace = root / "workspace"
            runtime_home = root / "home"
            workspace.mkdir(parents=True, exist_ok=True)
            runtime_home.mkdir(parents=True, exist_ok=True)
            adapter = resolve_instruction_adapter(
                "vllm_local",
                agent_markdown_filename="CUSTOM_AGENT.md",
            )
            result = adapter.materialize(
                compiled,
                workspace=workspace,
                runtime_home=runtime_home,
                codex_home=None,
            )
            self.assertEqual(result.mode, "fallback")
            target_path = workspace / "CUSTOM_AGENT.md"
            self.assertIn(str(target_path), result.materialized_paths)
            self.assertTrue(target_path.is_file())
            fallback_payload = adapter.fallback_payload(compiled)
            self.assertIsInstance(fallback_payload, dict)
            self.assertEqual(
                fallback_payload.get("materialized_filename"), "CUSTOM_AGENT.md"
            )
            self.assertIn("instructions_markdown", fallback_payload)

    def test_vllm_defaults_filename_when_not_configured(self) -> None:
        adapter = resolve_instruction_adapter("vllm_remote")
        descriptor = adapter.describe()
        self.assertEqual(
            descriptor.native_filename,
            NON_FRONTIER_DEFAULT_INSTRUCTION_FILENAME,
        )


if __name__ == "__main__":
    unittest.main()

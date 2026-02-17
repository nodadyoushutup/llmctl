from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

from services.instructions.compiler import (
    AGENT_FILENAME,
    INSTRUCTIONS_FILENAME,
    MANIFEST_FILENAME,
    PRIORITIES_FILENAME,
    ROLE_FILENAME,
    InstructionCompileInput,
    compile_instruction_package,
)
from services.instructions.package import (
    INSTRUCTIONS_SUBDIR,
    materialize_instruction_package,
)


class AgentRoleMarkdownStage2Tests(unittest.TestCase):
    def test_compile_non_autorun_omits_priorities_and_preserves_merge_order(self) -> None:
        compiled = compile_instruction_package(
            InstructionCompileInput(
                run_mode="task",
                provider="codex",
                role_markdown="# Role\n\nRole text.\n",
                agent_markdown="# Agent\n\nAgent text.\n",
                priorities=("first", "second"),
                runtime_overrides=("Override text",),
                source_ids={"agent_id": 1, "role_id": 2},
                source_versions={},
                generated_at="2026-02-16T00:00:00+00:00",
            )
        )

        self.assertIn(ROLE_FILENAME, compiled.artifacts)
        self.assertIn(AGENT_FILENAME, compiled.artifacts)
        self.assertIn(INSTRUCTIONS_FILENAME, compiled.artifacts)
        self.assertNotIn(PRIORITIES_FILENAME, compiled.artifacts)
        instructions = compiled.artifacts[INSTRUCTIONS_FILENAME]
        role_index = instructions.find("## Role Source")
        agent_index = instructions.find("## Agent Source")
        override_index = instructions.find("## Runtime Overrides")
        self.assertTrue(role_index >= 0)
        self.assertTrue(agent_index > role_index)
        self.assertTrue(override_index > agent_index)

    def test_compile_autorun_includes_priorities(self) -> None:
        compiled = compile_instruction_package(
            InstructionCompileInput(
                run_mode="autorun",
                provider="codex",
                role_markdown="# Role\n\nRole text.\n",
                agent_markdown="# Agent\n\nAgent text.\n",
                priorities=("Priority one", "Priority two"),
                runtime_overrides=tuple(),
                source_ids={"agent_id": 1, "role_id": 2},
                source_versions={},
                generated_at="2026-02-16T00:00:00+00:00",
            )
        )

        self.assertIn(PRIORITIES_FILENAME, compiled.artifacts)
        priorities = compiled.artifacts[PRIORITIES_FILENAME]
        self.assertIn("## Priority 1", priorities)
        self.assertIn("## Priority 2", priorities)
        self.assertTrue(compiled.manifest.get("includes_priorities"))

    def test_manifest_hash_is_content_stable(self) -> None:
        first = compile_instruction_package(
            InstructionCompileInput(
                run_mode="task",
                provider="gemini",
                role_markdown="# Role\n\nRole text.\n",
                agent_markdown="# Agent\n\nAgent text.\n",
                runtime_overrides=("Override",),
                source_ids={"agent_id": 1, "role_id": 2},
                source_versions={},
                generated_at="2026-02-16T00:00:00+00:00",
            )
        )
        second = compile_instruction_package(
            InstructionCompileInput(
                run_mode="task",
                provider="gemini",
                role_markdown="# Role\n\nRole text.\n",
                agent_markdown="# Agent\n\nAgent text.\n",
                runtime_overrides=("Override",),
                source_ids={"agent_id": 1, "role_id": 2},
                source_versions={},
                generated_at="2026-02-16T01:00:00+00:00",
            )
        )
        self.assertEqual(first.manifest_hash, second.manifest_hash)
        self.assertNotEqual(first.manifest["generated_at"], second.manifest["generated_at"])

    def test_package_materialization_writes_run_local_artifacts(self) -> None:
        compiled = compile_instruction_package(
            InstructionCompileInput(
                run_mode="task",
                provider="claude",
                role_markdown="# Role\n\nRole text.\n",
                agent_markdown="# Agent\n\nAgent text.\n",
                runtime_overrides=tuple(),
                source_ids={"agent_id": 9, "role_id": 8},
                source_versions={},
                generated_at="2026-02-16T00:00:00+00:00",
            )
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir) / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            materialized = materialize_instruction_package(workspace, compiled)

            expected_dir = workspace / INSTRUCTIONS_SUBDIR
            self.assertEqual(expected_dir, materialized.package_dir)
            self.assertTrue((expected_dir / ROLE_FILENAME).is_file())
            self.assertTrue((expected_dir / AGENT_FILENAME).is_file())
            self.assertTrue((expected_dir / INSTRUCTIONS_FILENAME).is_file())
            self.assertTrue((expected_dir / MANIFEST_FILENAME).is_file())
            self.assertEqual(compiled.manifest_hash, materialized.manifest_hash)


if __name__ == "__main__":
    unittest.main()


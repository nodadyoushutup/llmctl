from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session as OrmSession, sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

import core.db as core_db
from core.config import Config
from core.db import session_scope
from core.models import Agent, AgentPriority, AgentTask, LLMModel, Role, Run
from services import tasks as studio_tasks
from services.instructions.compiler import (
    INSTRUCTIONS_FILENAME,
    PRIORITIES_FILENAME,
    InstructionCompileInput,
    compile_instruction_package,
)
from services.integrations import save_integration_settings


class StudioDbTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp_dir = Path(self._tmp.name)
        self._orig_db_uri = Config.SQLALCHEMY_DATABASE_URI
        self._orig_workspaces_dir = Config.WORKSPACES_DIR
        self._orig_data_dir = Config.DATA_DIR
        Config.SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_dir / 'agent-role-stage6.sqlite3'}"
        Config.WORKSPACES_DIR = str(tmp_dir / "workspaces")
        Config.DATA_DIR = str(tmp_dir / "data")
        Path(Config.WORKSPACES_DIR).mkdir(parents=True, exist_ok=True)
        Path(Config.DATA_DIR).mkdir(parents=True, exist_ok=True)
        self._reset_engine()

    def tearDown(self) -> None:
        self._dispose_engine()
        Config.SQLALCHEMY_DATABASE_URI = self._orig_db_uri
        Config.WORKSPACES_DIR = self._orig_workspaces_dir
        Config.DATA_DIR = self._orig_data_dir
        self._tmp.cleanup()

    def _dispose_engine(self) -> None:
        if core_db._engine is not None:
            core_db._engine.dispose()
        core_db._engine = None
        core_db.SessionLocal = None

    def _reset_engine(self) -> None:
        self._dispose_engine()
        core_db._engine = create_engine(Config.SQLALCHEMY_DATABASE_URI, future=True)
        core_db.SessionLocal = sessionmaker(
            bind=core_db._engine,
            expire_on_commit=False,
            class_=OrmSession,
        )
        core_db.init_db()


class AgentRoleMarkdownStage6Tests(StudioDbTestCase):
    def _create_agent_task_fixture(
        self,
        *,
        provider: str,
        autorun: bool,
        model_config: dict[str, object] | None = None,
    ) -> int:
        with session_scope() as session:
            role = Role.create(
                session,
                name=f"Stage6 Role {provider}",
                description="Role description",
                details_json=json.dumps({"purpose": "stage6"}),
            )
            agent = Agent.create(
                session,
                name=f"Stage6 Agent {provider}",
                description="Agent description",
                role_id=role.id,
                prompt_json=json.dumps({"prompt": "Act deterministically."}),
                prompt_text=None,
                autonomous_prompt="Always stay on task.",
            )
            AgentPriority.create(
                session,
                agent_id=agent.id,
                position=2,
                content="Second priority",
            )
            AgentPriority.create(
                session,
                agent_id=agent.id,
                position=1,
                content="First priority",
            )
            model = LLMModel.create(
                session,
                name=f"stage6-{provider}",
                provider=provider,
                config_json=json.dumps(model_config or {}, sort_keys=True),
            )
            run_id: int | None = None
            if autorun:
                run = Run.create(
                    session,
                    name=f"stage6-run-{provider}",
                    agent_id=agent.id,
                    status="running",
                )
                run_id = run.id
            task = AgentTask.create(
                session,
                agent_id=agent.id,
                run_id=run_id,
                model_id=model.id,
                status="queued",
                prompt="",
            )
            return int(task.id)

    def _create_quick_node_fixture(self, *, provider: str = "codex") -> int:
        with session_scope() as session:
            model = LLMModel.create(
                session,
                name=f"stage6-{provider}-quick",
                provider=provider,
                config_json="{}",
            )
            task = AgentTask.create(
                session,
                agent_id=None,
                run_id=None,
                model_id=model.id,
                status="queued",
                kind="quick",
                prompt="Return one sentence.",
            )
            return int(task.id)

    def test_compiler_normalization_and_manifest_content_are_deterministic(self) -> None:
        first = compile_instruction_package(
            InstructionCompileInput(
                run_mode="autorun",
                provider="codex",
                role_markdown="# Role\r\n\r\nRole line with spaces   \r\n",
                agent_markdown="# Agent\r\n\r\nAgent line\t \r\n",
                priorities=(" Priority one\r\n", "Priority two   \r\n"),
                runtime_overrides=("Override one\r\n\r\n", "\r\n"),
                source_ids={"agent_id": 1, "role_id": 2},
                source_versions={"agent_version": "a1", "role_version": "r1"},
                generated_at="2026-02-16T00:00:00+00:00",
            )
        )
        second = compile_instruction_package(
            InstructionCompileInput(
                run_mode="autorun",
                provider="codex",
                role_markdown="# Role\n\nRole line with spaces\n",
                agent_markdown="# Agent\n\nAgent line\n",
                priorities=("Priority one", "Priority two"),
                runtime_overrides=("Override one",),
                source_ids={"agent_id": 1, "role_id": 2},
                source_versions={"agent_version": "a1", "role_version": "r1"},
                generated_at="2026-02-16T01:00:00+00:00",
            )
        )

        self.assertEqual(first.manifest_hash, second.manifest_hash)
        self.assertIn(PRIORITIES_FILENAME, first.artifacts)
        for content in first.artifacts.values():
            self.assertNotIn("\r", content)
            self.assertTrue(content.endswith("\n"))
            self.assertNotRegex(content, r"[ \t]+\n")

        manifest = first.manifest
        self.assertEqual("sha256", manifest.get("hash_algorithm"))
        self.assertEqual(first.manifest_hash, manifest.get("manifest_hash"))
        self.assertTrue(bool(manifest.get("includes_priorities")))
        self.assertIn("artifacts", manifest)
        artifact_manifest = manifest["artifacts"]
        assert isinstance(artifact_manifest, dict)
        self.assertIn(INSTRUCTIONS_FILENAME, artifact_manifest)
        instructions_metadata = artifact_manifest[INSTRUCTIONS_FILENAME]
        assert isinstance(instructions_metadata, dict)
        self.assertTrue(int(instructions_metadata.get("size_bytes") or 0) > 0)
        self.assertTrue(bool(instructions_metadata.get("sha256")))

    def test_frontier_runtime_file_matrix_matches_run_modes(self) -> None:
        provider_file_map = {
            "codex": "AGENTS.md",
            "gemini": "GEMINI.md",
            "claude": "CLAUDE.md",
        }
        for provider, file_name in provider_file_map.items():
            for autorun in (False, True):
                task_id = self._create_agent_task_fixture(
                    provider=provider,
                    autorun=autorun,
                )
                captured: dict[str, str] = {}

                def _fake_run_llm(
                    call_provider: str,
                    prompt: str,
                    *,
                    mcp_configs,
                    model_config,
                    on_update,
                    on_log,
                    cwd,
                    env,
                    _file_name=file_name,
                ) -> subprocess.CompletedProcess[str]:
                    del prompt, mcp_configs, model_config, on_update, on_log, env
                    workspace = Path(str(cwd))
                    captured["provider"] = call_provider
                    captured["compiled_markdown"] = (workspace / _file_name).read_text(
                        encoding="utf-8"
                    )
                    return subprocess.CompletedProcess(
                        args=[call_provider],
                        returncode=0,
                        stdout="ok",
                        stderr="",
                    )

                with patch.object(studio_tasks, "_run_llm", side_effect=_fake_run_llm):
                    studio_tasks._execute_agent_task(
                        task_id,
                        celery_task_id=f"stage6-{provider}-{autorun}",
                    )

                compiled_markdown = captured.get("compiled_markdown") or ""
                self.assertIn("## Role Source", compiled_markdown)
                self.assertIn("## Agent Source", compiled_markdown)
                if autorun:
                    self.assertIn("## Priorities Source", compiled_markdown)
                else:
                    self.assertNotIn("## Priorities Source", compiled_markdown)

                with session_scope() as session:
                    task = session.get(AgentTask, task_id)
                    assert task is not None
                    self.assertEqual("succeeded", task.status)
                    self.assertEqual("native", task.instruction_adapter_mode)
                    self.assertTrue((task.resolved_instruction_manifest_hash or "").strip())
                    paths = json.loads(task.instruction_materialized_paths_json or "[]")
                    self.assertTrue(
                        any(str(path).endswith(f"/{file_name}") for path in paths)
                    )

    def test_vllm_runtime_materializes_custom_filename_and_injects_fallback(self) -> None:
        save_integration_settings(
            "llm",
            {
                "provider_enabled_codex": "true",
                "provider_enabled_gemini": "true",
                "provider_enabled_claude": "true",
                "provider_enabled_vllm_local": "true",
            },
        )
        task_id = self._create_agent_task_fixture(
            provider="vllm_local",
            autorun=False,
            model_config={"agent_markdown_filename": "CUSTOM_AGENT.md"},
        )
        captured: dict[str, str] = {}

        def _fake_run_llm(
            provider: str,
            prompt: str,
            *,
            mcp_configs,
            model_config,
            on_update,
            on_log,
            cwd,
            env,
        ) -> subprocess.CompletedProcess[str]:
            del provider, mcp_configs, model_config, on_update, on_log, env
            workspace = Path(str(cwd))
            captured["custom_md"] = (workspace / "CUSTOM_AGENT.md").read_text(
                encoding="utf-8"
            )
            captured["prompt"] = prompt
            return subprocess.CompletedProcess(
                args=["vllm_local"],
                returncode=0,
                stdout="ok",
                stderr="",
            )

        with patch.object(studio_tasks, "_run_llm", side_effect=_fake_run_llm):
            studio_tasks._execute_agent_task(task_id, celery_task_id="stage6-vllm")

        custom_md = captured.get("custom_md") or ""
        self.assertIn("## Role Source", custom_md)
        self.assertIn("## Agent Source", custom_md)
        self.assertNotIn("## Priorities Source", custom_md)
        prompt_payload = json.loads(captured.get("prompt") or "{}")
        self.assertIsInstance(prompt_payload, dict)
        task_context = prompt_payload.get("task_context")
        self.assertIsInstance(task_context, dict)
        instructions = (
            task_context.get("instructions")
            if isinstance(task_context, dict)
            else None
        )
        self.assertIsInstance(instructions, dict)
        instructions_payload = instructions if isinstance(instructions, dict) else {}
        self.assertEqual(
            "CUSTOM_AGENT.md",
            instructions_payload.get("materialized_filename"),
        )
        self.assertTrue(
            (str(instructions_payload.get("instructions_markdown") or "").strip())
        )

        with session_scope() as session:
            task = session.get(AgentTask, task_id)
            assert task is not None
            self.assertEqual("succeeded", task.status)
            self.assertEqual("fallback", task.instruction_adapter_mode)
            self.assertTrue((task.resolved_instruction_manifest_hash or "").strip())
            paths = json.loads(task.instruction_materialized_paths_json or "[]")
            self.assertTrue(any(str(path).endswith("/CUSTOM_AGENT.md") for path in paths))

    def test_codex_fallback_path_preserves_prompt_envelope_when_native_disabled(self) -> None:
        save_integration_settings(
            "llm",
            {
                "instruction_native_enabled_codex": "false",
                "instruction_fallback_enabled_codex": "true",
            },
        )
        task_id = self._create_agent_task_fixture(provider="codex", autorun=False)
        captured: dict[str, str] = {}

        def _fake_run_llm(
            provider: str,
            prompt: str,
            *,
            mcp_configs,
            model_config,
            on_update,
            on_log,
            cwd,
            env,
        ) -> subprocess.CompletedProcess[str]:
            del provider, mcp_configs, model_config, on_update, on_log, env
            workspace = Path(str(cwd))
            captured["native_file_exists"] = "1" if (workspace / "AGENTS.md").exists() else "0"
            captured["prompt"] = prompt
            return subprocess.CompletedProcess(
                args=["codex"],
                returncode=0,
                stdout="ok",
                stderr="",
            )

        with patch.object(studio_tasks, "_run_llm", side_effect=_fake_run_llm):
            studio_tasks._execute_agent_task(task_id, celery_task_id="stage6-fallback")

        self.assertEqual("0", captured.get("native_file_exists"))
        prompt_payload = json.loads(captured.get("prompt") or "{}")
        self.assertIsInstance(prompt_payload, dict)
        task_context = prompt_payload.get("task_context")
        self.assertIsInstance(task_context, dict)
        instructions = (
            task_context.get("instructions")
            if isinstance(task_context, dict)
            else None
        )
        self.assertIsInstance(instructions, dict)
        instructions_payload = instructions if isinstance(instructions, dict) else {}
        self.assertTrue(
            (str(instructions_payload.get("instructions_markdown") or "").strip())
        )

        with session_scope() as session:
            task = session.get(AgentTask, task_id)
            assert task is not None
            self.assertEqual("succeeded", task.status)
            self.assertEqual("fallback", task.instruction_adapter_mode)
            paths = json.loads(task.instruction_materialized_paths_json or "[]")
            self.assertFalse(any(str(path).endswith("/AGENTS.md") for path in paths))

    def test_quick_node_without_agent_keeps_instruction_snapshot_fields_empty(self) -> None:
        task_id = self._create_quick_node_fixture(provider="codex")

        def _fake_run_llm(
            provider: str,
            prompt: str,
            *,
            mcp_configs,
            model_config,
            on_update,
            on_log,
            cwd,
            env,
        ) -> subprocess.CompletedProcess[str]:
            del provider, prompt, mcp_configs, model_config, on_update, on_log, cwd, env
            return subprocess.CompletedProcess(
                args=["codex"],
                returncode=0,
                stdout="ok",
                stderr="",
            )

        with patch.object(studio_tasks, "_run_llm", side_effect=_fake_run_llm):
            studio_tasks._execute_agent_task(task_id, celery_task_id="stage6-quick")

        with session_scope() as session:
            task = session.get(AgentTask, task_id)
            assert task is not None
            self.assertEqual("succeeded", task.status)
            self.assertIsNone(task.resolved_role_id)
            self.assertIsNone(task.resolved_role_version)
            self.assertIsNone(task.resolved_agent_id)
            self.assertIsNone(task.resolved_agent_version)
            self.assertIsNone(task.resolved_instruction_manifest_hash)
            self.assertIsNone(task.instruction_adapter_mode)
            self.assertIsNone(task.instruction_materialized_paths_json)


if __name__ == "__main__":
    unittest.main()

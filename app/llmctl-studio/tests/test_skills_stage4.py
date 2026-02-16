from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

import core.db as core_db
from core.config import Config
from core.db import session_scope
from core.models import (
    Agent,
    FLOWCHART_NODE_TYPE_TASK,
    Flowchart,
    FlowchartNode,
    LLMModel,
    Skill,
    SkillFile,
    SkillVersion,
    agent_skill_bindings,
)
from services import tasks as studio_tasks


class StudioDbTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp_dir = Path(self._tmp.name)
        self._orig_db_uri = Config.SQLALCHEMY_DATABASE_URI
        self._orig_workspaces_dir = Config.WORKSPACES_DIR
        self._orig_data_dir = Config.DATA_DIR
        Config.SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_dir / 'skills-stage4.sqlite3'}"
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
        core_db.init_engine(Config.SQLALCHEMY_DATABASE_URI)
        core_db.init_db()


class SkillsStage4Tests(StudioDbTestCase):
    def _create_task_node(
        self,
        provider: str,
        *,
        with_skill: bool,
        include_skill_md: bool = True,
    ) -> tuple[int, int, str | None]:
        with session_scope() as session:
            agent = Agent.create(
                session,
                name=f"{provider}-agent",
                prompt_json=json.dumps({"instruction": "Run stage 4 skill tests."}),
            )
            model = LLMModel.create(
                session,
                name=f"{provider}-model",
                provider=provider,
                config_json="{}",
            )
            flowchart = Flowchart.create(session, name=f"{provider}-flowchart")
            node_config = {"agent_id": agent.id} if with_skill else {}
            node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_TASK,
                model_id=model.id,
                config_json=json.dumps(node_config, sort_keys=True),
            )

            if not with_skill:
                return node.id, model.id, None

            skill_slug = f"skill-stage4-{provider}"
            skill = Skill.create(
                session,
                name=skill_slug,
                display_name=f"Skill Stage4 {provider.title()}",
                description="Stage 4 skill",
                status="active",
                source_type="ui",
            )
            version = SkillVersion.create(
                session,
                skill_id=skill.id,
                version="1.0.0",
                manifest_hash="",
            )
            if include_skill_md:
                skill_md = (
                    "---\n"
                    f"name: {skill_slug}\n"
                    f"display_name: Skill Stage4 {provider.title()}\n"
                    "description: Stage 4 skill\n"
                    "version: 1.0.0\n"
                    "status: active\n"
                    "---\n\n"
                    "# Skill Stage4\n"
                )
                SkillFile.create(
                    session,
                    skill_version_id=version.id,
                    path="SKILL.md",
                    content=skill_md,
                    checksum="",
                    size_bytes=len(skill_md.encode("utf-8")),
                )
            SkillFile.create(
                session,
                skill_version_id=version.id,
                path="scripts/run.sh",
                content="echo stage4\n",
                checksum="",
                size_bytes=len("echo stage4\n".encode("utf-8")),
            )
            session.execute(
                agent_skill_bindings.insert().values(
                    agent_id=agent.id,
                    skill_id=skill.id,
                    position=1,
                )
            )
            return node.id, model.id, skill_slug

    def _execute_node(
        self,
        *,
        node_id: int,
        model_id: int,
        provider: str,
        node_config: dict[str, object] | None = None,
        capture: dict[str, object] | None = None,
    ) -> dict[str, object]:
        node_payload = {"task_prompt": "Run stage 4 test prompt."}
        if node_config:
            node_payload.update(node_config)
        recorded = capture if capture is not None else {}

        def _fake_run_llm(
            provider_name: str,
            prompt: str,
            *,
            mcp_configs,
            model_config,
            on_update,
            on_log,
            cwd,
            env,
        ) -> subprocess.CompletedProcess[str]:
            del mcp_configs, model_config, on_update, on_log
            recorded["provider"] = provider_name
            recorded["prompt"] = prompt
            recorded["cwd"] = str(cwd) if cwd is not None else ""
            recorded["home"] = str((env or {}).get("HOME") or "")
            return subprocess.CompletedProcess(
                args=[provider_name],
                returncode=0,
                stdout=json.dumps({"result": "ok"}),
                stderr="",
            )

        with patch.object(studio_tasks, "_run_llm", side_effect=_fake_run_llm):
            output_state, routing_state = studio_tasks._execute_flowchart_task_node(
                node_id=node_id,
                node_ref_id=None,
                node_config=node_payload,
                input_context={"flowchart": {"id": 1}},
                execution_id=321,
                execution_task_id=None,
                enabled_providers={provider},
                default_model_id=model_id,
            )
        self.assertEqual({}, routing_state)
        return output_state

    def test_workspace_skill_projection_materialized_read_only(self) -> None:
        node_id, model_id, skill_slug = self._create_task_node("codex", with_skill=True)
        assert skill_slug is not None
        captured: dict[str, object] = {}

        def _fake_run_llm(
            provider_name: str,
            prompt: str,
            *,
            mcp_configs,
            model_config,
            on_update,
            on_log,
            cwd,
            env,
        ) -> subprocess.CompletedProcess[str]:
            del prompt, mcp_configs, model_config, on_update, on_log, env
            cwd_path = Path(str(cwd))
            skill_md = cwd_path / ".llmctl" / "skills" / skill_slug / "SKILL.md"
            captured["provider"] = provider_name
            captured["skill_md_exists"] = skill_md.exists()
            captured["skill_md_mode"] = (skill_md.stat().st_mode & 0o777) if skill_md.exists() else 0
            return subprocess.CompletedProcess(
                args=[provider_name],
                returncode=0,
                stdout=json.dumps({"result": "ok"}),
                stderr="",
            )

        with patch.object(studio_tasks, "_run_llm", side_effect=_fake_run_llm):
            output_state, _routing_state = studio_tasks._execute_flowchart_task_node(
                node_id=node_id,
                node_ref_id=None,
                node_config={"task_prompt": "Check workspace skill projection."},
                input_context={"flowchart": {"id": 1}},
                execution_id=321,
                execution_task_id=None,
                enabled_providers={"codex"},
                default_model_id=model_id,
            )

        self.assertEqual("native", output_state.get("skill_adapter_mode"))
        materialized_paths = output_state.get("skill_materialized_paths") or []
        self.assertTrue(
            any(f"/.llmctl/skills/{skill_slug}" in str(path) for path in materialized_paths)
        )
        self.assertTrue(captured.get("skill_md_exists"))
        self.assertEqual(0, int(captured.get("skill_md_mode") or 0) & 0o222)

    def test_policy_downgrades_to_fallback_when_materialization_fails(self) -> None:
        node_id, model_id, _skill_slug = self._create_task_node("codex", with_skill=True)
        captured: dict[str, object] = {}

        with patch.object(
            studio_tasks,
            "materialize_skill_set",
            side_effect=RuntimeError("adapter materialization failed"),
        ):
            output_state = self._execute_node(
                node_id=node_id,
                model_id=model_id,
                provider="codex",
                node_config={"allow_skill_adapter_fallback": True},
                capture=captured,
            )

        self.assertEqual("fallback", output_state.get("skill_adapter_mode"))
        self.assertEqual("prompt_fallback", output_state.get("skill_adapter"))
        payload = json.loads(str(captured.get("prompt") or "{}"))
        task_context = payload.get("task_context") if isinstance(payload, dict) else None
        self.assertIsInstance(task_context, dict)
        self.assertTrue((task_context or {}).get("skills"))

    def test_invalid_skill_package_fails_fast(self) -> None:
        node_id, model_id, _skill_slug = self._create_task_node(
            "codex",
            with_skill=True,
            include_skill_md=False,
        )
        with self.assertRaises(ValueError) as ctx:
            studio_tasks._execute_flowchart_task_node(
                node_id=node_id,
                node_ref_id=None,
                node_config={"task_prompt": "Should fail on missing SKILL.md"},
                input_context={"flowchart": {"id": 1}},
                execution_id=321,
                execution_task_id=None,
                enabled_providers={"codex"},
                default_model_id=model_id,
            )
        self.assertIn("Skill resolution failed", str(ctx.exception))

    def test_gemini_without_workspace_uses_run_local_home_for_cwd(self) -> None:
        node_id, model_id, _skill_slug = self._create_task_node(
            "gemini",
            with_skill=False,
        )
        captured: dict[str, object] = {}
        output_state = self._execute_node(
            node_id=node_id,
            model_id=model_id,
            provider="gemini",
            capture=captured,
        )
        self.assertIsNone(output_state.get("skill_adapter_mode"))
        self.assertIn("task-321-home", str(captured.get("home") or ""))
        self.assertIn("task-321-home", str(captured.get("cwd") or ""))

    def test_optional_transform_uses_run_local_home(self) -> None:
        captured: dict[str, object] = {}

        def _fake_run_llm(
            provider_name: str,
            prompt: str,
            *,
            mcp_configs,
            model_config,
            on_update,
            on_log,
            cwd,
            env,
        ) -> subprocess.CompletedProcess[str]:
            del prompt, mcp_configs, model_config, on_update, on_log
            captured["provider"] = provider_name
            captured["cwd"] = str(cwd) if cwd is not None else ""
            captured["home"] = str((env or {}).get("HOME") or "")
            return subprocess.CompletedProcess(
                args=[provider_name],
                returncode=0,
                stdout="{}",
                stderr="",
            )

        with patch.object(studio_tasks, "_run_llm", side_effect=_fake_run_llm):
            result = studio_tasks._execute_optional_llm_transform(
                prompt="{}",
                model=SimpleNamespace(provider="gemini", config_json="{}"),
                enabled_providers={"gemini"},
                mcp_configs={},
            )

        self.assertIsInstance(result, dict)
        self.assertIn("llmctl-flowchart-transform-home-", str(captured.get("cwd") or ""))
        self.assertEqual(captured.get("cwd"), captured.get("home"))


if __name__ == "__main__":
    unittest.main()

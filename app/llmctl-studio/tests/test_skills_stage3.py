from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
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
    AgentTask,
    FLOWCHART_NODE_TYPE_TASK,
    Flowchart,
    FlowchartNode,
    LLMModel,
    Skill,
    SkillFile,
    SkillVersion,
    agent_skill_bindings,
    flowchart_node_skills,
)
from services import tasks as studio_tasks
from services.skill_adapters import resolve_agent_skills


class StudioDbTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp_dir = Path(self._tmp.name)
        self._orig_db_uri = Config.SQLALCHEMY_DATABASE_URI
        self._orig_workspaces_dir = Config.WORKSPACES_DIR
        self._orig_data_dir = Config.DATA_DIR
        Config.SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_dir / 'skills-stage3.sqlite3'}"
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


class SkillsStage3Tests(StudioDbTestCase):
    def _create_task_node_with_skill(self, provider: str) -> tuple[int, int, int, int, int]:
        with session_scope() as session:
            agent = Agent.create(
                session,
                name=f"{provider}-agent",
                prompt_json=json.dumps({"instruction": "Run stage 3 skill tests."}),
            )
            model = LLMModel.create(
                session,
                name=f"{provider}-model",
                provider=provider,
                config_json="{}",
            )
            flowchart = Flowchart.create(session, name=f"{provider}-flowchart")
            node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_TASK,
                model_id=model.id,
                config_json=json.dumps({"agent_id": agent.id}, sort_keys=True),
            )

            skill_slug = f"skill-alpha-{provider}"
            skill = Skill.create(
                session,
                name=skill_slug,
                display_name=f"Skill Alpha {provider.title()}",
                description="Primary alpha skill",
                status="active",
                source_type="ui",
            )
            version = SkillVersion.create(
                session,
                skill_id=skill.id,
                version="1.0.0",
                manifest_hash="",
            )
            skill_md = (
                "---\n"
                f"name: {skill_slug}\n"
                f"display_name: Skill Alpha {provider.title()}\n"
                "description: Primary alpha skill\n"
                "version: 1.0.0\n"
                "status: active\n"
                "---\n\n"
                "# Skill Alpha\n"
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
                content="echo alpha\n",
                checksum="",
                size_bytes=len("echo alpha\n".encode("utf-8")),
            )
            session.execute(
                agent_skill_bindings.insert().values(
                    agent_id=agent.id,
                    skill_id=skill.id,
                    position=1,
                )
            )
            return node.id, model.id, skill.id, version.id, agent.id

    def _execute_node(self, provider: str) -> tuple[dict[str, object], dict[str, str]]:
        node_id, model_id, _skill_id, _version_id, agent_id = self._create_task_node_with_skill(
            provider
        )
        captured: dict[str, str] = {}

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
            captured["provider"] = provider_name
            captured["prompt"] = prompt
            captured["cwd"] = str(cwd) if cwd is not None else ""
            captured["home"] = str((env or {}).get("HOME") or "")
            captured["codex_home"] = str((env or {}).get("CODEX_HOME") or "")
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
                node_config={
                    "agent_id": agent_id,
                    "task_prompt": "Summarize this skill usage.",
                },
                input_context={"flowchart": {"id": 1}},
                execution_id=321,
                execution_task_id=None,
                enabled_providers={provider},
                default_model_id=model_id,
            )
        self.assertEqual({}, routing_state)
        return output_state, captured

    def test_provider_native_adapter_modes_and_home_isolation(self) -> None:
        expected_adapters = {
            "codex": "codex",
            "gemini": "gemini_cli",
            "claude": "claude_code",
        }
        for provider, adapter in expected_adapters.items():
            output_state, captured = self._execute_node(provider)
            self.assertEqual("native", output_state.get("skill_adapter_mode"))
            self.assertEqual(adapter, output_state.get("skill_adapter"))
            self.assertTrue(output_state.get("resolved_skill_ids"))
            self.assertTrue(output_state.get("resolved_skill_versions"))
            self.assertTrue(output_state.get("resolved_skill_manifest_hash"))
            self.assertIn("task-321-home", captured.get("home") or "")
            self.assertIn("task-321", captured.get("cwd") or "")
            if provider == "codex":
                self.assertIn("codex-homes", captured.get("codex_home") or "")

    def test_fallback_adapter_injects_skill_context_for_non_native_provider(self) -> None:
        output_state, captured = self._execute_node("vllm_local")
        self.assertEqual("fallback", output_state.get("skill_adapter_mode"))
        self.assertEqual("prompt_fallback", output_state.get("skill_adapter"))

        payload = json.loads(captured.get("prompt") or "{}")
        task_context = payload.get("task_context") if isinstance(payload, dict) else None
        self.assertIsInstance(task_context, dict)
        skills_payload = task_context.get("skills") if isinstance(task_context, dict) else None
        self.assertIsInstance(skills_payload, list)
        self.assertTrue(skills_payload)

    def test_resolver_orders_by_position_then_skill_name(self) -> None:
        with session_scope() as session:
            agent = Agent.create(
                session,
                name="order-agent",
                prompt_json=json.dumps({"instruction": "Resolver order test."}),
            )
            model = LLMModel.create(
                session,
                name="order-model",
                provider="codex",
                config_json="{}",
            )
            flowchart = Flowchart.create(session, name="order-flowchart")
            node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_TASK,
                model_id=model.id,
                config_json=json.dumps({"agent_id": agent.id}, sort_keys=True),
            )

            def _add_skill(name: str, position: int | None) -> None:
                skill = Skill.create(
                    session,
                    name=name,
                    display_name=name.title(),
                    description=f"{name} description",
                    status="active",
                    source_type="ui",
                )
                version = SkillVersion.create(
                    session,
                    skill_id=skill.id,
                    version="1.0.0",
                    manifest_hash="",
                )
                SkillFile.create(
                    session,
                    skill_version_id=version.id,
                    path="SKILL.md",
                    content=(
                        "---\n"
                        f"name: {name}\n"
                        f"display_name: {name.title()}\n"
                        "description: resolver order test\n"
                        "version: 1.0.0\n"
                        "status: active\n"
                        "---\n"
                    ),
                    checksum="",
                    size_bytes=0,
                )
                session.execute(
                    agent_skill_bindings.insert().values(
                        agent_id=agent.id,
                        skill_id=skill.id,
                        position=position,
                    )
                )

            _add_skill("zeta", 2)
            _add_skill("alpha", 1)
            _add_skill("beta", 1)

            resolved = resolve_agent_skills(session, agent.id)
            self.assertEqual(
                ["alpha", "beta", "zeta"],
                [entry.name for entry in resolved.skills],
            )

    def test_legacy_node_skill_bindings_are_ignored_with_warning(self) -> None:
        with session_scope() as session:
            agent = Agent.create(
                session,
                name="legacy-skill-agent",
                prompt_json=json.dumps({"instruction": "Ignore legacy node skills."}),
            )
            model = LLMModel.create(
                session,
                name="legacy-model",
                provider="codex",
                config_json="{}",
            )
            flowchart = Flowchart.create(session, name="legacy-flowchart")
            node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_TASK,
                model_id=model.id,
                config_json=json.dumps({"agent_id": agent.id}, sort_keys=True),
            )

            agent_skill = Skill.create(
                session,
                name="agent-skill",
                display_name="Agent Skill",
                description="Agent-bound skill",
                status="active",
                source_type="ui",
            )
            agent_version = SkillVersion.create(
                session,
                skill_id=agent_skill.id,
                version="1.0.0",
                manifest_hash="",
            )
            SkillFile.create(
                session,
                skill_version_id=agent_version.id,
                path="SKILL.md",
                content=(
                    "---\n"
                    "name: agent-skill\n"
                    "display_name: Agent Skill\n"
                    "description: Agent-bound skill\n"
                    "version: 1.0.0\n"
                    "status: active\n"
                    "---\n"
                ),
                checksum="",
                size_bytes=0,
            )
            session.execute(
                agent_skill_bindings.insert().values(
                    agent_id=agent.id,
                    skill_id=agent_skill.id,
                    position=1,
                )
            )

            legacy_skill = Skill.create(
                session,
                name="legacy-node-skill",
                display_name="Legacy Node Skill",
                description="Legacy node-bound skill",
                status="active",
                source_type="ui",
            )
            legacy_version = SkillVersion.create(
                session,
                skill_id=legacy_skill.id,
                version="1.0.0",
                manifest_hash="",
            )
            SkillFile.create(
                session,
                skill_version_id=legacy_version.id,
                path="SKILL.md",
                content=(
                    "---\n"
                    "name: legacy-node-skill\n"
                    "display_name: Legacy Node Skill\n"
                    "description: Legacy node-bound skill\n"
                    "version: 1.0.0\n"
                    "status: active\n"
                    "---\n"
                ),
                checksum="",
                size_bytes=0,
            )
            session.execute(
                flowchart_node_skills.insert().values(
                    flowchart_node_id=node.id,
                    skill_id=legacy_skill.id,
                    position=1,
                )
            )
            node_id = node.id
            model_id = model.id
            agent_skill_id = agent_skill.id
            selected_agent_id = agent.id

        with patch.object(
            studio_tasks,
            "_run_llm",
            return_value=subprocess.CompletedProcess(
                args=["codex"],
                returncode=0,
                stdout=json.dumps({"result": "ok"}),
                stderr="",
            ),
        ), self.assertLogs("services.tasks", level="WARNING") as logs:
            output_state, routing_state = studio_tasks._execute_flowchart_task_node(
                node_id=node_id,
                node_ref_id=None,
                node_config={
                    "agent_id": selected_agent_id,
                    "task_prompt": "Ignore legacy node skills.",
                },
                input_context={"flowchart": {"id": 1}},
                execution_id=321,
                execution_task_id=None,
                enabled_providers={"codex"},
                default_model_id=model_id,
            )

        self.assertEqual({}, routing_state)
        self.assertEqual([agent_skill_id], output_state.get("resolved_skill_ids"))
        self.assertTrue(
            any("legacy node-level skill binding" in message for message in logs.output)
        )

    def test_agent_task_runtime_uses_agent_skills_and_persists_snapshot(self) -> None:
        with session_scope() as session:
            agent = Agent.create(
                session,
                name="agent-task-skill-agent",
                prompt_json=json.dumps({"instruction": "Use agent-bound skills."}),
            )
            model = LLMModel.create(
                session,
                name="agent-task-model",
                provider="codex",
                config_json="{}",
            )
            skill = Skill.create(
                session,
                name="agent-task-skill",
                display_name="Agent Task Skill",
                description="Agent task skill",
                status="active",
                source_type="ui",
            )
            version = SkillVersion.create(
                session,
                skill_id=skill.id,
                version="1.0.0",
                manifest_hash="",
            )
            skill_md = (
                "---\n"
                "name: agent-task-skill\n"
                "display_name: Agent Task Skill\n"
                "description: Agent task skill\n"
                "version: 1.0.0\n"
                "status: active\n"
                "---\n\n"
                "# Agent Task Skill\n"
            )
            SkillFile.create(
                session,
                skill_version_id=version.id,
                path="SKILL.md",
                content=skill_md,
                checksum="",
                size_bytes=len(skill_md.encode("utf-8")),
            )
            session.execute(
                agent_skill_bindings.insert().values(
                    agent_id=agent.id,
                    skill_id=skill.id,
                    position=1,
                )
            )
            task = AgentTask.create(
                session,
                agent_id=agent.id,
                model_id=model.id,
                status="queued",
                prompt="Run stage 3 agent task.",
            )
            task_id = task.id
            expected_skill_id = skill.id
            expected_version_id = version.id

        with patch.object(
            studio_tasks,
            "_run_llm",
            return_value=subprocess.CompletedProcess(
                args=["codex"],
                returncode=0,
                stdout=json.dumps({"ok": True}),
                stderr="",
            ),
        ), patch.object(
            studio_tasks,
            "load_integration_settings",
            return_value={},
        ), patch.object(
            studio_tasks,
            "resolve_enabled_llm_providers",
            return_value={"codex"},
        ), patch.object(
            studio_tasks,
            "resolve_llm_provider",
            return_value="codex",
        ), patch.object(
            studio_tasks,
            "resolve_default_model_id",
            return_value=None,
        ):
            studio_tasks._execute_agent_task(task_id)

        with session_scope() as session:
            task = session.get(AgentTask, task_id)
            self.assertIsNotNone(task)
            assert task is not None
            self.assertEqual("succeeded", task.status)
            self.assertEqual("native", task.skill_adapter_mode)
            resolved_ids = json.loads(task.resolved_skill_ids_json or "[]")
            resolved_versions = json.loads(task.resolved_skill_versions_json or "[]")
            self.assertEqual([expected_skill_id], resolved_ids)
            self.assertEqual(expected_skill_id, resolved_versions[0]["skill_id"])
            self.assertEqual(expected_version_id, resolved_versions[0]["version_id"])
            self.assertTrue(task.resolved_skill_manifest_hash)


if __name__ == "__main__":
    unittest.main()

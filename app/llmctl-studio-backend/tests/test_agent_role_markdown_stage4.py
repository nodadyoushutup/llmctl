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
    AgentPriority,
    AgentTask,
    FLOWCHART_NODE_TYPE_TASK,
    Flowchart,
    FlowchartNode,
    FlowchartRun,
    FlowchartRunNode,
    LLMModel,
    Role,
    Run,
)
from services import tasks as studio_tasks


class StudioDbTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp_dir = Path(self._tmp.name)
        self._orig_db_uri = Config.SQLALCHEMY_DATABASE_URI
        self._orig_workspaces_dir = Config.WORKSPACES_DIR
        self._orig_data_dir = Config.DATA_DIR
        Config.SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_dir / 'agent-role-stage4.sqlite3'}"
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


class AgentRoleMarkdownStage4Tests(StudioDbTestCase):
    def _create_agent_task_fixture(
        self,
        *,
        autorun: bool,
    ) -> tuple[int, int, int]:
        with session_scope() as session:
            role = Role.create(
                session,
                name="Stage4 Role",
                description="Role description",
                details_json=json.dumps({"purpose": "stage4"}),
            )
            agent = Agent.create(
                session,
                name="Stage4 Agent",
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
                name="stage4-codex",
                provider="codex",
                config_json="{}",
            )
            run_id: int | None = None
            if autorun:
                run = Run.create(
                    session,
                    name="stage4-run",
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
            return int(task.id), int(agent.id), int(role.id)

    def test_autorun_persists_instruction_snapshot_and_priority_order(self) -> None:
        task_id, agent_id, role_id = self._create_agent_task_fixture(autorun=True)
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
            del mcp_configs, model_config, on_update, on_log, env
            workspace = Path(str(cwd))
            captured["provider"] = provider
            captured["prompt"] = prompt
            captured["agents_md"] = (workspace / "AGENTS.md").read_text(encoding="utf-8")
            return subprocess.CompletedProcess(
                args=[provider],
                returncode=0,
                stdout="ok",
                stderr="",
            )

        with patch.object(studio_tasks, "_run_llm", side_effect=_fake_run_llm):
            studio_tasks._execute_agent_task(task_id, celery_task_id="stage4-celery")

        agent_markdown = captured.get("agents_md") or ""
        self.assertIn("## Priorities Source", agent_markdown)
        self.assertLess(
            agent_markdown.find("First priority"),
            agent_markdown.find("Second priority"),
        )
        prompt_payload = json.loads(captured.get("prompt") or "{}")
        self.assertEqual("autorun", prompt_payload.get("task_context", {}).get("kind"))
        self.assertIn(
            "configured priority order",
            prompt_payload.get("user_request") or "",
        )
        self.assertNotIn("Always stay on task", prompt_payload.get("user_request") or "")

        with session_scope() as session:
            task = session.get(AgentTask, task_id)
            assert task is not None
            self.assertEqual("succeeded", task.status)
            self.assertEqual(agent_id, task.resolved_agent_id)
            self.assertEqual(role_id, task.resolved_role_id)
            self.assertTrue((task.resolved_agent_version or "").strip())
            self.assertTrue((task.resolved_role_version or "").strip())
            self.assertTrue((task.resolved_instruction_manifest_hash or "").strip())
            self.assertEqual("native", task.instruction_adapter_mode)
            self.assertTrue((task.instruction_materialized_paths_json or "").strip())
            paths = json.loads(task.instruction_materialized_paths_json or "[]")
            self.assertTrue(any(str(path).endswith("/AGENTS.md") for path in paths))

    def test_non_autorun_omits_priorities_and_persists_snapshot(self) -> None:
        task_id, agent_id, role_id = self._create_agent_task_fixture(autorun=False)
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
            del prompt, mcp_configs, model_config, on_update, on_log, env
            workspace = Path(str(cwd))
            captured["provider"] = provider
            captured["agents_md"] = (workspace / "AGENTS.md").read_text(encoding="utf-8")
            return subprocess.CompletedProcess(
                args=[provider],
                returncode=0,
                stdout="ok",
                stderr="",
            )

        with patch.object(studio_tasks, "_run_llm", side_effect=_fake_run_llm):
            studio_tasks._execute_agent_task(task_id, celery_task_id="stage4-celery")

        agent_markdown = captured.get("agents_md") or ""
        self.assertNotIn("## Priorities Source", agent_markdown)

        with session_scope() as session:
            task = session.get(AgentTask, task_id)
            assert task is not None
            self.assertEqual("succeeded", task.status)
            self.assertEqual(agent_id, task.resolved_agent_id)
            self.assertEqual(role_id, task.resolved_role_id)
            self.assertTrue((task.resolved_instruction_manifest_hash or "").strip())
            self.assertEqual("native", task.instruction_adapter_mode)

    def test_flowchart_task_node_persists_instruction_snapshot(self) -> None:
        with session_scope() as session:
            role = Role.create(
                session,
                name="Flowchart Role",
                description="Role description",
                details_json=json.dumps({"purpose": "flowchart"}),
            )
            agent = Agent.create(
                session,
                name="Flowchart Agent",
                description="Agent description",
                role_id=role.id,
                prompt_json=json.dumps({"prompt": "Flowchart behavior"}),
                prompt_text=None,
            )
            AgentPriority.create(
                session,
                agent_id=agent.id,
                position=1,
                content="Should not be included for flowchart mode",
            )
            model = LLMModel.create(
                session,
                name="flowchart-codex",
                provider="codex",
                config_json="{}",
            )
            flowchart = Flowchart.create(session, name="stage4-flowchart")
            node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_TASK,
                model_id=model.id,
                config_json=json.dumps({"agent_id": agent.id}),
            )
            run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="running",
            )
            node_task = AgentTask.create(
                session,
                agent_id=agent.id,
                flowchart_id=flowchart.id,
                flowchart_run_id=run.id,
                flowchart_node_id=node.id,
                status="running",
                prompt="",
            )
            node_run = FlowchartRunNode.create(
                session,
                flowchart_run_id=run.id,
                flowchart_node_id=node.id,
                execution_index=1,
                agent_task_id=node_task.id,
                status="running",
                input_context_json=json.dumps({"flowchart": {"id": flowchart.id}}),
            )
            node_id = int(node.id)
            model_id = int(model.id)
            execution_id = int(node_run.id)
            execution_task_id = int(node_task.id)
            agent_id = int(agent.id)
            role_id = int(role.id)

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
            del prompt, mcp_configs, model_config, on_update, on_log, env
            workspace = Path(str(cwd))
            captured["provider"] = provider
            captured["agents_md"] = (workspace / "AGENTS.md").read_text(encoding="utf-8")
            return subprocess.CompletedProcess(
                args=[provider],
                returncode=0,
                stdout=json.dumps({"result": "ok"}),
                stderr="",
            )

        with patch.object(studio_tasks, "_run_llm", side_effect=_fake_run_llm):
            output_state, routing_state = studio_tasks._execute_flowchart_task_node(
                node_id=node_id,
                node_ref_id=None,
                node_config={
                    "task_prompt": "Flowchart prompt",
                    "agent_id": agent_id,
                },
                input_context={"flowchart": {"id": 1}},
                execution_id=execution_id,
                execution_task_id=execution_task_id,
                enabled_providers={"codex"},
                default_model_id=model_id,
            )

        self.assertEqual({}, routing_state)
        self.assertEqual("native", output_state.get("instruction_adapter_mode"))
        self.assertEqual(agent_id, output_state.get("resolved_agent_id"))
        self.assertEqual(role_id, output_state.get("resolved_role_id"))
        self.assertNotIn("## Priorities Source", captured.get("agents_md") or "")

        with session_scope() as session:
            node_run = session.get(FlowchartRunNode, execution_id)
            assert node_run is not None
            self.assertEqual(agent_id, node_run.resolved_agent_id)
            self.assertEqual(role_id, node_run.resolved_role_id)
            self.assertTrue((node_run.resolved_agent_version or "").strip())
            self.assertTrue((node_run.resolved_role_version or "").strip())
            self.assertTrue((node_run.resolved_instruction_manifest_hash or "").strip())
            self.assertEqual("native", node_run.instruction_adapter_mode)
            self.assertTrue((node_run.instruction_materialized_paths_json or "").strip())
            node_paths = json.loads(node_run.instruction_materialized_paths_json or "[]")
            self.assertTrue(any(str(path).endswith("/AGENTS.md") for path in node_paths))

            task = session.get(AgentTask, execution_task_id)
            assert task is not None
            self.assertEqual(agent_id, task.resolved_agent_id)
            self.assertEqual(role_id, task.resolved_role_id)
            self.assertEqual("native", task.instruction_adapter_mode)
            self.assertTrue((task.instruction_materialized_paths_json or "").strip())


if __name__ == "__main__":
    unittest.main()

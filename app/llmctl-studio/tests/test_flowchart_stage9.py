from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

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
    FLOWCHART_NODE_TYPE_DECISION,
    FLOWCHART_NODE_TYPE_END,
    FLOWCHART_NODE_TYPE_FLOWCHART,
    FLOWCHART_NODE_TYPE_MEMORY,
    FLOWCHART_NODE_TYPE_MILESTONE,
    FLOWCHART_NODE_TYPE_PLAN,
    FLOWCHART_NODE_TYPE_START,
    FLOWCHART_NODE_TYPE_TASK,
    LLMModel,
    MCPServer,
    Milestone,
    Memory,
    Plan,
    PlanStage,
    PlanTask,
    SCRIPT_TYPE_INIT,
    SCRIPT_TYPE_POST_INIT,
    SCRIPT_TYPE_POST_RUN,
    SCRIPT_TYPE_PRE_INIT,
    SCRIPT_TYPE_SKILL,
    Script,
    TaskTemplate,
    Flowchart,
    FlowchartEdge,
    FlowchartNode,
    FlowchartRun,
    FlowchartRunNode,
)
from services import tasks as studio_tasks
import web.views as studio_views


class StudioDbTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp_dir = Path(self._tmp.name)
        self._orig_db_uri = Config.SQLALCHEMY_DATABASE_URI
        self._orig_workspaces_dir = Config.WORKSPACES_DIR
        Config.SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_dir / 'stage9.sqlite3'}"
        Config.WORKSPACES_DIR = str(tmp_dir / "workspaces")
        Path(Config.WORKSPACES_DIR).mkdir(parents=True, exist_ok=True)
        self._reset_engine()

    def tearDown(self) -> None:
        self._dispose_engine()
        Config.SQLALCHEMY_DATABASE_URI = self._orig_db_uri
        Config.WORKSPACES_DIR = self._orig_workspaces_dir
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


class FlowchartStage9UnitTests(StudioDbTestCase):
    def _invoke_flowchart_run(
        self,
        flowchart_id: int,
        run_id: int,
        *,
        monotonic_values: list[float] | None = None,
    ) -> None:
        base_patches = [
            patch.object(studio_tasks, "load_integration_settings", return_value={}),
            patch.object(studio_tasks, "resolve_enabled_llm_providers", return_value=set()),
            patch.object(studio_tasks, "resolve_default_model_id", return_value=None),
        ]
        with base_patches[0], base_patches[1], base_patches[2]:
            if monotonic_values is None:
                studio_tasks.run_flowchart.run(flowchart_id, run_id)
                return
            with patch.object(
                studio_tasks.time, "monotonic", side_effect=monotonic_values
            ):
                studio_tasks.run_flowchart.run(flowchart_id, run_id)

    def test_decision_route_resolution_from_structured_output(self) -> None:
        input_context = {
            "latest_upstream": {
                "output_state": {"structured_output": {"route_key": "approve"}},
                "routing_state": {},
            }
        }
        output_state, routing_state = studio_tasks._execute_flowchart_decision_node(
            node_config={},
            input_context=input_context,
            mcp_server_keys=["llmctl-mcp"],
        )
        self.assertEqual("approve", routing_state["route_key"])
        self.assertEqual("approve", output_state["resolved_route_key"])
        selected = studio_tasks._resolve_flowchart_outgoing_edges(
            node_type=FLOWCHART_NODE_TYPE_DECISION,
            node_config={},
            outgoing_edges=[
                {"id": 1, "condition_key": "reject"},
                {"id": 2, "condition_key": "approve"},
            ],
            routing_state=routing_state,
        )
        self.assertEqual([2], [edge["id"] for edge in selected])

    def test_script_stage_split_preserves_order(self) -> None:
        scripts = [
            Script(id=1, file_name="a.sh", content="", script_type=SCRIPT_TYPE_INIT),
            Script(id=2, file_name="b.sh", content="", script_type=SCRIPT_TYPE_PRE_INIT),
            Script(id=3, file_name="c.sh", content="", script_type=SCRIPT_TYPE_INIT),
            Script(id=4, file_name="d.sh", content="", script_type=SCRIPT_TYPE_POST_RUN),
            Script(id=5, file_name="e.sh", content="", script_type=SCRIPT_TYPE_POST_INIT),
            Script(id=6, file_name="f.sh", content="", script_type=SCRIPT_TYPE_SKILL),
        ]
        pre_init, init, post_init, post_run, skill, unknown = (
            studio_tasks._split_scripts_by_stage(scripts)
        )
        self.assertEqual([2], [item.id for item in pre_init])
        self.assertEqual([1, 3], [item.id for item in init])
        self.assertEqual([5], [item.id for item in post_init])
        self.assertEqual([4], [item.id for item in post_run])
        self.assertEqual([6], [item.id for item in skill])
        self.assertEqual([], unknown)

    def test_node_model_resolver_precedence_and_override(self) -> None:
        with session_scope() as session:
            node_model = LLMModel.create(
                session,
                name="node-model",
                provider="codex",
                config_json="{}",
            )
            template_model = LLMModel.create(
                session,
                name="template-model",
                provider="codex",
                config_json="{}",
            )
            default_model = LLMModel.create(
                session,
                name="default-model",
                provider="codex",
                config_json="{}",
            )
            flowchart = Flowchart.create(session, name="resolver-flowchart")
            node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_TASK,
                model_id=node_model.id,
                x=0.0,
                y=0.0,
            )
            template = TaskTemplate.create(
                session,
                name="resolver-template",
                prompt="test",
                model_id=template_model.id,
            )

            resolved = studio_tasks._resolve_node_model(
                session,
                node=node,
                template=template,
                default_model_id=default_model.id,
            )
            self.assertEqual(node_model.id, resolved.id)

            node.model_id = None
            resolved = studio_tasks._resolve_node_model(
                session,
                node=node,
                template=template,
                default_model_id=default_model.id,
            )
            self.assertEqual(template_model.id, resolved.id)

            template.model_id = None
            resolved = studio_tasks._resolve_node_model(
                session,
                node=node,
                template=template,
                default_model_id=default_model.id,
            )
            self.assertEqual(default_model.id, resolved.id)

            with self.assertRaisesRegex(ValueError, "No model configured"):
                studio_tasks._resolve_node_model(
                    session,
                    node=node,
                    template=template,
                    default_model_id=None,
                )

    def test_task_node_runs_without_template_when_inline_prompt_present(self) -> None:
        with session_scope() as session:
            model = LLMModel.create(
                session,
                name="inline-task-model",
                provider="codex",
                config_json="{}",
            )
            flowchart = Flowchart.create(session, name="inline-task-flowchart")
            start_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                x=0.0,
                y=0.0,
            )
            task_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_TASK,
                model_id=model.id,
                x=1.0,
                y=0.0,
                config_json=json.dumps(
                    {
                        "task_name": "ad-hoc task",
                        "task_prompt": "Return JSON with route_key=done",
                    },
                    sort_keys=True,
                ),
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=task_node.id,
            )
            flowchart_run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="queued",
            )
            run_id = flowchart_run.id
            task_node_id = task_node.id
            flowchart_id = flowchart.id

        with patch.object(
            studio_tasks,
            "_run_llm",
            return_value=SimpleNamespace(
                args=[],
                returncode=0,
                stdout=json.dumps({"route_key": "done"}),
                stderr="Reading prompt from stdin...\n",
            ),
        ), patch.object(studio_tasks, "load_integration_settings", return_value={}), patch.object(
            studio_tasks, "resolve_enabled_llm_providers", return_value={"codex"}
        ), patch.object(studio_tasks, "resolve_default_model_id", return_value=None):
            studio_tasks.run_flowchart.run(flowchart_id, run_id)

        with session_scope() as session:
            run = session.get(FlowchartRun, run_id)
            self.assertEqual("completed", run.status)
            task_run = (
                session.query(FlowchartRunNode)
                .where(
                    FlowchartRunNode.flowchart_run_id == run_id,
                    FlowchartRunNode.flowchart_node_id == task_node_id,
                )
                .first()
            )
            self.assertIsNotNone(task_run)
            output_state = json.loads(task_run.output_state_json or "{}")
            self.assertEqual("config", output_state.get("task_prompt_source"))
            self.assertEqual("ad-hoc task", output_state.get("task_name"))
            self.assertIsNone(output_state.get("task_template_id"))
            self.assertEqual("", output_state.get("raw_error"))
            self.assertEqual("post_run", output_state.get("task_current_stage"))
            output_stage_logs = output_state.get("task_stage_logs") or {}
            self.assertIn("llm_query", output_stage_logs)
            self.assertIn("Launching", output_stage_logs.get("llm_query", ""))
            self.assertIsNotNone(task_run.agent_task_id)
            task = session.get(AgentTask, task_run.agent_task_id)
            self.assertIsNotNone(task)
            assert task is not None
            self.assertEqual("succeeded", task.status)
            self.assertEqual(flowchart_id, task.flowchart_id)
            self.assertEqual(run_id, task.flowchart_run_id)
            self.assertEqual(task_node_id, task.flowchart_node_id)
            self.assertEqual(json.dumps({"route_key": "done"}), task.output)
            self.assertEqual("post_run", task.current_stage)
            task_stage_logs = json.loads(task.stage_logs or "{}")
            self.assertIn("llm_query", task_stage_logs)
            self.assertIn("Launching", task_stage_logs.get("llm_query", ""))

    def test_task_node_uses_selected_agent_from_config(self) -> None:
        with session_scope() as session:
            model = LLMModel.create(
                session,
                name="inline-agent-task-model",
                provider="codex",
                config_json="{}",
            )
            agent = Agent.create(
                session,
                name="Task Agent",
                prompt_json=json.dumps({"instruction": "Use task agent profile."}),
            )
            flowchart = Flowchart.create(session, name="inline-agent-task-flowchart")
            start_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                x=0.0,
                y=0.0,
            )
            task_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_TASK,
                model_id=model.id,
                x=1.0,
                y=0.0,
                config_json=json.dumps(
                    {
                        "task_prompt": "Return JSON with route_key=done",
                        "agent_id": agent.id,
                    },
                    sort_keys=True,
                ),
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=task_node.id,
            )
            flowchart_run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="queued",
            )
            run_id = flowchart_run.id
            task_node_id = task_node.id
            flowchart_id = flowchart.id
            agent_id = agent.id

        with patch.object(
            studio_tasks,
            "_run_llm",
            return_value=SimpleNamespace(
                args=[],
                returncode=0,
                stdout=json.dumps({"route_key": "done"}),
                stderr="",
            ),
        ) as llm_mock, patch.object(
            studio_tasks,
            "load_integration_settings",
            return_value={},
        ), patch.object(
            studio_tasks,
            "resolve_enabled_llm_providers",
            return_value={"codex"},
        ), patch.object(
            studio_tasks,
            "resolve_default_model_id",
            return_value=None,
        ):
            studio_tasks.run_flowchart.run(flowchart_id, run_id)

        llm_prompt = llm_mock.call_args.args[1]
        llm_payload = json.loads(llm_prompt)
        self.assertEqual(agent_id, ((llm_payload.get("agent_profile") or {}).get("id")))

        with session_scope() as session:
            run = session.get(FlowchartRun, run_id)
            self.assertEqual("completed", run.status)
            node_run = (
                session.query(FlowchartRunNode)
                .where(
                    FlowchartRunNode.flowchart_run_id == run_id,
                    FlowchartRunNode.flowchart_node_id == task_node_id,
                )
                .first()
            )
            self.assertIsNotNone(node_run)
            output_state = json.loads(node_run.output_state_json or "{}")
            self.assertEqual(agent_id, output_state.get("agent_id"))
            self.assertEqual("config", output_state.get("agent_source"))
            task = session.get(AgentTask, node_run.agent_task_id)
            self.assertIsNotNone(task)
            assert task is not None
            self.assertEqual(agent_id, task.agent_id)

    def test_flowchart_task_output_display_prefers_raw_output(self) -> None:
        output = studio_tasks._flowchart_task_output_display(
            {
                "node_type": FLOWCHART_NODE_TYPE_TASK,
                "raw_output": "Hello\n",
                "structured_output": {"text": "ignored"},
            }
        )
        self.assertEqual("Hello\n", output)

    def test_node_view_output_display_prefers_flowchart_task_raw_output(self) -> None:
        raw = json.dumps(
            {
                "node_type": FLOWCHART_NODE_TYPE_TASK,
                "raw_output": "Hello\n",
                "structured_output": {"text": "Hello"},
            }
        )
        display = studio_views._task_output_for_display(raw)
        self.assertEqual("Hello\n", display)

    def test_scheduler_merge_waits_for_all_upstream_parents(self) -> None:
        with session_scope() as session:
            flowchart = Flowchart.create(session, name="merge-flowchart", max_parallel_nodes=2)
            start_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                x=0.0,
                y=0.0,
            )
            left_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=1.0,
                y=1.0,
            )
            right_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=2.0,
                y=2.0,
            )
            join_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=3.0,
                y=3.0,
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=left_node.id,
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=right_node.id,
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=left_node.id,
                target_node_id=join_node.id,
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=right_node.id,
                target_node_id=join_node.id,
            )
            flowchart_run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="queued",
            )
            run_id = flowchart_run.id
            join_node_id = join_node.id
            left_node_id = left_node.id
            right_node_id = right_node.id

        self._invoke_flowchart_run(flowchart.id, run_id)

        with session_scope() as session:
            run = session.get(FlowchartRun, run_id)
            self.assertIsNotNone(run)
            self.assertEqual("completed", run.status)
            node_runs = (
                session.query(FlowchartRunNode)
                .where(FlowchartRunNode.flowchart_run_id == run_id)
                .order_by(FlowchartRunNode.id.asc())
                .all()
            )
            self.assertEqual(4, len(node_runs))
            join_run = (
                session.query(FlowchartRunNode)
                .where(
                    FlowchartRunNode.flowchart_run_id == run_id,
                    FlowchartRunNode.flowchart_node_id == join_node_id,
                )
                .first()
            )
            self.assertIsNotNone(join_run)
            input_context = json.loads(join_run.input_context_json or "{}")
            upstream_nodes = input_context.get("upstream_nodes") or []
            self.assertEqual(2, len(upstream_nodes))
            self.assertEqual(
                [left_node_id, right_node_id],
                sorted(node["node_id"] for node in upstream_nodes),
            )

    def test_reaching_start_queues_followup_run(self) -> None:
        with session_scope() as session:
            flowchart = Flowchart.create(session, name="start-handoff-flowchart")
            start_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                x=0.0,
                y=0.0,
            )
            task_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=1.0,
                y=0.0,
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=task_node.id,
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=task_node.id,
                target_node_id=start_node.id,
            )
            flowchart_run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="queued",
            )
            flowchart_id = flowchart.id
            run_id = flowchart_run.id
            start_node_id = start_node.id
            task_node_id = task_node.id

        with patch.object(
            studio_tasks.run_flowchart,
            "delay",
            return_value=SimpleNamespace(id="next-run-job"),
        ) as delay_mock:
            self._invoke_flowchart_run(flowchart_id, run_id)

        with session_scope() as session:
            run = session.get(FlowchartRun, run_id)
            self.assertIsNotNone(run)
            assert run is not None
            self.assertEqual("completed", run.status)

            runs = (
                session.query(FlowchartRun)
                .where(FlowchartRun.flowchart_id == flowchart_id)
                .order_by(FlowchartRun.id.asc())
                .all()
            )
            self.assertEqual(2, len(runs))
            next_run = runs[-1]
            self.assertEqual("queued", next_run.status)
            self.assertNotEqual(run_id, next_run.id)

            node_runs = (
                session.query(FlowchartRunNode)
                .where(FlowchartRunNode.flowchart_run_id == run_id)
                .order_by(FlowchartRunNode.id.asc())
                .all()
            )
            self.assertEqual(2, len(node_runs))
            self.assertEqual(
                [start_node_id, task_node_id],
                [item.flowchart_node_id for item in node_runs],
            )

        delay_mock.assert_called_once()
        called_flowchart_id, called_run_id = delay_mock.call_args.args
        self.assertEqual(flowchart_id, called_flowchart_id)
        self.assertGreater(int(called_run_id), run_id)

    def test_stop_request_finishes_current_node_then_stops(self) -> None:
        with session_scope() as session:
            flowchart = Flowchart.create(session, name="graceful-stop-flowchart")
            start_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                x=0.0,
                y=0.0,
            )
            next_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=1.0,
                y=0.0,
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=next_node.id,
            )
            flowchart_run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="queued",
            )
            flowchart_id = flowchart.id
            run_id = flowchart_run.id
            start_node_id = start_node.id
            next_node_id = next_node.id

        original_execute = studio_tasks._execute_flowchart_node

        def _execute_with_stop_request(*args, **kwargs):
            node_id = int(kwargs.get("node_id"))
            if node_id == start_node_id:
                with session_scope() as session:
                    run = session.get(FlowchartRun, run_id)
                    assert run is not None
                    run.status = "stopping"
            return original_execute(*args, **kwargs)

        with patch.object(
            studio_tasks,
            "_execute_flowchart_node",
            side_effect=_execute_with_stop_request,
        ):
            self._invoke_flowchart_run(flowchart_id, run_id)

        with session_scope() as session:
            run = session.get(FlowchartRun, run_id)
            self.assertIsNotNone(run)
            assert run is not None
            self.assertEqual("stopped", run.status)
            node_runs = (
                session.query(FlowchartRunNode)
                .where(FlowchartRunNode.flowchart_run_id == run_id)
                .order_by(FlowchartRunNode.id.asc())
                .all()
            )
            self.assertEqual(1, len(node_runs))
            self.assertEqual(start_node_id, node_runs[0].flowchart_node_id)
            self.assertEqual("succeeded", node_runs[0].status)
            self.assertFalse(
                any(item.flowchart_node_id == next_node_id for item in node_runs)
            )

    def test_stop_request_prevents_followup_run_when_reaching_start(self) -> None:
        with session_scope() as session:
            flowchart = Flowchart.create(session, name="graceful-stop-no-followup")
            start_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                x=0.0,
                y=0.0,
            )
            memory_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=1.0,
                y=0.0,
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=memory_node.id,
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=memory_node.id,
                target_node_id=start_node.id,
            )
            flowchart_run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="queued",
            )
            flowchart_id = flowchart.id
            run_id = flowchart_run.id
            memory_node_id = memory_node.id

        original_execute = studio_tasks._execute_flowchart_node

        def _execute_with_stop_request(*args, **kwargs):
            node_id = int(kwargs.get("node_id"))
            if node_id == memory_node_id:
                with session_scope() as session:
                    run = session.get(FlowchartRun, run_id)
                    assert run is not None
                    run.status = "stopping"
            return original_execute(*args, **kwargs)

        with patch.object(
            studio_tasks,
            "_execute_flowchart_node",
            side_effect=_execute_with_stop_request,
        ), patch.object(
            studio_tasks.run_flowchart,
            "delay",
            return_value=SimpleNamespace(id="next-run-job"),
        ) as delay_mock:
            self._invoke_flowchart_run(flowchart_id, run_id)

        with session_scope() as session:
            run = session.get(FlowchartRun, run_id)
            self.assertIsNotNone(run)
            assert run is not None
            self.assertEqual("stopped", run.status)
            runs = (
                session.query(FlowchartRun)
                .where(FlowchartRun.flowchart_id == flowchart_id)
                .order_by(FlowchartRun.id.asc())
                .all()
            )
            self.assertEqual(1, len(runs))

        delay_mock.assert_not_called()

    def test_end_node_terminates_run_even_with_outgoing_edges(self) -> None:
        with session_scope() as session:
            flowchart = Flowchart.create(session, name="end-terminates-run")
            start_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                x=0.0,
                y=0.0,
            )
            end_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_END,
                x=1.0,
                y=0.0,
            )
            memory_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=2.0,
                y=0.0,
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=end_node.id,
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=end_node.id,
                target_node_id=memory_node.id,
            )
            flowchart_run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="queued",
            )
            flowchart_id = flowchart.id
            run_id = flowchart_run.id
            start_node_id = start_node.id
            end_node_id = end_node.id
            memory_node_id = memory_node.id

        with patch.object(
            studio_tasks.run_flowchart,
            "delay",
            return_value=SimpleNamespace(id="unexpected-followup-run"),
        ) as delay_mock:
            self._invoke_flowchart_run(flowchart_id, run_id)

        with session_scope() as session:
            run = session.get(FlowchartRun, run_id)
            self.assertIsNotNone(run)
            assert run is not None
            self.assertEqual("completed", run.status)

            node_runs = (
                session.query(FlowchartRunNode)
                .where(FlowchartRunNode.flowchart_run_id == run_id)
                .order_by(FlowchartRunNode.id.asc())
                .all()
            )
            self.assertEqual(
                [start_node_id, end_node_id],
                [item.flowchart_node_id for item in node_runs],
            )
            self.assertFalse(
                any(item.flowchart_node_id == memory_node_id for item in node_runs)
            )

        delay_mock.assert_not_called()

    def test_guardrail_max_node_executions_records_failure(self) -> None:
        with session_scope() as session:
            flowchart = Flowchart.create(
                session,
                name="max-node-executions",
                max_node_executions=1,
            )
            start_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                x=0.0,
                y=0.0,
            )
            gated_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=1.0,
                y=1.0,
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=gated_node.id,
            )
            flowchart_run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="queued",
            )
            run_id = flowchart_run.id
            gated_node_id = gated_node.id

        self._invoke_flowchart_run(flowchart.id, run_id)

        with session_scope() as session:
            run = session.get(FlowchartRun, run_id)
            self.assertEqual("failed", run.status)
            failed = (
                session.query(FlowchartRunNode)
                .where(
                    FlowchartRunNode.flowchart_run_id == run_id,
                    FlowchartRunNode.flowchart_node_id == gated_node_id,
                )
                .first()
            )
            self.assertIsNotNone(failed)
            self.assertEqual("failed", failed.status)
            self.assertIn("max_node_executions", failed.error or "")

    def test_guardrail_max_runtime_minutes_records_failure(self) -> None:
        with session_scope() as session:
            flowchart = Flowchart.create(
                session,
                name="max-runtime-minutes",
                max_runtime_minutes=1,
            )
            start_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                x=0.0,
                y=0.0,
            )
            flowchart_run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="queued",
            )
            run_id = flowchart_run.id
            start_node_id = start_node.id

        self._invoke_flowchart_run(
            flowchart.id,
            run_id,
            monotonic_values=[0.0, 120.0, 120.0],
        )

        with session_scope() as session:
            run = session.get(FlowchartRun, run_id)
            self.assertEqual("failed", run.status)
            failed = (
                session.query(FlowchartRunNode)
                .where(
                    FlowchartRunNode.flowchart_run_id == run_id,
                    FlowchartRunNode.flowchart_node_id == start_node_id,
                )
                .first()
            )
            self.assertIsNotNone(failed)
            self.assertEqual("failed", failed.status)
            self.assertIn("max_runtime_minutes", failed.error or "")

    def test_flowchart_node_queues_new_target_run_on_every_execution(self) -> None:
        with session_scope() as session:
            target_flowchart = Flowchart.create(session, name="target-flowchart")
            target_flowchart_id = target_flowchart.id

        with patch.object(
            studio_tasks.run_flowchart,
            "delay",
            side_effect=[
                SimpleNamespace(id="target-run-job-1"),
                SimpleNamespace(id="target-run-job-2"),
            ],
        ) as delay_mock:
            first_output_state, first_routing_state = (
                studio_tasks._execute_flowchart_flowchart_node(
                    node_ref_id=target_flowchart_id,
                )
            )
            second_output_state, second_routing_state = (
                studio_tasks._execute_flowchart_flowchart_node(
                    node_ref_id=target_flowchart_id,
                )
            )

        self.assertEqual({}, first_routing_state)
        self.assertEqual({}, second_routing_state)
        self.assertEqual(
            FLOWCHART_NODE_TYPE_FLOWCHART,
            first_output_state.get("node_type"),
        )
        self.assertEqual(
            FLOWCHART_NODE_TYPE_FLOWCHART,
            second_output_state.get("node_type"),
        )
        self.assertEqual(
            target_flowchart_id,
            int(first_output_state.get("triggered_flowchart_id") or 0),
        )
        self.assertEqual(
            target_flowchart_id,
            int(second_output_state.get("triggered_flowchart_id") or 0),
        )
        first_run_id = int(first_output_state.get("triggered_flowchart_run_id") or 0)
        second_run_id = int(second_output_state.get("triggered_flowchart_run_id") or 0)
        self.assertGreater(first_run_id, 0)
        self.assertGreater(second_run_id, 0)
        self.assertNotEqual(first_run_id, second_run_id)
        self.assertEqual(2, delay_mock.call_count)

        with session_scope() as session:
            runs = (
                session.query(FlowchartRun)
                .where(FlowchartRun.flowchart_id == target_flowchart_id)
                .order_by(FlowchartRun.id.asc())
                .all()
            )
            self.assertEqual(2, len(runs))
            self.assertEqual(first_run_id, runs[0].id)
            self.assertEqual(second_run_id, runs[1].id)
            self.assertEqual("queued", runs[0].status)
            self.assertEqual("queued", runs[1].status)
            self.assertEqual("target-run-job-1", runs[0].celery_task_id)
            self.assertEqual("target-run-job-2", runs[1].celery_task_id)

    def test_run_llm_codex_always_includes_skip_git_repo_check(self) -> None:
        failed = subprocess.CompletedProcess(
            args=["codex", "exec"],
            returncode=1,
            stdout="",
            stderr="some other codex failure",
        )

        with patch.object(studio_tasks.Config, "CODEX_SKIP_GIT_REPO_CHECK", False), patch.object(
            studio_tasks.Config, "CODEX_MODEL", ""
        ), patch.object(studio_tasks, "_run_llm_process", return_value=failed) as run_mock:
            result = studio_tasks._run_llm(
                provider="codex",
                prompt="hello",
                mcp_configs={},
                model_config={},
            )

        self.assertEqual(1, result.returncode)
        self.assertEqual(1, run_mock.call_count)
        self.assertIn("--skip-git-repo-check", run_mock.call_args.args[0])


class FlowchartStage9ApiTests(StudioDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        template_dir = STUDIO_SRC / "web" / "templates"
        app = Flask("stage9-api-tests", template_folder=str(template_dir))
        app.config["TESTING"] = True
        app.secret_key = "stage9-tests"
        app.register_blueprint(studio_views.bp)
        self.client = app.test_client()

    def _create_flowchart(self, name: str) -> int:
        response = self.client.post(
            "/flowcharts",
            json={"name": name},
        )
        self.assertEqual(201, response.status_code)
        payload = response.get_json() or {}
        return int(payload["flowchart"]["id"])

    def test_new_flowchart_starts_with_single_start_node(self) -> None:
        flowchart_id = self._create_flowchart("Stage 9 Default Start")
        graph_response = self.client.get(f"/flowcharts/{flowchart_id}/graph")
        self.assertEqual(200, graph_response.status_code)
        graph_payload = graph_response.get_json() or {}
        nodes = graph_payload.get("nodes") or []
        start_nodes = [
            node
            for node in nodes
            if node.get("node_type") == FLOWCHART_NODE_TYPE_START
        ]
        self.assertEqual(1, len(start_nodes))
        self.assertEqual(1, len(nodes))
        self.assertTrue((graph_payload.get("validation") or {}).get("valid"))

    def test_flowchart_crud_and_graph_save_load(self) -> None:
        flowchart_id = self._create_flowchart("Stage 9 CRUD")
        list_response = self.client.get("/flowcharts?format=json")
        self.assertEqual(200, list_response.status_code)
        flowcharts = (list_response.get_json() or {}).get("flowcharts") or []
        self.assertIn(flowchart_id, {int(item["id"]) for item in flowcharts})

        update_response = self.client.post(
            f"/flowcharts/{flowchart_id}",
            json={"name": "Stage 9 CRUD Updated", "max_parallel_nodes": 2},
        )
        self.assertEqual(200, update_response.status_code)

        graph_response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "client_id": "n-start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    },
                    {
                        "client_id": "n-decision",
                        "node_type": FLOWCHART_NODE_TYPE_DECISION,
                        "x": 200,
                        "y": 20,
                        "config": {
                            "route_field_path": "latest_upstream.output_state.message"
                        },
                    },
                ],
                "edges": [
                    {
                        "source_node_id": "n-start",
                        "target_node_id": "n-decision",
                        "source_handle_id": "r1",
                        "target_handle_id": "l1",
                        "label": "to decision",
                    },
                    {
                        "source_node_id": "n-decision",
                        "target_node_id": "n-start",
                        "source_handle_id": "b2",
                        "target_handle_id": "t2",
                        "condition_key": "Start node executed.",
                        "label": "loop",
                    },
                ],
            },
        )
        self.assertEqual(200, graph_response.status_code)
        graph_payload = graph_response.get_json() or {}
        self.assertEqual(2, len(graph_payload.get("nodes") or []))
        self.assertEqual(2, len(graph_payload.get("edges") or []))
        self.assertTrue((graph_payload.get("validation") or {}).get("valid"))
        saved_edges = graph_payload.get("edges") or []
        saved_edge_map = {
            (edge.get("source_handle_id"), edge.get("target_handle_id")): edge
            for edge in saved_edges
        }
        self.assertIn(("r1", "l1"), saved_edge_map)
        self.assertEqual("to decision", saved_edge_map[("r1", "l1")].get("label"))
        self.assertIn(("b2", "t2"), saved_edge_map)
        self.assertEqual("loop", saved_edge_map[("b2", "t2")].get("label"))

        load_response = self.client.get(f"/flowcharts/{flowchart_id}/graph")
        self.assertEqual(200, load_response.status_code)
        loaded = load_response.get_json() or {}
        self.assertEqual(2, len(loaded.get("nodes") or []))
        self.assertEqual(2, len(loaded.get("edges") or []))
        self.assertTrue((loaded.get("validation") or {}).get("valid"))
        loaded_edge_map = {
            (edge.get("source_handle_id"), edge.get("target_handle_id")): edge
            for edge in (loaded.get("edges") or [])
        }
        self.assertIn(("r1", "l1"), loaded_edge_map)
        self.assertIn(("b2", "t2"), loaded_edge_map)

        delete_response = self.client.post(
            f"/flowcharts/{flowchart_id}/delete",
            json={},
        )
        self.assertEqual(200, delete_response.status_code)
        self.assertTrue((delete_response.get_json() or {}).get("deleted"))

    def test_graph_allows_any_edge_handle_direction(self) -> None:
        flowchart_id = self._create_flowchart("Stage 9 Flexible Handles")
        response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "client_id": "n-start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    },
                    {
                        "client_id": "n-task",
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "x": 200,
                        "y": 20,
                        "config": {"task_prompt": "Hello"},
                    },
                ],
                "edges": [
                    {
                        "source_node_id": "n-start",
                        "target_node_id": "n-task",
                        "source_handle_id": "l1",
                        "target_handle_id": "r1",
                    }
                ],
            },
        )
        self.assertEqual(200, response.status_code)
        payload = response.get_json() or {}
        self.assertTrue((payload.get("validation") or {}).get("valid"))
        edges = payload.get("edges") or []
        self.assertEqual(1, len(edges))
        self.assertEqual("l1", edges[0].get("source_handle_id"))
        self.assertEqual("r1", edges[0].get("target_handle_id"))

        delete_response = self.client.post(
            f"/flowcharts/{flowchart_id}/delete",
            json={},
        )
        self.assertEqual(200, delete_response.status_code)
        self.assertTrue((delete_response.get_json() or {}).get("deleted"))

    def test_graph_rejects_multiple_outputs_for_non_decision_nodes(self) -> None:
        flowchart_id = self._create_flowchart("Stage 9 Output Limit")
        response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "client_id": "n-start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    },
                    {
                        "client_id": "n-task-a",
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "x": 200,
                        "y": -60,
                        "config": {"task_prompt": "A"},
                    },
                    {
                        "client_id": "n-task-b",
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "x": 200,
                        "y": 60,
                        "config": {"task_prompt": "B"},
                    },
                ],
                "edges": [
                    {"source_node_id": "n-start", "target_node_id": "n-task-a"},
                    {"source_node_id": "n-start", "target_node_id": "n-task-b"},
                ],
            },
        )
        self.assertEqual(400, response.status_code)
        payload = response.get_json() or {}
        errors = ((payload.get("validation") or {}).get("errors")) or []
        self.assertTrue(
            any("supports at most 1 outgoing edge" in str(error) for error in errors)
        )

    def test_graph_rejects_more_than_three_decision_outputs(self) -> None:
        flowchart_id = self._create_flowchart("Stage 9 Decision Output Limit")
        response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "client_id": "n-start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    },
                    {
                        "client_id": "n-decision",
                        "node_type": FLOWCHART_NODE_TYPE_DECISION,
                        "x": 160,
                        "y": 0,
                    },
                    {
                        "client_id": "n-task-1",
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "x": 320,
                        "y": -120,
                        "config": {"task_prompt": "1"},
                    },
                    {
                        "client_id": "n-task-2",
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "x": 320,
                        "y": -40,
                        "config": {"task_prompt": "2"},
                    },
                    {
                        "client_id": "n-task-3",
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "x": 320,
                        "y": 40,
                        "config": {"task_prompt": "3"},
                    },
                    {
                        "client_id": "n-task-4",
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "x": 320,
                        "y": 120,
                        "config": {"task_prompt": "4"},
                    },
                ],
                "edges": [
                    {"source_node_id": "n-start", "target_node_id": "n-decision"},
                    {
                        "source_node_id": "n-decision",
                        "target_node_id": "n-task-1",
                        "condition_key": "route_1",
                    },
                    {
                        "source_node_id": "n-decision",
                        "target_node_id": "n-task-2",
                        "condition_key": "route_2",
                    },
                    {
                        "source_node_id": "n-decision",
                        "target_node_id": "n-task-3",
                        "condition_key": "route_3",
                    },
                    {
                        "source_node_id": "n-decision",
                        "target_node_id": "n-task-4",
                        "condition_key": "route_4",
                    },
                ],
            },
        )
        self.assertEqual(400, response.status_code)
        payload = response.get_json() or {}
        errors = ((payload.get("validation") or {}).get("errors")) or []
        self.assertTrue(
            any("supports at most 3 outgoing edges" in str(error) for error in errors)
        )

    def test_graph_rejects_outgoing_edges_from_end_nodes(self) -> None:
        flowchart_id = self._create_flowchart("Stage 9 End Output Limit")
        response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "client_id": "n-start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    },
                    {
                        "client_id": "n-end",
                        "node_type": FLOWCHART_NODE_TYPE_END,
                        "x": 150,
                        "y": 0,
                    },
                    {
                        "client_id": "n-task",
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "x": 300,
                        "y": 0,
                        "config": {"task_prompt": "Do work"},
                    },
                ],
                "edges": [
                    {"source_node_id": "n-start", "target_node_id": "n-end"},
                    {"source_node_id": "n-end", "target_node_id": "n-task"},
                ],
            },
        )
        self.assertEqual(400, response.status_code)
        payload = response.get_json() or {}
        errors = ((payload.get("validation") or {}).get("errors")) or []
        self.assertTrue(any("End node" in str(error) for error in errors))

    def test_run_start_stop_and_status(self) -> None:
        flowchart_id = self._create_flowchart("Stage 9 Run")
        graph_response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "client_id": "n-start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    }
                ],
                "edges": [],
            },
        )
        self.assertEqual(200, graph_response.status_code)

        with patch.object(
            studio_views.run_flowchart, "delay", return_value=SimpleNamespace(id="job-123")
        ):
            run_response = self.client.post(f"/flowcharts/{flowchart_id}/run", json={})
        self.assertEqual(202, run_response.status_code)
        run_payload = (run_response.get_json() or {}).get("flowchart_run") or {}
        run_id = int(run_payload["id"])
        self.assertEqual("queued", run_payload["status"])

        status_response = self.client.get(f"/flowcharts/runs/{run_id}/status")
        self.assertEqual(200, status_response.status_code)
        status_payload = status_response.get_json() or {}
        self.assertEqual("queued", status_payload["status"])

        with patch.object(studio_views.celery_app.control, "revoke", return_value=None) as revoke_mock:
            stop_response = self.client.post(f"/flowcharts/runs/{run_id}/cancel", json={})
        self.assertEqual(200, stop_response.status_code)
        stop_payload = stop_response.get_json() or {}
        self.assertFalse(stop_payload["canceled"])
        self.assertEqual("stopped", stop_payload["flowchart_run"]["status"])
        self.assertEqual("stopped", stop_payload["action"])
        self.assertTrue(stop_payload["stop_requested"])
        self.assertEqual(1, revoke_mock.call_count)

        status_after_stop = self.client.get(f"/flowcharts/runs/{run_id}/status")
        self.assertEqual(200, status_after_stop.status_code)
        self.assertEqual("stopped", (status_after_stop.get_json() or {})["status"])

    def test_run_force_stop_sets_canceled(self) -> None:
        flowchart_id = self._create_flowchart("Stage 9 Force Stop")
        graph_response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "client_id": "n-start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    }
                ],
                "edges": [],
            },
        )
        self.assertEqual(200, graph_response.status_code)

        with patch.object(
            studio_views.run_flowchart, "delay", return_value=SimpleNamespace(id="job-456")
        ):
            run_response = self.client.post(f"/flowcharts/{flowchart_id}/run", json={})
        self.assertEqual(202, run_response.status_code)
        run_payload = (run_response.get_json() or {}).get("flowchart_run") or {}
        run_id = int(run_payload["id"])

        with patch.object(studio_views.celery_app.control, "revoke", return_value=None) as revoke_mock:
            force_response = self.client.post(
                f"/flowcharts/runs/{run_id}/cancel",
                json={"force": True},
            )
        self.assertEqual(200, force_response.status_code)
        force_payload = force_response.get_json() or {}
        self.assertTrue(force_payload["canceled"])
        self.assertEqual("canceled", force_payload["flowchart_run"]["status"])
        self.assertEqual("canceled", force_payload["action"])
        self.assertTrue(force_payload["force"])
        self.assertEqual(1, revoke_mock.call_count)
        _, revoke_kwargs = revoke_mock.call_args
        self.assertTrue(revoke_kwargs.get("terminate"))
        self.assertEqual("SIGTERM", revoke_kwargs.get("signal"))

    def test_graph_allows_task_inline_prompt_without_ref(self) -> None:
        flowchart_id = self._create_flowchart("Stage 9 Inline Task")
        graph_response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "client_id": "n-start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    },
                    {
                        "client_id": "n-task",
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "x": 160,
                        "y": 0,
                        "config": {"task_prompt": "Do something useful"},
                    },
                ],
                "edges": [
                    {
                        "source_node_id": "n-start",
                        "target_node_id": "n-task",
                    }
                ],
            },
        )
        self.assertEqual(200, graph_response.status_code)
        payload = graph_response.get_json() or {}
        self.assertTrue((payload.get("validation") or {}).get("valid"))
        task_node = next(
            node for node in (payload.get("nodes") or []) if node["node_type"] == FLOWCHART_NODE_TYPE_TASK
        )
        self.assertIsNone(task_node.get("ref_id"))

    def test_history_run_view_backfills_node_activity_tasks(self) -> None:
        with session_scope() as session:
            flowchart = Flowchart.create(session, name="Stage 9 History Backfill")
            start_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                x=0.0,
                y=0.0,
            )
            flowchart_run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="completed",
            )
            node_run = FlowchartRunNode.create(
                session,
                flowchart_run_id=flowchart_run.id,
                flowchart_node_id=start_node.id,
                execution_index=1,
                status="succeeded",
                input_context_json=json.dumps({"flowchart": {"run_id": flowchart_run.id}}),
                output_state_json=json.dumps({"message": "Start node executed."}),
            )
            flowchart_id = flowchart.id
            run_id = flowchart_run.id
            node_run_id = node_run.id
            start_node_id = start_node.id

        response = self.client.get(f"/flowcharts/{flowchart_id}/history/{run_id}")
        self.assertEqual(200, response.status_code)

        with session_scope() as session:
            stored_node_run = session.get(FlowchartRunNode, node_run_id)
            self.assertIsNotNone(stored_node_run)
            assert stored_node_run is not None
            self.assertIsNotNone(stored_node_run.agent_task_id)
            task = session.get(AgentTask, stored_node_run.agent_task_id)
            self.assertIsNotNone(task)
            assert task is not None
            self.assertEqual(flowchart_id, task.flowchart_id)
            self.assertEqual(run_id, task.flowchart_run_id)
            self.assertEqual(start_node_id, task.flowchart_node_id)

    def test_graph_rejects_task_without_ref_or_inline_prompt(self) -> None:
        flowchart_id = self._create_flowchart("Stage 9 Invalid Task")
        graph_response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "client_id": "n-start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    },
                    {
                        "client_id": "n-task",
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "x": 160,
                        "y": 0,
                        "config": {},
                    },
                ],
                "edges": [
                    {
                        "source_node_id": "n-start",
                        "target_node_id": "n-task",
                    }
                ],
            },
        )
        self.assertEqual(400, graph_response.status_code)
        payload = graph_response.get_json() or {}
        self.assertIn("task node requires ref_id or config.task_prompt", payload.get("error", ""))

    def test_graph_accepts_flowchart_node_with_ref_and_rejects_missing_ref(self) -> None:
        parent_flowchart_id = self._create_flowchart("Stage 9 Parent Flowchart")
        child_flowchart_id = self._create_flowchart("Stage 9 Child Flowchart")

        invalid_response = self.client.post(
            f"/flowcharts/{parent_flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "client_id": "start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    },
                    {
                        "client_id": "launch",
                        "node_type": FLOWCHART_NODE_TYPE_FLOWCHART,
                        "x": 180,
                        "y": 0,
                    },
                ],
                "edges": [
                    {"source_node_id": "start", "target_node_id": "launch"},
                ],
            },
        )
        self.assertEqual(400, invalid_response.status_code)
        invalid_payload = invalid_response.get_json() or {}
        self.assertIn("requires ref_id", invalid_payload.get("error", ""))

        valid_response = self.client.post(
            f"/flowcharts/{parent_flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "client_id": "start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    },
                    {
                        "client_id": "launch",
                        "node_type": FLOWCHART_NODE_TYPE_FLOWCHART,
                        "ref_id": child_flowchart_id,
                        "x": 180,
                        "y": 0,
                    },
                ],
                "edges": [
                    {"source_node_id": "start", "target_node_id": "launch"},
                ],
            },
        )
        self.assertEqual(200, valid_response.status_code)
        valid_payload = valid_response.get_json() or {}
        self.assertTrue((valid_payload.get("validation") or {}).get("valid"))
        flowchart_node = next(
            node
            for node in (valid_payload.get("nodes") or [])
            if node.get("node_type") == FLOWCHART_NODE_TYPE_FLOWCHART
        )
        self.assertEqual(child_flowchart_id, int(flowchart_node.get("ref_id") or 0))

    def test_node_bound_utilities_do_not_inherit_template_bindings(self) -> None:
        with session_scope() as session:
            template_model = LLMModel.create(
                session,
                name="template-model",
                provider="codex",
                config_json="{}",
            )
            node_model = LLMModel.create(
                session,
                name="node-model",
                provider="codex",
                config_json="{}",
            )
            template_mcp = MCPServer.create(
                session,
                name="template-mcp",
                server_key="template-mcp",
                config_json='{"command":"echo"}',
            )
            node_mcp = MCPServer.create(
                session,
                name="node-mcp",
                server_key="node-mcp",
                config_json='{"command":"echo"}',
            )
            template_script = Script.create(
                session,
                file_name="template.sh",
                content="#!/bin/sh\necho template\n",
                script_type=SCRIPT_TYPE_INIT,
            )
            node_script = Script.create(
                session,
                file_name="node.sh",
                content="#!/bin/sh\necho node\n",
                script_type=SCRIPT_TYPE_INIT,
            )
            template = TaskTemplate.create(
                session,
                name="template-task",
                prompt="prompt",
                model_id=template_model.id,
            )
            template.mcp_servers.append(template_mcp)
            template.scripts.append(template_script)
            template_id = template.id
            node_model_id = node_model.id
            node_mcp_id = node_mcp.id
            node_script_id = node_script.id
            template_mcp_id = template_mcp.id
            template_script_id = template_script.id

        flowchart_id = self._create_flowchart("Stage 9 Utilities")
        graph_response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "client_id": "n-start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    },
                    {
                        "client_id": "n-task",
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "ref_id": template_id,
                        "x": 120,
                        "y": 0,
                    },
                ],
                "edges": [
                    {
                        "source_node_id": "n-start",
                        "target_node_id": "n-task",
                    }
                ],
            },
        )
        self.assertEqual(200, graph_response.status_code)
        graph_payload = graph_response.get_json() or {}
        task_node = next(
            node for node in (graph_payload.get("nodes") or []) if node["node_type"] == "task"
        )
        task_node_id = int(task_node["id"])

        before = self.client.get(
            f"/flowcharts/{flowchart_id}/nodes/{task_node_id}/utilities"
        )
        self.assertEqual(200, before.status_code)
        before_node = (before.get_json() or {}).get("node") or {}
        self.assertIsNone(before_node.get("model_id"))
        self.assertEqual([], before_node.get("mcp_server_ids"))
        self.assertEqual([], before_node.get("script_ids"))
        self.assertNotIn(template_mcp_id, before_node.get("mcp_server_ids") or [])
        self.assertNotIn(template_script_id, before_node.get("script_ids") or [])

        set_model = self.client.post(
            f"/flowcharts/{flowchart_id}/nodes/{task_node_id}/model",
            json={"model_id": node_model_id},
        )
        self.assertEqual(200, set_model.status_code)
        attach_mcp = self.client.post(
            f"/flowcharts/{flowchart_id}/nodes/{task_node_id}/mcp-servers",
            json={"mcp_server_id": node_mcp_id},
        )
        self.assertEqual(200, attach_mcp.status_code)
        attach_script = self.client.post(
            f"/flowcharts/{flowchart_id}/nodes/{task_node_id}/scripts",
            json={"script_id": node_script_id},
        )
        self.assertEqual(200, attach_script.status_code)

        after = self.client.get(f"/flowcharts/{flowchart_id}/nodes/{task_node_id}/utilities")
        self.assertEqual(200, after.status_code)
        after_node = (after.get_json() or {}).get("node") or {}
        self.assertEqual(node_model_id, after_node.get("model_id"))
        self.assertIn(node_mcp_id, after_node.get("mcp_server_ids") or [])
        self.assertIn(node_script_id, after_node.get("script_ids") or [])
        self.assertNotIn(template_mcp_id, after_node.get("mcp_server_ids") or [])
        self.assertNotIn(template_script_id, after_node.get("script_ids") or [])

    def test_node_type_behaviors_task_plan_milestone_memory_decision(self) -> None:
        with session_scope() as session:
            model = LLMModel.create(
                session,
                name="integration-model",
                provider="codex",
                config_json="{}",
            )
            template = TaskTemplate.create(
                session,
                name="integration-template",
                prompt="Return structured JSON",
                model_id=model.id,
            )
            plan = Plan.create(session, name="integration-plan")
            stage = PlanStage.create(
                session,
                plan_id=plan.id,
                name="stage-1",
                position=1,
            )
            plan_task = PlanTask.create(
                session,
                plan_stage_id=stage.id,
                name="task-1",
                position=1,
            )
            milestone = Milestone.create(
                session,
                name="integration-milestone",
            )
            memory = Memory.create(session, description="before")
            template_id = template.id
            plan_id = plan.id
            stage_id = stage.id
            plan_task_id = plan_task.id
            milestone_id = milestone.id
            memory_id = memory.id

        flowchart_id = self._create_flowchart("Stage 9 Node Behaviors")
        graph_response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "client_id": "start",
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    },
                    {
                        "client_id": "task",
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "ref_id": template_id,
                        "x": 100,
                        "y": 0,
                    },
                    {
                        "client_id": "decision",
                        "node_type": FLOWCHART_NODE_TYPE_DECISION,
                        "x": 200,
                        "y": 0,
                    },
                    {
                        "client_id": "plan",
                        "node_type": FLOWCHART_NODE_TYPE_PLAN,
                        "ref_id": plan_id,
                        "x": 300,
                        "y": 0,
                        "config": {
                            "action": "update_completion",
                            "patch": {
                                "mark_plan_complete": True,
                                "complete_stage_ids": [stage_id],
                                "complete_task_ids": [plan_task_id],
                            },
                        },
                    },
                    {
                        "client_id": "milestone",
                        "node_type": FLOWCHART_NODE_TYPE_MILESTONE,
                        "ref_id": milestone_id,
                        "x": 400,
                        "y": 0,
                        "config": {
                            "action": "update",
                            "patch": {"latest_update": "milestone-updated"},
                            "mark_complete": True,
                        },
                    },
                    {
                        "client_id": "memory",
                        "node_type": FLOWCHART_NODE_TYPE_MEMORY,
                        "ref_id": memory_id,
                        "x": 500,
                        "y": 0,
                        "config": {
                            "action": "store",
                            "text_source_path": "latest_upstream.output_state.milestone.latest_update",
                        },
                    },
                ],
                "edges": [
                    {"source_node_id": "start", "target_node_id": "task"},
                    {"source_node_id": "task", "target_node_id": "decision"},
                    {
                        "source_node_id": "decision",
                        "target_node_id": "plan",
                        "condition_key": "continue",
                    },
                    {"source_node_id": "plan", "target_node_id": "milestone"},
                    {"source_node_id": "milestone", "target_node_id": "memory"},
                ],
            },
        )
        self.assertEqual(200, graph_response.status_code)
        self.assertTrue((graph_response.get_json() or {}).get("validation", {}).get("valid"))

        with patch.object(
            studio_views.run_flowchart, "delay", return_value=SimpleNamespace(id="job-node-types")
        ):
            run_response = self.client.post(f"/flowcharts/{flowchart_id}/run", json={})
        self.assertEqual(202, run_response.status_code)
        run_id = int(((run_response.get_json() or {}).get("flowchart_run") or {})["id"])

        fake_task_output = {
            "route_key": "continue",
            "note": "task-ok",
        }
        with patch.object(
            studio_tasks,
            "_run_llm",
            return_value=SimpleNamespace(
                args=[],
                returncode=0,
                stdout=json.dumps(fake_task_output),
                stderr="",
            ),
        ), patch.object(studio_tasks, "load_integration_settings", return_value={}), patch.object(
            studio_tasks, "resolve_enabled_llm_providers", return_value={"codex"}
        ), patch.object(studio_tasks, "resolve_default_model_id", return_value=None):
            studio_tasks.run_flowchart.run(flowchart_id, run_id)

        with session_scope() as session:
            run = session.get(FlowchartRun, run_id)
            self.assertEqual("completed", run.status)
            node_runs = (
                session.query(FlowchartRunNode)
                .where(FlowchartRunNode.flowchart_run_id == run_id)
                .order_by(FlowchartRunNode.id.asc())
                .all()
            )
            observed_types = {
                json.loads(item.output_state_json or "{}").get("node_type") for item in node_runs
            }
            self.assertEqual(
                {
                    FLOWCHART_NODE_TYPE_START,
                    FLOWCHART_NODE_TYPE_TASK,
                    FLOWCHART_NODE_TYPE_DECISION,
                    FLOWCHART_NODE_TYPE_PLAN,
                    FLOWCHART_NODE_TYPE_MILESTONE,
                    FLOWCHART_NODE_TYPE_MEMORY,
                },
                observed_types,
            )

            plan = session.get(Plan, plan_id)
            stage = session.get(PlanStage, stage_id)
            plan_task = session.get(PlanTask, plan_task_id)
            milestone = session.get(Milestone, milestone_id)
            memory = session.get(Memory, memory_id)

            self.assertIsNotNone(plan.completed_at)
            self.assertIsNotNone(stage.completed_at)
            self.assertIsNotNone(plan_task.completed_at)
            self.assertTrue(milestone.completed)
            self.assertEqual("done", milestone.status)
            self.assertEqual(100, milestone.progress_percent)
            self.assertEqual("milestone-updated", milestone.latest_update)
            self.assertEqual("milestone-updated", memory.description)


if __name__ == "__main__":
    unittest.main()

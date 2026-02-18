from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

import core.db as core_db
from core.config import Config
from core.db import session_scope
from core.models import (
    AgentTask,
    FLOWCHART_NODE_TYPE_MEMORY,
    FLOWCHART_NODE_TYPE_RAG,
    FLOWCHART_NODE_TYPE_START,
    Flowchart,
    FlowchartEdge,
    FlowchartNode,
    FlowchartRun,
    FlowchartRunNode,
    LLMModel,
    RAGRetrievalAudit,
)
from rag.domain import contracts as rag_contracts
from services import tasks as studio_tasks


class StudioDbTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp_dir = Path(self._tmp.name)
        self._orig_db_uri = Config.SQLALCHEMY_DATABASE_URI
        self._orig_data_dir = Config.DATA_DIR
        test_db_uri = os.getenv("LLMCTL_STUDIO_DATABASE_URI", self._orig_db_uri)
        if not str(test_db_uri or "").startswith("postgresql"):
            self.skipTest("RAG stage9 tests require PostgreSQL test database URI.")
        Config.SQLALCHEMY_DATABASE_URI = test_db_uri
        Config.DATA_DIR = str(tmp_dir / "data")
        Path(Config.DATA_DIR).mkdir(parents=True, exist_ok=True)
        self._reset_engine()

    def tearDown(self) -> None:
        self._dispose_engine()
        Config.SQLALCHEMY_DATABASE_URI = self._orig_db_uri
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


class RagStage9RuntimeTests(StudioDbTestCase):
    def _invoke_flowchart_run(self, flowchart_id: int, run_id: int) -> None:
        with (
            patch.object(studio_tasks, "load_integration_settings", return_value={}),
            patch.object(studio_tasks, "resolve_enabled_llm_providers", return_value=set()),
            patch.object(studio_tasks, "resolve_default_model_id", return_value=None),
            patch.object(
                studio_tasks,
                "rag_runtime_health_snapshot",
                return_value={"state": "configured_healthy", "provider": "chroma"},
            ),
        ):
            studio_tasks.run_flowchart.run(flowchart_id, run_id)

    def _create_rag_node(self) -> tuple[int, int]:
        with session_scope() as session:
            model = LLMModel.create(
                session,
                name="codex-rag",
                provider="codex",
                config_json="{}",
            )
            flowchart = Flowchart.create(session, name="RAG Runtime")
            rag_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_RAG,
                title="RAG Node",
                model_id=model.id,
                x=10.0,
                y=10.0,
                config_json=json.dumps({}, sort_keys=True),
            )
            return rag_node.id, model.id

    def test_query_prompt_merge_order(self) -> None:
        rag_node_id, _model_id = self._create_rag_node()

        captured_question: dict[str, str] = {}

        def _fake_query_contract(**kwargs):
            captured_question["value"] = str(kwargs.get("question") or "")
            return {
                "answer": "answer",
                "retrieval_context": [{"text": "ctx", "collection": "docs", "rank": 1}],
                "retrieval_stats": {"provider": "chroma", "top_k": 3, "retrieved_count": 1},
                "synthesis_error": None,
                "mode": "query",
                "collections": ["docs"],
            }

        input_context = {
            "flowchart": {"run_id": 42},
            "upstream_nodes": [
                {"node_id": 11, "output_state": {"answer": "solid context"}},
            ],
            "dotted_upstream_nodes": [
                {"node_id": 22, "output_state": {"answer": "dotted context"}},
            ],
        }

        with patch.object(studio_tasks, "execute_query_contract", side_effect=_fake_query_contract):
            output_state, routing_state = studio_tasks._execute_flowchart_rag_node(
                node_id=rag_node_id,
                node_config={
                    "mode": "query",
                    "collections": ["docs"],
                    "question_prompt": "base question",
                    "top_k": 3,
                },
                input_context=input_context,
                execution_id=99,
                default_model_id=None,
            )

        self.assertEqual({}, routing_state)
        self.assertEqual("query", output_state.get("mode"))
        merged = captured_question.get("value", "")
        self.assertTrue(merged)
        self.assertLess(merged.find("base question"), merged.find("Solid connector context"))
        self.assertLess(merged.find("Solid connector context"), merged.find("Dotted connector context"))

    def test_query_synthesis_prompt_includes_retrieval_source_metadata(self) -> None:
        rag_node_id, _model_id = self._create_rag_node()
        captured_user_prompt: dict[str, str] = {}

        def _fake_chat_completion(_config, messages):
            for message in messages:
                if isinstance(message, dict) and message.get("role") == "user":
                    captured_user_prompt["value"] = str(message.get("content") or "")
                    break
            return "Synthesized answer"

        def _fake_query_contract(**kwargs):
            synthesize_answer = kwargs.get("synthesize_answer")
            self.assertTrue(callable(synthesize_answer))
            answer = synthesize_answer(
                "Which file matched?",
                [
                    {
                        "text": "Probe snippet",
                        "collection": "drive_2",
                        "rank": 1,
                        "path": "sample_delta_index_probe.pdf",
                        "source_id": "src-2",
                        "chunk_id": "chunk-1",
                        "score": 0.123,
                    }
                ],
            )
            return {
                "answer": answer,
                "retrieval_context": [
                    {
                        "text": "Probe snippet",
                        "collection": "drive_2",
                        "rank": 1,
                        "path": "sample_delta_index_probe.pdf",
                    }
                ],
                "retrieval_stats": {"provider": "chroma", "top_k": 3, "retrieved_count": 1},
                "synthesis_error": None,
                "mode": "query",
                "collections": ["drive_2"],
            }

        with (
            patch.object(studio_tasks, "execute_query_contract", side_effect=_fake_query_contract),
            patch.object(
                studio_tasks,
                "load_rag_config",
                return_value=SimpleNamespace(chat_max_context_chars=12000),
            ),
            patch.object(studio_tasks, "rag_has_chat_api_key", return_value=True),
            patch.object(studio_tasks, "rag_call_chat_completion", side_effect=_fake_chat_completion),
        ):
            output_state, _routing_state = studio_tasks._execute_flowchart_rag_node(
                node_id=rag_node_id,
                node_config={
                    "mode": "query",
                    "collections": ["drive_2"],
                    "question_prompt": "Name one indexed file.",
                    "top_k": 3,
                },
                input_context={"flowchart": {"run_id": 42}},
                execution_id=99,
                default_model_id=None,
            )

        self.assertEqual("Synthesized answer", output_state.get("answer"))
        prompt = captured_user_prompt.get("value", "")
        self.assertIn("path=sample_delta_index_probe.pdf", prompt)
        self.assertIn("collection=drive_2", prompt)
        self.assertIn("Probe snippet", prompt)

    def test_index_mode_uses_collection_index_runner(self) -> None:
        rag_node_id, _model_id = self._create_rag_node()

        with patch.object(
            studio_tasks,
            "run_index_for_collections",
            return_value={
                "mode": "delta_index",
                "collections": ["docs"],
                "source_count": 1,
                "total_files": 4,
                "total_chunks": 13,
                "sources": [{"source_id": 1, "source_name": "Docs"}],
            },
        ) as mocked_index:
            output_state, _routing_state = studio_tasks._execute_flowchart_rag_node(
                node_id=rag_node_id,
                node_config={
                    "mode": "delta_index",
                    "collections": ["docs"],
                },
                input_context={"flowchart": {"run_id": 1}},
                execution_id=12,
                default_model_id=None,
            )

        mocked_index.assert_called_once()
        index_kwargs = mocked_index.call_args.kwargs
        self.assertEqual("delta_index", index_kwargs.get("mode"))
        self.assertEqual(["docs"], index_kwargs.get("collections"))
        self.assertEqual("codex", index_kwargs.get("model_provider"))
        self.assertTrue(callable(index_kwargs.get("on_log")))
        self.assertEqual("delta_index", output_state.get("mode"))
        self.assertEqual(["docs"], output_state.get("collections"))
        self.assertEqual(4, (output_state.get("retrieval_stats") or {}).get("total_files"))
        self.assertEqual("llm_query", output_state.get("task_current_stage"))
        stage_logs = output_state.get("task_stage_logs") or {}
        self.assertIn("llm_query", stage_logs)

    def test_quick_rag_run_uses_node_config_model_provider(self) -> None:
        with patch.object(
            studio_tasks,
            "run_index_for_collections",
            return_value={
                "mode": "fresh_index",
                "collections": ["docs"],
                "source_count": 1,
                "total_files": 2,
                "total_chunks": 5,
                "sources": [{"source_id": 1, "source_name": "Docs"}],
            },
        ) as mocked_index:
            output_state, _routing_state = studio_tasks._execute_flowchart_rag_node(
                node_id=999_999,
                node_config={
                    "mode": "fresh_index",
                    "collections": ["docs"],
                    "model_provider": "gemini",
                },
                input_context={
                    "kind": "rag_quick_run",
                    "rag_quick_run": {"source_id": 1},
                },
                execution_id=501,
                default_model_id=None,
            )

        mocked_index.assert_called_once()
        index_kwargs = mocked_index.call_args.kwargs
        self.assertEqual("fresh_index", index_kwargs.get("mode"))
        self.assertEqual(["docs"], index_kwargs.get("collections"))
        self.assertEqual("gemini", index_kwargs.get("model_provider"))
        self.assertTrue(callable(index_kwargs.get("on_log")))
        self.assertEqual("gemini", output_state.get("model_provider"))
        self.assertIsNone(output_state.get("model_id"))
        self.assertEqual("", output_state.get("model_name"))

    def test_index_mode_captures_stage_logs_for_execution_task(self) -> None:
        with session_scope() as session:
            task = AgentTask.create(
                session,
                status="running",
                kind="rag_quick_index",
                prompt=json.dumps(
                    {
                        "task_context": {
                            "kind": "rag_quick_run",
                            "rag_quick_run": {"mode": "fresh_index", "collection": "docs"},
                        }
                    },
                    sort_keys=True,
                ),
            )
            task_id = int(task.id)

        def _index_side_effect(*, mode, collections, model_provider, on_log):
            self.assertEqual("fresh_index", mode)
            self.assertEqual(["docs"], collections)
            self.assertEqual("codex", model_provider)
            self.assertTrue(callable(on_log))
            on_log("Index start")
            on_log("Index finish")
            return {
                "mode": "fresh_index",
                "collections": ["docs"],
                "source_count": 1,
                "total_files": 2,
                "total_chunks": 3,
                "sources": [{"source_id": 1, "source_name": "Docs"}],
            }

        with patch.object(
            studio_tasks,
            "run_index_for_collections",
            side_effect=_index_side_effect,
        ):
            output_state, _routing_state = studio_tasks._execute_flowchart_rag_node(
                node_id=999_991,
                node_config={
                    "mode": "fresh_index",
                    "collections": ["docs"],
                    "model_provider": "codex",
                },
                input_context={
                    "kind": "rag_quick_run",
                    "rag_quick_run": {"source_id": 1},
                },
                execution_id=task_id,
                execution_task_id=task_id,
                default_model_id=None,
            )

        self.assertEqual("llm_query", output_state.get("task_current_stage"))
        stage_logs = output_state.get("task_stage_logs") or {}
        llm_query_logs = str(stage_logs.get("llm_query") or "")
        self.assertIn("Index start", llm_query_logs)
        self.assertIn("Index finish", llm_query_logs)

        with session_scope() as session:
            updated = session.get(AgentTask, task_id)
            assert updated is not None
            self.assertEqual("llm_query", str(updated.current_stage or ""))
            persisted_logs = json.loads(updated.stage_logs or "{}")
            self.assertIn("Index start", str(persisted_logs.get("llm_query") or ""))

    def test_flowchart_run_executes_rag_node_in_each_mode(self) -> None:
        for mode in ("fresh_index", "delta_index", "query"):
            with self.subTest(mode=mode):
                with session_scope() as session:
                    model = LLMModel.create(
                        session,
                        name=f"codex-{mode}",
                        provider="codex",
                        config_json="{}",
                    )
                    flowchart = Flowchart.create(session, name=f"RAG Mode {mode}")
                    start_node = FlowchartNode.create(
                        session,
                        flowchart_id=flowchart.id,
                        node_type=FLOWCHART_NODE_TYPE_START,
                        x=0.0,
                        y=0.0,
                        config_json=json.dumps({}, sort_keys=True),
                    )
                    rag_config: dict[str, object] = {
                        "mode": mode,
                        "collections": [f"{mode}-docs"],
                    }
                    if mode == "query":
                        rag_config["question_prompt"] = "What changed?"
                        rag_config["top_k"] = 4
                    rag_node = FlowchartNode.create(
                        session,
                        flowchart_id=flowchart.id,
                        node_type=FLOWCHART_NODE_TYPE_RAG,
                        title=f"RAG {mode}",
                        model_id=model.id,
                        x=160.0,
                        y=0.0,
                        config_json=json.dumps(rag_config, sort_keys=True),
                    )
                    FlowchartEdge.create(
                        session,
                        flowchart_id=flowchart.id,
                        source_node_id=start_node.id,
                        target_node_id=rag_node.id,
                        edge_mode="solid",
                    )
                    run = FlowchartRun.create(
                        session,
                        flowchart_id=flowchart.id,
                        status="queued",
                    )
                    flowchart_id = flowchart.id
                    run_id = run.id
                    rag_node_id = rag_node.id

                if mode == "query":
                    with patch.object(
                        studio_tasks,
                        "execute_query_contract",
                        return_value={
                            "answer": "query answer",
                            "retrieval_context": [
                                {"text": "ctx", "collection": f"{mode}-docs", "rank": 1}
                            ],
                            "retrieval_stats": {
                                "provider": "chroma",
                                "retrieved_count": 1,
                                "top_k": 4,
                            },
                            "synthesis_error": None,
                            "mode": "query",
                            "collections": [f"{mode}-docs"],
                        },
                    ) as mocked_query:
                        self._invoke_flowchart_run(flowchart_id, run_id)
                    mocked_query.assert_called_once()
                    self.assertEqual([f"{mode}-docs"], mocked_query.call_args.kwargs["collections"])
                else:
                    with patch.object(
                        studio_tasks,
                        "run_index_for_collections",
                        return_value={
                            "mode": mode,
                            "collections": [f"{mode}-docs"],
                            "source_count": 1,
                            "total_files": 2,
                            "total_chunks": 6,
                            "sources": [{"source_id": 1, "source_name": "Docs"}],
                        },
                    ) as mocked_index:
                        self._invoke_flowchart_run(flowchart_id, run_id)
                    mocked_index.assert_called_once()
                    index_kwargs = mocked_index.call_args.kwargs
                    self.assertEqual(mode, index_kwargs.get("mode"))
                    self.assertEqual([f"{mode}-docs"], index_kwargs.get("collections"))
                    self.assertEqual("codex", index_kwargs.get("model_provider"))
                    self.assertTrue(callable(index_kwargs.get("on_log")))

                with session_scope() as session:
                    updated_run = session.get(FlowchartRun, run_id)
                    self.assertIsNotNone(updated_run)
                    self.assertEqual("completed", updated_run.status if updated_run else None)
                    rag_node_run = (
                        session.query(FlowchartRunNode)
                        .filter(
                            FlowchartRunNode.flowchart_run_id == run_id,
                            FlowchartRunNode.flowchart_node_id == rag_node_id,
                        )
                        .one()
                    )
                    self.assertEqual("succeeded", rag_node_run.status)
                    output_state = json.loads(rag_node_run.output_state_json or "{}")
                    self.assertEqual(mode, output_state.get("mode"))
                    self.assertEqual([f"{mode}-docs"], output_state.get("collections"))

    def test_rag_output_is_available_to_downstream_node_context(self) -> None:
        with session_scope() as session:
            model = LLMModel.create(
                session,
                name="codex-query",
                provider="codex",
                config_json="{}",
            )
            flowchart = Flowchart.create(session, name="RAG downstream context")
            start_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                x=0.0,
                y=0.0,
                config_json=json.dumps({}, sort_keys=True),
            )
            rag_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_RAG,
                model_id=model.id,
                x=150.0,
                y=0.0,
                config_json=json.dumps(
                    {
                        "mode": "query",
                        "collections": ["docs"],
                        "question_prompt": "Summarize docs",
                        "top_k": 3,
                    },
                    sort_keys=True,
                ),
            )
            memory_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=300.0,
                y=0.0,
                config_json=json.dumps({}, sort_keys=True),
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=rag_node.id,
                edge_mode="solid",
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=rag_node.id,
                target_node_id=memory_node.id,
                edge_mode="solid",
            )
            run = FlowchartRun.create(session, flowchart_id=flowchart.id, status="queued")
            flowchart_id = flowchart.id
            run_id = run.id
            memory_node_id = memory_node.id
            rag_node_id = rag_node.id

        with patch.object(
            studio_tasks,
            "execute_query_contract",
            return_value={
                "answer": "RAG answer",
                "retrieval_context": [{"text": "ctx", "collection": "docs", "rank": 1}],
                "retrieval_stats": {"provider": "chroma", "retrieved_count": 1, "top_k": 3},
                "synthesis_error": None,
                "mode": "query",
                "collections": ["docs"],
            },
        ):
            self._invoke_flowchart_run(flowchart_id, run_id)

        with session_scope() as session:
            run = session.get(FlowchartRun, run_id)
            self.assertIsNotNone(run)
            self.assertEqual("completed", run.status if run else None)
            memory_node_run = (
                session.query(FlowchartRunNode)
                .filter(
                    FlowchartRunNode.flowchart_run_id == run_id,
                    FlowchartRunNode.flowchart_node_id == memory_node_id,
                )
                .one()
            )
            input_context = json.loads(memory_node_run.input_context_json or "{}")
            upstream_nodes = input_context.get("upstream_nodes") or []
            self.assertEqual(1, len(upstream_nodes))
            self.assertEqual(rag_node_id, upstream_nodes[0].get("node_id"))
            upstream_output = upstream_nodes[0].get("output_state") or {}
            self.assertEqual("query", upstream_output.get("mode"))
            self.assertEqual(["docs"], upstream_output.get("collections"))

    def test_rag_query_runtime_merges_solid_and_dotted_context(self) -> None:
        with session_scope() as session:
            model = LLMModel.create(
                session,
                name="codex-query-context",
                provider="codex",
                config_json="{}",
            )
            flowchart = Flowchart.create(session, name="RAG mixed connector context")
            start_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                x=0.0,
                y=0.0,
                config_json=json.dumps({}, sort_keys=True),
            )
            solid_context_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=120.0,
                y=-70.0,
                config_json=json.dumps(
                    {"action": "store", "text": "solid context"},
                    sort_keys=True,
                ),
            )
            dotted_context_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=120.0,
                y=70.0,
                config_json=json.dumps(
                    {"action": "store", "text": "dotted context"},
                    sort_keys=True,
                ),
            )
            rag_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_RAG,
                model_id=model.id,
                x=280.0,
                y=0.0,
                config_json=json.dumps(
                    {
                        "mode": "query",
                        "collections": ["docs"],
                        "question_prompt": "base question",
                        "top_k": 3,
                    },
                    sort_keys=True,
                ),
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=solid_context_node.id,
                edge_mode="solid",
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=dotted_context_node.id,
                edge_mode="solid",
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=solid_context_node.id,
                target_node_id=rag_node.id,
                edge_mode="solid",
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=dotted_context_node.id,
                target_node_id=rag_node.id,
                edge_mode="dotted",
            )
            run = FlowchartRun.create(session, flowchart_id=flowchart.id, status="queued")
            flowchart_id = flowchart.id
            run_id = run.id

        captured_question: dict[str, str] = {}

        def _fake_query_contract(**kwargs):
            captured_question["value"] = str(kwargs.get("question") or "")
            return {
                "answer": "RAG answer",
                "retrieval_context": [{"text": "ctx", "collection": "docs", "rank": 1}],
                "retrieval_stats": {"provider": "chroma", "retrieved_count": 1, "top_k": 3},
                "synthesis_error": None,
                "mode": "query",
                "collections": ["docs"],
            }

        with patch.object(studio_tasks, "execute_query_contract", side_effect=_fake_query_contract):
            self._invoke_flowchart_run(flowchart_id, run_id)

        question = captured_question.get("value", "")
        self.assertIn("base question", question)
        self.assertIn("Solid connector context", question)
        self.assertIn("Dotted connector context", question)
        self.assertLess(question.find("Solid connector context"), question.find("Dotted connector context"))

    def test_non_rag_nodes_still_execute_with_rag_runtime_changes(self) -> None:
        with session_scope() as session:
            flowchart = Flowchart.create(session, name="Non-RAG regression")
            start_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                x=0.0,
                y=0.0,
                config_json=json.dumps({}, sort_keys=True),
            )
            memory_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                x=140.0,
                y=0.0,
                config_json=json.dumps(
                    {"action": "store", "text": "baseline memory"},
                    sort_keys=True,
                ),
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=memory_node.id,
                edge_mode="solid",
            )
            run = FlowchartRun.create(session, flowchart_id=flowchart.id, status="queued")
            flowchart_id = flowchart.id
            run_id = run.id
            start_node_id = start_node.id
            memory_node_id = memory_node.id

        self._invoke_flowchart_run(flowchart_id, run_id)

        with session_scope() as session:
            updated_run = session.get(FlowchartRun, run_id)
            self.assertIsNotNone(updated_run)
            self.assertEqual("completed", updated_run.status if updated_run else None)
            node_runs = (
                session.query(FlowchartRunNode)
                .filter(FlowchartRunNode.flowchart_run_id == run_id)
                .order_by(FlowchartRunNode.execution_index.asc(), FlowchartRunNode.id.asc())
                .all()
            )
            self.assertEqual(
                [start_node_id, memory_node_id],
                [item.flowchart_node_id for item in node_runs],
            )

    def test_rag_node_activity_metadata_contains_execution_details(self) -> None:
        with session_scope() as session:
            model = LLMModel.create(
                session,
                name="codex-query-activity",
                provider="codex",
                config_json="{}",
            )
            flowchart = Flowchart.create(session, name="RAG activity metadata")
            start_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                x=0.0,
                y=0.0,
                config_json=json.dumps({}, sort_keys=True),
            )
            rag_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_RAG,
                model_id=model.id,
                x=160.0,
                y=0.0,
                config_json=json.dumps(
                    {
                        "mode": "query",
                        "collections": ["docs"],
                        "question_prompt": "Give summary",
                        "top_k": 5,
                    },
                    sort_keys=True,
                ),
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=rag_node.id,
                edge_mode="solid",
            )
            run = FlowchartRun.create(session, flowchart_id=flowchart.id, status="queued")
            flowchart_id = flowchart.id
            run_id = run.id
            rag_node_id = rag_node.id

        with patch.object(
            studio_tasks,
            "execute_query_contract",
            return_value={
                "answer": "detailed answer",
                "retrieval_context": [{"text": "ctx", "collection": "docs", "rank": 1}],
                "retrieval_stats": {"provider": "chroma", "retrieved_count": 1, "top_k": 5},
                "synthesis_error": None,
                "mode": "query",
                "collections": ["docs"],
            },
        ):
            self._invoke_flowchart_run(flowchart_id, run_id)

        with session_scope() as session:
            rag_node_run = (
                session.query(FlowchartRunNode)
                .filter(
                    FlowchartRunNode.flowchart_run_id == run_id,
                    FlowchartRunNode.flowchart_node_id == rag_node_id,
                )
                .one()
            )
            self.assertEqual("succeeded", rag_node_run.status)
            output_state = json.loads(rag_node_run.output_state_json or "{}")
            self.assertEqual("query", output_state.get("mode"))
            self.assertEqual(["docs"], output_state.get("collections"))
            retrieval_stats = output_state.get("retrieval_stats") or {}
            self.assertEqual("chroma", retrieval_stats.get("provider"))
            self.assertEqual(1, retrieval_stats.get("retrieved_count"))
            self.assertEqual(5, retrieval_stats.get("top_k"))
            self.assertEqual("detailed answer", output_state.get("answer"))
            self.assertEqual("detailed answer", output_state.get("raw_output"))
            structured_output = output_state.get("structured_output") or {}
            self.assertEqual("detailed answer", structured_output.get("text"))

    def test_run_flowchart_fails_fast_for_unhealthy_rag(self) -> None:
        with session_scope() as session:
            model = LLMModel.create(
                session,
                name="codex-rag",
                provider="codex",
                config_json="{}",
            )
            flowchart = Flowchart.create(session, name="RAG Precheck")
            start_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_START,
                x=0.0,
                y=0.0,
                config_json=json.dumps({}, sort_keys=True),
            )
            rag_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_RAG,
                model_id=model.id,
                x=100.0,
                y=100.0,
                config_json=json.dumps(
                    {
                        "mode": "query",
                        "collections": ["docs"],
                        "question_prompt": "Q",
                    },
                    sort_keys=True,
                ),
            )
            FlowchartEdge.create(
                session,
                flowchart_id=flowchart.id,
                source_node_id=start_node.id,
                target_node_id=rag_node.id,
                edge_mode="solid",
            )
            run = FlowchartRun.create(session, flowchart_id=flowchart.id, status="queued")

        with patch.object(
            studio_tasks,
            "rag_runtime_health_snapshot",
            return_value={"state": "configured_unhealthy", "provider": "chroma"},
        ):
            studio_tasks.run_flowchart.run(flowchart.id, run.id)

        with session_scope() as session:
            updated_run = session.get(FlowchartRun, run.id)
            self.assertIsNotNone(updated_run)
            self.assertEqual("failed", updated_run.status if updated_run else None)

            run_nodes = (
                session.query(FlowchartRunNode)
                .filter(FlowchartRunNode.flowchart_run_id == run.id)
                .all()
            )
            self.assertTrue(run_nodes)
            self.assertEqual(rag_node.id, run_nodes[0].flowchart_node_id)
            self.assertIn("pre-run validation failed", str(run_nodes[0].error or ""))


class RagStage9AuditContractTests(StudioDbTestCase):
    def test_query_contract_keeps_citation_metadata_without_snippet_leakage(self) -> None:
        source = SimpleNamespace(
            id=1,
            name="Docs",
            kind="local",
            collection="docs",
            last_error=None,
            last_indexed_at=object(),
        )
        config = SimpleNamespace()

        with (
            patch.object(
                rag_contracts,
                "rag_health_snapshot",
                return_value={"state": "configured_healthy", "provider": "chroma"},
            ),
            patch.object(rag_contracts, "list_sources", return_value=[source]),
            patch.object(rag_contracts, "load_config", return_value=config),
            patch.object(rag_contracts, "has_embedding_api_key", return_value=True),
            patch.object(
                rag_contracts,
                "get_collections",
                return_value=[{"source": source, "collection": object()}],
            ),
            patch.object(
                rag_contracts,
                "query_collections",
                return_value=(
                    ["retrieved snippet text"],
                    [
                        {
                            "collection": "docs",
                            "source_id": "src-1",
                            "path": "docs/readme.md",
                            "chunk_id": "chunk-1",
                            "score": 0.12,
                        }
                    ],
                ),
            ),
        ):
            result = rag_contracts.execute_query_contract(
                question="What is supported?",
                collections=["docs"],
                top_k=5,
                request_id="req-123",
                runtime_kind="flowchart",
                flowchart_run_id=7,
                flowchart_node_run_id=8,
                synthesize_answer=lambda _q, _ctx: "Answer",
            )

        self.assertEqual("Answer", result.get("answer"))
        context_row = (result.get("retrieval_context") or [])[0]
        self.assertIn("text", context_row)
        self.assertIn("collection", context_row)
        self.assertIn("rank", context_row)
        self.assertEqual("docs/readme.md", context_row.get("path"))
        self.assertEqual("chunk-1", context_row.get("chunk_id"))
        self.assertEqual("src-1", context_row.get("source_id"))
        self.assertNotIn("snippet", context_row)
        citation_row = (result.get("citation_records") or [])[0]
        self.assertEqual("docs", citation_row.get("collection"))
        self.assertEqual("docs/readme.md", citation_row.get("path"))
        self.assertEqual("chunk-1", citation_row.get("chunk_id"))
        self.assertNotIn("snippet", citation_row)

        with session_scope() as session:
            rows = session.query(RAGRetrievalAudit).all()
            self.assertEqual(1, len(rows))
            self.assertEqual("docs", rows[0].collection)
            self.assertEqual("docs/readme.md", rows[0].path)
            self.assertEqual("retrieved snippet text", rows[0].snippet)

    def test_format_retrieval_context_for_synthesis_includes_source_metadata(self) -> None:
        rendered = rag_contracts.format_retrieval_context_for_synthesis(
            [
                {
                    "text": "Primary snippet",
                    "collection": "drive_2",
                    "rank": 1,
                    "source_id": "src-2",
                    "path": "sample.pdf",
                    "chunk_id": "chunk-a",
                    "score": 0.42,
                }
            ]
        )
        self.assertIn("[1]", rendered)
        self.assertIn("collection=drive_2", rendered)
        self.assertIn("path=sample.pdf", rendered)
        self.assertIn("chunk_id=chunk-a", rendered)
        self.assertIn("score=0.42", rendered)
        self.assertIn("Primary snippet", rendered)


if __name__ == "__main__":
    unittest.main()

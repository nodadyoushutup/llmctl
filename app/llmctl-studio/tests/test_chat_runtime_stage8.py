from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask
from sqlalchemy import func, select

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio" / "src"
STUDIO_APP_ROOT = REPO_ROOT / "app" / "llmctl-studio"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))
if str(STUDIO_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(STUDIO_APP_ROOT))

import core.db as core_db
from chat.contracts import (
    CHAT_REASON_MCP_FAILED,
    RAG_HEALTH_CONFIGURED_HEALTHY,
    RAG_HEALTH_CONFIGURED_UNHEALTHY,
    RAG_REASON_UNAVAILABLE,
)
from chat.rag_client import StubRAGContractClient
from chat.runtime import (
    archive_thread,
    clear_thread,
    create_thread,
    delete_thread,
    execute_turn,
    get_thread,
    list_activity,
    list_threads,
    restore_thread,
)
from chat.settings import (
    load_chat_runtime_settings_payload,
    save_chat_runtime_settings,
)
from core.config import Config
from core.db import session_scope
from core.models import (
    CHAT_TURN_STATUS_FAILED,
    ChatActivityEvent,
    ChatMessage,
    ChatThread,
    ChatTurn,
    IntegrationSetting,
    LLMModel,
    MCPServer,
)
from web import views as studio_views


class StudioDbTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp_dir = Path(self._tmp.name)
        self._orig_db_uri = Config.SQLALCHEMY_DATABASE_URI
        self._orig_data_dir = Config.DATA_DIR
        Config.SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_dir / 'chat-runtime.sqlite3'}"
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


class ChatRuntimeStage8Tests(StudioDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        template_dir = STUDIO_SRC / "web" / "templates"
        app = Flask("chat-runtime-tests", template_folder=str(template_dir))
        app.config["TESTING"] = True
        app.secret_key = "chat-runtime-tests"
        app.register_blueprint(studio_views.bp)
        self.client = app.test_client()

    def _create_model(
        self,
        *,
        name: str,
        provider: str = "vllm_remote",
        context_window_tokens: int = 256,
    ) -> LLMModel:
        with session_scope() as session:
            model = LLMModel.create(
                session,
                name=name,
                description=f"{name} description",
                provider=provider,
                config_json=json.dumps(
                    {
                        "model": "stub-model",
                        "context_window_tokens": context_window_tokens,
                    }
                ),
            )
            return model

    def _create_mcp_server(self, *, name: str = "MCP Test") -> MCPServer:
        with session_scope() as session:
            return MCPServer.create(
                session,
                name=name,
                server_key="mcp-test",
                description="test",
                config_json=json.dumps({"command": "python3", "args": ["-V"]}),
                server_type="custom",
            )

    def test_thread_lifecycle_and_hard_delete(self) -> None:
        model = self._create_model(name="Lifecycle Model")
        thread = create_thread(title="Lifecycle", model_id=model.id)
        thread_id = int(thread["id"])

        self.assertTrue(any(item["id"] == thread_id for item in list_threads(include_archived=True)))
        self.assertTrue(archive_thread(thread_id))
        self.assertEqual([], [item for item in list_threads() if item["id"] == thread_id])
        self.assertTrue(restore_thread(thread_id))
        self.assertTrue(delete_thread(thread_id))
        self.assertIsNone(get_thread(thread_id))

        with session_scope() as session:
            self.assertEqual(
                0,
                session.execute(
                    select(func.count(ChatThread.id)).where(ChatThread.id == thread_id)
                ).scalar_one(),
            )

    def test_execute_turn_session_model_binding_and_audit(self) -> None:
        model = self._create_model(name="Bound Model")
        thread = create_thread(title="Bound", model_id=model.id)
        thread_id = int(thread["id"])

        captured_prompts: list[str] = []

        def _fake_llm(*args, **kwargs):
            captured_prompts.append(str(args[1] if len(args) > 1 else kwargs.get("prompt", "")))
            return subprocess.CompletedProcess(["stub"], 0, "assistant reply", "")

        with patch("chat.runtime._run_llm", side_effect=_fake_llm):
            result = execute_turn(thread_id=thread_id, message="Hello session model")

        self.assertTrue(result.ok)
        self.assertIn("Hello session model", captured_prompts[0])
        payload = get_thread(thread_id) or {}
        self.assertEqual(model.id, payload.get("model_id"))
        self.assertEqual("assistant", payload["messages"][-1]["role"])

        events = list_activity(thread_id=thread_id)
        event_types = {item["event_type"] for item in events}
        self.assertIn("turn_requested", event_types)
        self.assertIn("turn_responded", event_types)

    def test_rag_required_unavailable_failure_contract(self) -> None:
        model = self._create_model(name="RAG Model")
        thread = create_thread(
            title="RAG Unavailable",
            model_id=model.id,
            rag_collections=["docs"],
        )
        thread_id = int(thread["id"])

        rag_client = StubRAGContractClient()
        rag_client.health_result.state = RAG_HEALTH_CONFIGURED_UNHEALTHY

        with patch("chat.runtime._run_llm") as mocked_llm:
            result = execute_turn(
                thread_id=thread_id,
                message="Need retrieval",
                rag_client=rag_client,
            )

        self.assertFalse(result.ok)
        self.assertEqual(RAG_REASON_UNAVAILABLE, result.reason_code)
        mocked_llm.assert_not_called()
        with session_scope() as session:
            turn = session.execute(
                select(ChatTurn).where(ChatTurn.id == result.turn_id)
            ).scalars().first()
            self.assertIsNotNone(turn)
            self.assertEqual(CHAT_TURN_STATUS_FAILED, turn.status if turn else None)

    def test_citation_metadata_persisted_but_not_prompt_context(self) -> None:
        model = self._create_model(name="Citation Model")
        thread = create_thread(
            title="Citation",
            model_id=model.id,
            rag_collections=["docs"],
        )
        thread_id = int(thread["id"])

        rag_client = StubRAGContractClient()
        rag_client.health_result.state = RAG_HEALTH_CONFIGURED_HEALTHY
        rag_client.retrieval_response.retrieval_context = ["retrieved context line"]
        rag_client.retrieval_response.citation_records = [
            {
                "provider": "chroma",
                "collection": "docs",
                "source_id": "src-1",
                "snippet": "sensitive citation snippet",
            }
        ]

        captured_prompt: list[str] = []

        def _fake_llm(*args, **kwargs):
            captured_prompt.append(str(args[1] if len(args) > 1 else kwargs.get("prompt", "")))
            return subprocess.CompletedProcess(["stub"], 0, "answer", "")

        with patch("chat.runtime._run_llm", side_effect=_fake_llm):
            result = execute_turn(
                thread_id=thread_id,
                message="question",
                rag_client=rag_client,
            )

        self.assertTrue(result.ok)
        prompt = captured_prompt[0]
        self.assertIn("retrieved context line", prompt)
        self.assertNotIn("sensitive citation snippet", prompt)

        with session_scope() as session:
            turn = session.execute(
                select(ChatTurn).where(ChatTurn.id == result.turn_id)
            ).scalars().first()
            self.assertIsNotNone(turn)
            citation_payload = json.loads(turn.citation_metadata_json or "[]") if turn else []
            self.assertEqual(1, len(citation_payload))

    def test_mcp_failure_propagates_turn_failure(self) -> None:
        model = self._create_model(name="MCP Model")
        server = self._create_mcp_server()
        thread = create_thread(
            title="MCP Failure",
            model_id=model.id,
            mcp_server_ids=[server.id],
        )
        thread_id = int(thread["id"])

        with patch(
            "chat.runtime._run_llm",
            return_value=subprocess.CompletedProcess(["stub"], 1, "", "mcp failed"),
        ):
            result = execute_turn(thread_id=thread_id, message="trigger mcp")

        self.assertFalse(result.ok)
        self.assertEqual(CHAT_REASON_MCP_FAILED, result.reason_code)

    def test_context_auto_compaction_persists_summary_and_activity(self) -> None:
        model = self._create_model(name="Compaction Model", context_window_tokens=60)
        save_chat_runtime_settings(
            {
                "history_budget_percent": "60",
                "rag_budget_percent": "20",
                "compaction_trigger_percent": "100",
                "compaction_target_percent": "70",
                "preserve_recent_turns": "1",
                "default_context_window_tokens": "60",
                "max_compaction_summary_chars": "500",
            }
        )
        thread = create_thread(title="Compaction", model_id=model.id)
        thread_id = int(thread["id"])

        with session_scope() as session:
            for idx in range(5):
                ChatMessage.create(
                    session,
                    thread_id=thread_id,
                    role="user" if idx % 2 == 0 else "assistant",
                    content=f"historical message {idx} " + ("x" * 80),
                    token_estimate=20,
                    metadata_json="{}",
                )

        with patch(
            "chat.runtime._run_llm",
            return_value=subprocess.CompletedProcess(["stub"], 0, "compact ok", ""),
        ):
            result = execute_turn(thread_id=thread_id, message="new input")

        self.assertTrue(result.ok)
        payload = get_thread(thread_id) or {}
        summary_text = str(payload.get("compaction_summary_text") or "")
        self.assertTrue(summary_text)
        self.assertTrue(payload.get("latest_turn", {}).get("compaction_applied"))
        events = list_activity(thread_id=thread_id, event_class="compaction")
        self.assertTrue(events)

    def test_clear_resets_thread_state(self) -> None:
        model = self._create_model(name="Clear Model")
        thread = create_thread(title="Clear", model_id=model.id)
        thread_id = int(thread["id"])
        with patch(
            "chat.runtime._run_llm",
            return_value=subprocess.CompletedProcess(["stub"], 0, "reply", ""),
        ):
            execute_turn(thread_id=thread_id, message="first")
        self.assertTrue(clear_thread(thread_id))
        payload = get_thread(thread_id) or {}
        self.assertEqual([], payload.get("messages"))
        self.assertEqual("", payload.get("compaction_summary_text"))

    def test_api_turn_rejects_session_override_fields(self) -> None:
        model = self._create_model(name="API Model")
        thread = create_thread(title="API", model_id=model.id)
        thread_id = int(thread["id"])
        response = self.client.post(
            f"/api/chat/threads/{thread_id}/turn",
            json={"message": "hello", "model_id": model.id},
        )
        self.assertEqual(400, response.status_code)
        payload = response.get_json() or {}
        self.assertEqual("CHAT_SESSION_SCOPE_SELECTOR_OVERRIDE", payload.get("reason_code"))

    def test_runtime_settings_route_updates_global_scope(self) -> None:
        response = self.client.post(
            "/settings/runtime/chat",
            data={
                "history_budget_percent": "55",
                "rag_budget_percent": "20",
                "mcp_budget_percent": "25",
                "compaction_trigger_percent": "100",
                "compaction_target_percent": "80",
                "preserve_recent_turns": "3",
                "rag_top_k": "9",
                "default_context_window_tokens": "12345",
                "max_compaction_summary_chars": "900",
            },
            follow_redirects=False,
        )
        self.assertEqual(302, response.status_code)
        payload = load_chat_runtime_settings_payload()
        self.assertEqual("55", payload["history_budget_percent"])
        self.assertEqual("20", payload["rag_budget_percent"])
        self.assertEqual("25", payload["mcp_budget_percent"])
        with session_scope() as session:
            rows = session.execute(
                select(IntegrationSetting).where(
                    IntegrationSetting.provider == "chat_runtime"
                )
            ).scalars().all()
            self.assertTrue(rows)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from unittest.mock import patch

from flask import Flask
from sqlalchemy import func, select
import psycopg

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
STUDIO_APP_ROOT = REPO_ROOT / "app" / "llmctl-studio-backend"
LEGACY_TEMPLATE_DIR = REPO_ROOT / "_legacy" / "llmctl-studio-backend" / "src" / "web" / "templates"
if (STUDIO_SRC / "web" / "templates").exists():
    TEMPLATE_DIR = STUDIO_SRC / "web" / "templates"
else:
    TEMPLATE_DIR = LEGACY_TEMPLATE_DIR
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))
if str(STUDIO_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(STUDIO_APP_ROOT))

import core.db as core_db
from chat.contracts import (
    CHAT_REASON_MCP_FAILED,
    RAGContractError,
    RAG_HEALTH_CONFIGURED_HEALTHY,
    RAG_HEALTH_CONFIGURED_UNHEALTHY,
    RAG_REASON_RETRIEVAL_FAILED,
    RAG_REASON_UNAVAILABLE,
)
from chat.rag_client import StubRAGContractClient
from chat.runtime import (
    _derive_thread_title,
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
    load_chat_default_settings_payload,
    load_chat_runtime_settings_payload,
    save_chat_default_settings,
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
from services.integrations import save_integration_settings
from rag.web import views as rag_views
from web import views as studio_views

os.environ.setdefault(
    "LLMCTL_STUDIO_DATABASE_URI",
    "postgresql+psycopg://llmctl:llmctl@127.0.0.1:15432/llmctl_studio",
)


class StudioDbTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp_dir = Path(self._tmp.name)
        self._base_db_uri = os.environ["LLMCTL_STUDIO_DATABASE_URI"]
        self._schema_name = f"chat_runtime_stage8_{uuid.uuid4().hex}"
        self._orig_db_uri = Config.SQLALCHEMY_DATABASE_URI
        self._orig_data_dir = Config.DATA_DIR
        self._create_schema(self._schema_name)
        Config.SQLALCHEMY_DATABASE_URI = self._with_search_path(
            self._base_db_uri,
            self._schema_name,
        )
        Config.DATA_DIR = str(tmp_dir / "data")
        Path(Config.DATA_DIR).mkdir(parents=True, exist_ok=True)
        self._reset_engine()

    def tearDown(self) -> None:
        self._dispose_engine()
        self._drop_schema(self._schema_name)
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

    @staticmethod
    def _as_psycopg_uri(database_uri: str) -> str:
        if database_uri.startswith("postgresql+psycopg://"):
            return "postgresql://" + database_uri.split("://", 1)[1]
        return database_uri

    @staticmethod
    def _with_search_path(database_uri: str, schema_name: str) -> str:
        parts = urlsplit(database_uri)
        query_items = parse_qsl(parts.query, keep_blank_values=True)
        updated_items: list[tuple[str, str]] = []
        options_value = f"-csearch_path={schema_name}"
        options_updated = False
        for key, value in query_items:
            if key == "options":
                merged = value.strip()
                if options_value not in merged:
                    merged = f"{merged} {options_value}".strip()
                updated_items.append((key, merged))
                options_updated = True
            else:
                updated_items.append((key, value))
        if not options_updated:
            updated_items.append(("options", options_value))
        query = urlencode(updated_items, doseq=True)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))

    def _create_schema(self, schema_name: str) -> None:
        with psycopg.connect(self._as_psycopg_uri(self._base_db_uri), autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"')

    def _drop_schema(self, schema_name: str) -> None:
        with psycopg.connect(self._as_psycopg_uri(self._base_db_uri), autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')


class ChatRuntimeStage8Tests(StudioDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        app = Flask("chat-runtime-tests", template_folder=str(TEMPLATE_DIR))
        app.config["TESTING"] = True
        app.secret_key = "chat-runtime-tests"
        app.register_blueprint(studio_views.bp)
        app.register_blueprint(rag_views.bp)
        if "agents.list_task_templates" not in app.view_functions:
            app.add_url_rule(
                "/_test/list-task-templates",
                endpoint="agents.list_task_templates",
                view_func=lambda: "",
            )
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

    def _create_mcp_server(
        self,
        *,
        name: str = "MCP Test",
        server_key: str = "mcp-test",
    ) -> MCPServer:
        with session_scope() as session:
            return MCPServer.create(
                session,
                name=name,
                server_key=server_key,
                description="test",
                config_json=json.dumps({"command": "python3", "args": ["-V"]}),
                server_type="custom",
            )

    def test_thread_lifecycle_and_hard_delete(self) -> None:
        model = self._create_model(name="Lifecycle Model")
        thread = create_thread(title="Lifecycle", model_id=model.id)
        thread_id = int(thread["id"])
        self.assertEqual("medium", thread.get("response_complexity"))

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

    def test_derive_thread_title_from_question_prompt(self) -> None:
        title = _derive_thread_title(
            "how do i set up rag retrieval for api docs in python?"
        )
        self.assertEqual("Set Up RAG Retrieval for API Docs in Python", title)

    def test_execute_turn_auto_titles_default_thread(self) -> None:
        model = self._create_model(name="Auto Title Model")
        thread = create_thread(title="", model_id=model.id)
        thread_id = int(thread["id"])

        with patch(
            "chat.runtime._run_llm",
            return_value=subprocess.CompletedProcess(["stub"], 0, "assistant reply", ""),
        ):
            result = execute_turn(
                thread_id=thread_id,
                message="how do i configure rag retrieval fallback for api responses?",
            )

        self.assertTrue(result.ok)
        payload = get_thread(thread_id) or {}
        self.assertEqual(
            "Configure RAG Retrieval Fallback for API Responses",
            payload.get("title"),
        )

    def test_execute_turn_auto_titles_legacy_default_thread(self) -> None:
        model = self._create_model(name="Legacy Auto Title Model")
        thread = create_thread(title="New chat", model_id=model.id)
        thread_id = int(thread["id"])

        with patch(
            "chat.runtime._run_llm",
            return_value=subprocess.CompletedProcess(["stub"], 0, "assistant reply", ""),
        ):
            result = execute_turn(
                thread_id=thread_id,
                message="how do i configure rag retrieval fallback for api responses?",
            )

        self.assertTrue(result.ok)
        payload = get_thread(thread_id) or {}
        self.assertEqual(
            "Configure RAG Retrieval Fallback for API Responses",
            payload.get("title"),
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

    def test_execute_turn_applies_response_complexity_prompting(self) -> None:
        model = self._create_model(name="Complexity Model")
        thread = create_thread(
            title="Complexity",
            model_id=model.id,
            response_complexity="extra_high",
        )
        thread_id = int(thread["id"])

        captured_prompt: list[str] = []

        def _fake_llm(*args, **kwargs):
            captured_prompt.append(str(args[1] if len(args) > 1 else kwargs.get("prompt", "")))
            return subprocess.CompletedProcess(["stub"], 0, "assistant reply", "")

        with patch("chat.runtime._run_llm", side_effect=_fake_llm):
            result = execute_turn(
                thread_id=thread_id,
                message="Give me a complete breakdown.",
            )

        self.assertTrue(result.ok)
        self.assertTrue(captured_prompt)
        prompt = captured_prompt[0]
        self.assertIn("Response complexity: EXTRA HIGH", prompt)
        self.assertIn("Use Markdown when it improves clarity", prompt)

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

    def test_rag_health_timeout_returns_failure_result(self) -> None:
        model = self._create_model(name="RAG Health Timeout Model")
        thread = create_thread(
            title="RAG Health Timeout",
            model_id=model.id,
            rag_collections=["docs"],
        )
        thread_id = int(thread["id"])

        class _HealthTimeoutRagClient:
            def health(self):
                raise RAGContractError(
                    reason_code=RAG_REASON_RETRIEVAL_FAILED,
                    message="health timeout",
                )

            def retrieve(self, payload):
                raise AssertionError("retrieve should not be called when health fails")

        with patch("chat.runtime._run_llm") as mocked_llm:
            result = execute_turn(
                thread_id=thread_id,
                message="Need retrieval",
                rag_client=_HealthTimeoutRagClient(),
            )

        self.assertFalse(result.ok)
        self.assertEqual(RAG_REASON_RETRIEVAL_FAILED, result.reason_code)
        self.assertEqual("health timeout", result.error)
        mocked_llm.assert_not_called()

    def test_rag_selected_without_retrieval_context_fails_closed(self) -> None:
        model = self._create_model(name="RAG Empty Context Model")
        thread = create_thread(
            title="RAG Empty Context",
            model_id=model.id,
            rag_collections=["docs"],
        )
        thread_id = int(thread["id"])

        rag_client = StubRAGContractClient()
        rag_client.health_result.state = RAG_HEALTH_CONFIGURED_HEALTHY
        rag_client.retrieval_response.retrieval_context = []

        with patch("chat.runtime._run_llm") as mocked_llm:
            result = execute_turn(
                thread_id=thread_id,
                message="Need repo-specific answer",
                rag_client=rag_client,
            )

        self.assertFalse(result.ok)
        self.assertEqual(RAG_REASON_UNAVAILABLE, result.reason_code)
        self.assertIn(
            "No retrieval context was found for selected collections.",
            str(result.error),
        )
        mocked_llm.assert_not_called()

    def test_rag_selected_without_retrieval_context_allows_turn_with_mcp(self) -> None:
        model = self._create_model(name="RAG Empty Context With MCP Model")
        server = self._create_mcp_server(name="MCP With Empty RAG", server_key="github")
        thread = create_thread(
            title="RAG Empty Context With MCP",
            model_id=model.id,
            rag_collections=["docs"],
            mcp_server_ids=[server.id],
        )
        thread_id = int(thread["id"])

        rag_client = StubRAGContractClient()
        rag_client.health_result.state = RAG_HEALTH_CONFIGURED_HEALTHY
        rag_client.retrieval_response.retrieval_context = []

        with patch(
            "chat.runtime._run_llm",
            return_value=subprocess.CompletedProcess(["stub"], 0, "assistant reply", ""),
        ) as mocked_llm:
            result = execute_turn(
                thread_id=thread_id,
                message="summarize repo and github status",
                rag_client=rag_client,
            )

        self.assertTrue(result.ok)
        mocked_llm.assert_called_once()
        with session_scope() as session:
            turn = session.execute(
                select(ChatTurn).where(ChatTurn.id == result.turn_id)
            ).scalars().first()
            self.assertIsNotNone(turn)
            runtime_metadata = json.loads(turn.runtime_metadata_json or "{}") if turn else {}
            retrieval_stats = runtime_metadata.get("retrieval_stats") or {}
            self.assertTrue(
                retrieval_stats.get("rag_context_missing_for_selected_collections")
            )
            self.assertEqual(["github"], runtime_metadata.get("selected_mcp_servers"))

    def test_rag_retrieval_request_disables_answer_synthesis(self) -> None:
        model = self._create_model(name="RAG Retrieval Request Model")
        thread = create_thread(
            title="RAG Retrieval Request",
            model_id=model.id,
            rag_collections=["docs"],
        )
        thread_id = int(thread["id"])
        captured_payload: dict[str, object] = {}

        class _CaptureRagClient:
            def health(self):
                return type(
                    "Health",
                    (),
                    {
                        "state": RAG_HEALTH_CONFIGURED_HEALTHY,
                        "provider": "chroma",
                        "error": None,
                    },
                )()

            def retrieve(self, payload):
                captured_payload["request"] = payload
                return type(
                    "RetrievalResponse",
                    (),
                    {
                        "retrieval_context": ["retrieved context"],
                        "citation_records": [],
                        "retrieval_stats": {"provider": "chroma", "retrieved_count": 1},
                    },
                )()

        with patch(
            "chat.runtime._run_llm",
            return_value=subprocess.CompletedProcess(["stub"], 0, "assistant reply", ""),
        ):
            result = execute_turn(
                thread_id=thread_id,
                message="Need retrieval",
                rag_client=_CaptureRagClient(),
            )

        self.assertTrue(result.ok)
        request_payload = captured_payload.get("request")
        self.assertIsNotNone(request_payload)
        self.assertFalse(getattr(request_payload, "synthesize_answer"))

    def test_rag_retrieval_request_scopes_to_mentioned_collection(self) -> None:
        model = self._create_model(name="RAG Retrieval Scope Model")
        thread = create_thread(
            title="RAG Retrieval Scope",
            model_id=model.id,
            rag_collections=["drive_2", "example_1"],
        )
        thread_id = int(thread["id"])
        captured_payload: dict[str, object] = {}

        class _CaptureRagClient:
            def health(self):
                return type(
                    "Health",
                    (),
                    {
                        "state": RAG_HEALTH_CONFIGURED_HEALTHY,
                        "provider": "chroma",
                        "error": None,
                    },
                )()

            def retrieve(self, payload):
                captured_payload["request"] = payload
                return type(
                    "RetrievalResponse",
                    (),
                    {
                        "retrieval_context": ["retrieved context"],
                        "citation_records": [{"collection": "example_1", "retrieval_rank": 1}],
                        "retrieval_stats": {"provider": "chroma", "retrieved_count": 1},
                    },
                )()

        with patch(
            "chat.runtime._run_llm",
            return_value=subprocess.CompletedProcess(["stub"], 0, "assistant reply", ""),
        ):
            result = execute_turn(
                thread_id=thread_id,
                message="tell me about files in example_1",
                rag_client=_CaptureRagClient(),
            )

        self.assertTrue(result.ok)
        request_payload = captured_payload.get("request")
        self.assertIsNotNone(request_payload)
        self.assertEqual(["example_1"], list(getattr(request_payload, "collections", [])))

    def test_rag_retrieval_unexpected_error_returns_failure_result(self) -> None:
        model = self._create_model(name="RAG Unexpected Error Model")
        thread = create_thread(
            title="RAG Unexpected Error",
            model_id=model.id,
            rag_collections=["docs"],
        )
        thread_id = int(thread["id"])

        class _BrokenRagClient:
            def health(self):
                return type("Health", (), {"state": RAG_HEALTH_CONFIGURED_HEALTHY, "provider": "chroma"})()

            def retrieve(self, payload):
                raise TimeoutError("timed out")

        with patch("chat.runtime._run_llm") as mocked_llm:
            result = execute_turn(
                thread_id=thread_id,
                message="Need retrieval",
                rag_client=_BrokenRagClient(),
            )

        self.assertFalse(result.ok)
        self.assertEqual(RAG_REASON_RETRIEVAL_FAILED, result.reason_code)
        self.assertEqual("RAG retrieval failed unexpectedly.", result.error)
        mocked_llm.assert_not_called()

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
        self.assertIn("Retrieved source map:", prompt)
        self.assertIn("collection=docs", prompt)
        self.assertNotIn("sensitive citation snippet", prompt)

        with session_scope() as session:
            turn = session.execute(
                select(ChatTurn).where(ChatTurn.id == result.turn_id)
            ).scalars().first()
            self.assertIsNotNone(turn)
            citation_payload = json.loads(turn.citation_metadata_json or "[]") if turn else []
            self.assertEqual(1, len(citation_payload))

    def test_explicit_file_hint_scopes_retrieval_context_for_selected_collection(self) -> None:
        model = self._create_model(name="Scoped Retrieval Model")
        thread = create_thread(
            title="Scoped Retrieval",
            model_id=model.id,
            rag_collections=["drive_2"],
        )
        thread_id = int(thread["id"])

        rag_client = StubRAGContractClient()
        rag_client.health_result.state = RAG_HEALTH_CONFIGURED_HEALTHY
        rag_client.retrieval_response.retrieval_context = [
            "Context from an unrelated document.",
            "Context for the newly indexed delta probe.",
        ]
        rag_client.retrieval_response.citation_records = [
            {
                "collection": "drive_2",
                "path": "sample_ocr_vector_points_demo.pdf",
                "retrieval_rank": 1,
            },
            {
                "collection": "drive_2",
                "path": "sample_delta_index_probe_20260218_062251Z.pdf",
                "retrieval_rank": 2,
            },
        ]

        captured_prompt: list[str] = []

        def _fake_llm(*args, **kwargs):
            captured_prompt.append(str(args[1] if len(args) > 1 else kwargs.get("prompt", "")))
            return subprocess.CompletedProcess(["stub"], 0, "answer", "")

        with patch("chat.runtime._run_llm", side_effect=_fake_llm):
            result = execute_turn(
                thread_id=thread_id,
                message=(
                    "What does sample_delta_index_probe_20260218_062251Z.pdf say?"
                ),
                rag_client=rag_client,
            )

        self.assertTrue(result.ok)
        prompt = captured_prompt[0]
        self.assertIn("Context for the newly indexed delta probe.", prompt)
        self.assertNotIn("Context from an unrelated document.", prompt)
        self.assertIn("sample_delta_index_probe_20260218_062251Z.pdf", prompt)
        self.assertNotIn("sample_ocr_vector_points_demo.pdf", prompt)

    def test_collection_name_hint_scopes_retrieval_context(self) -> None:
        model = self._create_model(name="Collection Hint Scope Model")
        thread = create_thread(
            title="Collection Hint Scope",
            model_id=model.id,
            rag_collections=["drive_2", "example_1"],
        )
        thread_id = int(thread["id"])

        rag_client = StubRAGContractClient()
        rag_client.health_result.state = RAG_HEALTH_CONFIGURED_HEALTHY
        rag_client.retrieval_response.retrieval_context = [
            "Drive collection context.",
            "Example collection context.",
        ]
        rag_client.retrieval_response.citation_records = [
            {
                "collection": "drive_2",
                "path": "drive_notes.md",
                "retrieval_rank": 1,
            },
            {
                "collection": "example_1",
                "path": "example_notes.md",
                "retrieval_rank": 2,
            },
        ]

        captured_prompt: list[str] = []

        def _fake_llm(*args, **kwargs):
            captured_prompt.append(str(args[1] if len(args) > 1 else kwargs.get("prompt", "")))
            return subprocess.CompletedProcess(["stub"], 0, "answer", "")

        with patch("chat.runtime._run_llm", side_effect=_fake_llm):
            result = execute_turn(
                thread_id=thread_id,
                message="Tell me generally about files in example_1.",
                rag_client=rag_client,
            )

        self.assertTrue(result.ok)
        prompt = captured_prompt[0]
        self.assertIn("Example collection context.", prompt)
        self.assertNotIn("Drive collection context.", prompt)
        self.assertIn("collection=example_1", prompt)
        self.assertNotIn("collection=drive_2", prompt)

    def test_collection_name_hint_scopes_for_nonword_collection_name(self) -> None:
        model = self._create_model(name="Collection Hint Nonword Scope Model")
        thread = create_thread(
            title="Collection Hint Nonword Scope",
            model_id=model.id,
            rag_collections=["TeSt / Collection (Prod)", "drive_2"],
        )
        thread_id = int(thread["id"])

        rag_client = StubRAGContractClient()
        rag_client.health_result.state = RAG_HEALTH_CONFIGURED_HEALTHY
        rag_client.retrieval_response.retrieval_context = [
            "Nonword collection context.",
            "Drive collection context.",
        ]
        rag_client.retrieval_response.citation_records = [
            {
                "collection": "TeSt / Collection (Prod)",
                "path": "prod_notes.md",
                "retrieval_rank": 1,
            },
            {
                "collection": "drive_2",
                "path": "drive_notes.md",
                "retrieval_rank": 2,
            },
        ]

        captured_prompt: list[str] = []

        def _fake_llm(*args, **kwargs):
            captured_prompt.append(str(args[1] if len(args) > 1 else kwargs.get("prompt", "")))
            return subprocess.CompletedProcess(["stub"], 0, "answer", "")

        with patch("chat.runtime._run_llm", side_effect=_fake_llm):
            result = execute_turn(
                thread_id=thread_id,
                message="Can you summarize test collection prod?",
                rag_client=rag_client,
            )

        self.assertTrue(result.ok)
        prompt = captured_prompt[0]
        self.assertIn("Nonword collection context.", prompt)
        self.assertNotIn("Drive collection context.", prompt)
        self.assertIn("collection=TeSt / Collection (Prod)", prompt)
        self.assertNotIn("collection=drive_2", prompt)

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

    def test_execute_turn_includes_atlassian_defaults_for_selected_mcp(self) -> None:
        model = self._create_model(name="Atlassian Prompt Model")
        server = self._create_mcp_server(name="Atlassian MCP", server_key="atlassian")
        save_integration_settings(
            "jira",
            {
                "site": "https://example.atlassian.net",
                "project_key": "OPS",
                "board": "42",
                "board_label": "Platform Board",
            },
        )
        save_integration_settings(
            "confluence",
            {
                "site": "https://example.atlassian.net/wiki",
                "space": "ENG",
            },
        )
        thread = create_thread(
            title="Atlassian Context",
            model_id=model.id,
            mcp_server_ids=[server.id],
        )
        thread_id = int(thread["id"])

        captured_prompt: list[str] = []

        def _fake_llm(*args, **kwargs):
            captured_prompt.append(
                str(args[1] if len(args) > 1 else kwargs.get("prompt", ""))
            )
            return subprocess.CompletedProcess(["stub"], 0, "assistant reply", "")

        with patch("chat.runtime._run_llm", side_effect=_fake_llm):
            result = execute_turn(thread_id=thread_id, message="show jira updates")

        self.assertTrue(result.ok)
        self.assertTrue(captured_prompt)
        prompt = captured_prompt[0]
        self.assertIn("Integration defaults for enabled MCP servers", prompt)
        self.assertIn("Jira defaults:", prompt)
        self.assertIn("project key OPS", prompt)
        self.assertIn("board Platform Board", prompt)
        self.assertIn("Confluence defaults:", prompt)
        self.assertIn("space ENG", prompt)

    def test_execute_turn_includes_github_and_chroma_defaults_for_selected_mcp(self) -> None:
        model = self._create_model(name="GitHub Chroma Prompt Model")
        github_server = self._create_mcp_server(name="GitHub MCP", server_key="github")
        chroma_server = self._create_mcp_server(name="Chroma MCP", server_key="chroma")
        save_integration_settings("github", {"repo": "acme/platform"})
        save_integration_settings(
            "chroma",
            {"host": "chroma.internal", "port": "8443", "ssl": "true"},
        )
        thread = create_thread(
            title="GitHub + Chroma Context",
            model_id=model.id,
            mcp_server_ids=[github_server.id, chroma_server.id],
        )
        thread_id = int(thread["id"])

        captured_prompt: list[str] = []

        def _fake_llm(*args, **kwargs):
            captured_prompt.append(
                str(args[1] if len(args) > 1 else kwargs.get("prompt", ""))
            )
            return subprocess.CompletedProcess(["stub"], 0, "assistant reply", "")

        with patch("chat.runtime._run_llm", side_effect=_fake_llm):
            result = execute_turn(
                thread_id=thread_id,
                message="summarize repo and vector settings",
            )

        self.assertTrue(result.ok)
        self.assertTrue(captured_prompt)
        prompt = captured_prompt[0]
        self.assertIn("Integration defaults for enabled MCP servers", prompt)
        self.assertIn("GitHub default repository: acme/platform.", prompt)
        self.assertIn("ChromaDB defaults:", prompt)
        self.assertIn("host chroma.internal", prompt)
        self.assertIn("port 8443", prompt)
        self.assertIn("ssl true", prompt)

    def test_execute_turn_includes_google_tool_verification_guidance(self) -> None:
        model = self._create_model(name="Google Prompt Model")
        cloud_server = self._create_mcp_server(
            name="Google Cloud MCP",
            server_key="google-cloud",
        )
        workspace_server = self._create_mcp_server(
            name="Google Workspace MCP",
            server_key="google-workspace",
        )
        save_integration_settings(
            "google_cloud",
            {"google_cloud_project_id": "demo-project"},
        )
        save_integration_settings(
            "google_workspace",
            {"workspace_delegated_user_email": "user@example.com"},
        )
        thread = create_thread(
            title="Google Context",
            model_id=model.id,
            mcp_server_ids=[cloud_server.id, workspace_server.id],
        )
        thread_id = int(thread["id"])

        captured_prompt: list[str] = []

        def _fake_llm(*args, **kwargs):
            captured_prompt.append(
                str(args[1] if len(args) > 1 else kwargs.get("prompt", ""))
            )
            return subprocess.CompletedProcess(["stub"], 0, "assistant reply", "")

        with patch("chat.runtime._run_llm", side_effect=_fake_llm):
            result = execute_turn(
                thread_id=thread_id,
                message="verify google mcp servers",
            )

        self.assertTrue(result.ok)
        self.assertTrue(captured_prompt)
        prompt = captured_prompt[0]
        self.assertIn("Integration defaults for enabled MCP servers", prompt)
        self.assertIn("Google Cloud default project_id: demo-project.", prompt)
        self.assertIn("Google Workspace delegated user: user@example.com.", prompt)
        self.assertIn("Google Cloud MCP is tool-centric:", prompt)
        self.assertIn("Google Workspace MCP is tool-centric:", prompt)
        self.assertIn("Do not require resources/list.", prompt)

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
        for payload in (
            {"message": "hello", "model_id": model.id},
            {"message": "hello", "response_complexity": "high"},
        ):
            response = self.client.post(
                f"/api/chat/threads/{thread_id}/turn",
                json=payload,
            )
            self.assertEqual(400, response.status_code)
            body = response.get_json() or {}
            self.assertEqual("CHAT_SESSION_SCOPE_SELECTOR_OVERRIDE", body.get("reason_code"))

    def test_api_chat_thread_config_updates_session_scope_selectors(self) -> None:
        model = self._create_model(name="Session API Model")
        mcp_server = self._create_mcp_server(name="Session API MCP")
        thread = create_thread(title="Session API Thread", model_id=model.id)
        thread_id = int(thread["id"])

        response = self.client.post(
            f"/api/chat/threads/{thread_id}/config",
            json={
                "model_id": model.id,
                "response_complexity": "high",
                "mcp_server_ids": [mcp_server.id],
                "rag_collections": ["example_1"],
            },
        )
        self.assertEqual(200, response.status_code)
        body = response.get_json() or {}
        self.assertTrue(body.get("ok"))
        payload = get_thread(thread_id) or {}
        self.assertEqual("high", payload.get("response_complexity"))
        self.assertEqual(["example_1"], payload.get("rag_collections"))
        self.assertEqual(
            [mcp_server.id],
            [item["id"] for item in payload.get("mcp_servers", [])],
        )

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
        self.assertTrue((response.headers.get("Location") or "").endswith("/settings/chat"))
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

    def test_runtime_settings_chat_section_renders_and_preserves_runtime_redirect(self) -> None:
        page = self.client.get("/settings/runtime/chat")
        self.assertEqual(200, page.status_code)
        self.assertIn(b"Chat Runtime Settings", page.data)

        save_response = self.client.post(
            "/settings/runtime/chat",
            data={
                "history_budget_percent": "50",
                "rag_budget_percent": "25",
                "mcp_budget_percent": "25",
                "compaction_trigger_percent": "95",
                "compaction_target_percent": "80",
                "preserve_recent_turns": "3",
                "rag_top_k": "7",
                "default_context_window_tokens": "10000",
                "max_compaction_summary_chars": "700",
                "return_to": "runtime",
            },
            follow_redirects=False,
        )
        self.assertEqual(302, save_response.status_code)
        self.assertTrue(
            (save_response.headers.get("Location") or "").endswith(
                "/settings/runtime/chat"
            )
        )

    def test_settings_chat_page_renders(self) -> None:
        page = self.client.get("/settings/chat")
        self.assertEqual(200, page.status_code)
        self.assertIn(b"Chat Defaults", page.data)

    def test_chat_default_settings_route_persists_defaults(self) -> None:
        model = self._create_model(name="Default Settings Model")
        mcp_server = self._create_mcp_server(name="Default Settings MCP")
        response = self.client.post(
            "/settings/chat/defaults",
            data={
                "default_model_id": str(model.id),
                "default_response_complexity": "high",
                "default_mcp_server_ids": [str(mcp_server.id)],
            },
            follow_redirects=False,
        )
        self.assertEqual(302, response.status_code)
        self.assertTrue((response.headers.get("Location") or "").endswith("/settings/chat"))
        payload = load_chat_default_settings_payload()
        self.assertEqual(model.id, payload["default_model_id"])
        self.assertEqual("high", payload["default_response_complexity"])
        self.assertEqual([mcp_server.id], payload["default_mcp_server_ids"])

    def test_chat_thread_creation_applies_saved_defaults_when_fields_missing(self) -> None:
        model = self._create_model(name="Creation Defaults Model")
        mcp_server = self._create_mcp_server(name="Creation Defaults MCP")
        save_chat_default_settings(
            {
                "default_model_id": str(model.id),
                "default_response_complexity": "high",
                "default_mcp_server_ids": [str(mcp_server.id)],
                "default_rag_collections": ["docs"],
            }
        )
        response = self.client.post(
            "/chat/threads",
            data={"title": "Uses defaults"},
            follow_redirects=False,
        )
        self.assertEqual(302, response.status_code)
        with session_scope() as session:
            thread = (
                session.execute(select(ChatThread).order_by(ChatThread.id.desc()))
                .scalars()
                .first()
            )
            self.assertIsNotNone(thread)
            if thread is not None:
                self.assertEqual(model.id, thread.model_id)
                self.assertEqual("high", thread.response_complexity)
                payload = get_thread(thread.id) or {}
                self.assertEqual(["docs"], payload.get("rag_collections"))
                self.assertEqual(
                    [mcp_server.id],
                    [item["id"] for item in payload.get("mcp_servers", [])],
                )

    def test_chat_page_hides_archived_threads_from_list(self) -> None:
        model = self._create_model(name="Visible Threads Model")
        create_thread(title="Visible Thread", model_id=model.id)
        hidden = create_thread(title="Archived Thread", model_id=model.id)
        self.assertTrue(archive_thread(int(hidden["id"])))

        page = self.client.get("/chat")
        self.assertEqual(200, page.status_code)
        self.assertIn(b"Visible Thread", page.data)
        self.assertNotIn(b"Archived Thread", page.data)

    def test_chat_page_session_controls_render_model_selector(self) -> None:
        selected_model = self._create_model(name="Selected Session Model", provider="codex")
        other_model = self._create_model(name="Other Session Model", provider="gemini")
        thread = create_thread(title="Session model", model_id=selected_model.id)
        thread_id = int(thread["id"])

        page = self.client.get(f"/chat?thread_id={thread_id}")
        self.assertEqual(200, page.status_code)
        self.assertIn(b'<select name="model_id">', page.data)
        self.assertIn(
            f'value="{selected_model.id}" selected'.encode("utf-8"),
            page.data,
        )
        self.assertIn(
            f'value="{other_model.id}"'.encode("utf-8"),
            page.data,
        )

    def test_chat_page_sidebar_uses_settings_defaults_only(self) -> None:
        model = self._create_model(name="Sidebar Defaults Model")
        create_thread(title="Settings-driven thread", model_id=model.id)

        page = self.client.get("/chat")
        self.assertEqual(200, page.status_code)
        self.assertIn(b"new chat", page.data)
        self.assertNotIn(b"thread defaults", page.data)
        self.assertNotIn(b"mcp_selection_present", page.data)
        self.assertNotIn(b"rag_selection_present", page.data)

    def test_chat_thread_creation_blank_model_uses_llm_default(self) -> None:
        default_model = self._create_model(name="LLM Default Model")
        self._create_model(name="Newer Model")
        save_chat_default_settings(
            {
                "default_model_id": "",
                "default_mcp_server_ids": [],
                "default_rag_collections": [],
            }
        )
        save_integration_settings("llm", {"default_model_id": str(default_model.id)})

        response = self.client.post(
            "/chat/threads",
            data={"title": "Uses LLM default", "model_id": ""},
            follow_redirects=False,
        )
        self.assertEqual(302, response.status_code)
        with session_scope() as session:
            thread = (
                session.execute(select(ChatThread).order_by(ChatThread.id.desc()))
                .scalars()
                .first()
            )
            self.assertIsNotNone(thread)
            if thread is not None:
                self.assertEqual(default_model.id, thread.model_id)

    def test_chat_thread_creation_route_persists_response_complexity(self) -> None:
        model = self._create_model(name="Complexity Thread Model")
        response = self.client.post(
            "/chat/threads",
            data={
                "title": "Complexity thread",
                "model_id": str(model.id),
                "response_complexity": "high",
            },
            follow_redirects=False,
        )
        self.assertEqual(302, response.status_code)
        with session_scope() as session:
            thread = (
                session.execute(select(ChatThread).order_by(ChatThread.id.desc()))
                .scalars()
                .first()
            )
            self.assertIsNotNone(thread)
            if thread is not None:
                payload = get_thread(thread.id) or {}
                self.assertEqual("high", payload.get("response_complexity"))

    def test_chat_thread_update_route_preserves_model_when_model_field_missing(self) -> None:
        model = self._create_model(name="Config Preserve Model")
        mcp_server = self._create_mcp_server(name="Config Preserve MCP")
        thread = create_thread(title="Preserve config", model_id=model.id)
        thread_id = int(thread["id"])

        response = self.client.post(
            f"/chat/threads/{thread_id}/config",
            data={
                "response_complexity": "high",
                "mcp_server_ids": [str(mcp_server.id)],
            },
            follow_redirects=False,
        )
        self.assertEqual(302, response.status_code)
        payload = get_thread(thread_id) or {}
        self.assertEqual(model.id, payload.get("model_id"))
        self.assertEqual("high", payload.get("response_complexity"))
        self.assertEqual(
            [mcp_server.id],
            [item["id"] for item in payload.get("mcp_servers", [])],
        )

    def test_execute_turn_unbound_thread_prefers_llm_default_model(self) -> None:
        default_model = self._create_model(name="LLM Default Runtime Model")
        newest_model = self._create_model(name="Newest Runtime Model")
        self.assertNotEqual(default_model.id, newest_model.id)
        save_chat_default_settings(
            {
                "default_model_id": "",
                "default_mcp_server_ids": [],
                "default_rag_collections": [],
            }
        )
        save_integration_settings("llm", {"default_model_id": str(default_model.id)})
        thread = create_thread(title="Runtime default resolution", model_id=None)
        thread_id = int(thread["id"])

        with patch(
            "chat.runtime._run_llm",
            return_value=subprocess.CompletedProcess(["stub"], 0, "resolved", ""),
        ):
            result = execute_turn(thread_id=thread_id, message="resolve model")

        self.assertTrue(result.ok)
        payload = get_thread(thread_id) or {}
        self.assertEqual(default_model.id, payload.get("model_id"))
        with session_scope() as session:
            latest_turn = (
                session.execute(select(ChatTurn).order_by(ChatTurn.id.desc()))
                .scalars()
                .first()
            )
            self.assertIsNotNone(latest_turn)
            if latest_turn is not None:
                self.assertEqual(default_model.id, latest_turn.model_id)


if __name__ == "__main__":
    unittest.main()

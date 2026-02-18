from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from unittest.mock import patch

from flask import Flask
import psycopg

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
LEGACY_TEMPLATE_DIR = REPO_ROOT / "_legacy" / "llmctl-studio-backend" / "src" / "web" / "templates"
if (STUDIO_SRC / "web" / "templates").exists():
    TEMPLATE_DIR = STUDIO_SRC / "web" / "templates"
else:
    TEMPLATE_DIR = LEGACY_TEMPLATE_DIR
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

os.environ.setdefault(
    "LLMCTL_STUDIO_DATABASE_URI",
    "postgresql+psycopg://llmctl:llmctl@127.0.0.1:15432/llmctl_studio",
)

import core.db as core_db
from core.config import Config
from core.db import session_scope
from core.models import (
    FLOWCHART_NODE_TYPE_MEMORY,
    Flowchart,
    FlowchartNode,
    FlowchartRun,
    FlowchartRunNode,
    LLMModel,
    MCPServer,
    Memory,
    NodeArtifact,
    NODE_ARTIFACT_TYPE_MEMORY,
)
from rag.web.views import bp as rag_bp
import web.views as studio_views


class _FakeChromaCollection:
    def __init__(self, name: str):
        self.name = name
        self.metadata = {"owner": "stage8"}

    def count(self) -> int:
        return 12


class _FakeChromaClient:
    def list_collections(self):
        return ["docs", "runbooks"]

    def get_collection(self, name: str):
        return _FakeChromaCollection(name)

    def delete_collection(self, name: str):
        return None


class Stage8ApiRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp_dir = Path(self._tmp.name)
        data_dir = tmp_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        self._orig_data_dir = Config.DATA_DIR
        self._orig_workspaces_dir = Config.WORKSPACES_DIR
        self._orig_db_uri = Config.SQLALCHEMY_DATABASE_URI
        self._base_db_uri = os.environ["LLMCTL_STUDIO_DATABASE_URI"]
        self._schema_name = f"react_stage8_api_{uuid.uuid4().hex}"

        Config.DATA_DIR = str(data_dir)
        Config.WORKSPACES_DIR = str(tmp_dir / "workspaces")
        Path(Config.WORKSPACES_DIR).mkdir(parents=True, exist_ok=True)
        self._create_schema(self._schema_name)
        Config.SQLALCHEMY_DATABASE_URI = self._with_search_path(
            self._base_db_uri,
            self._schema_name,
        )

        self._dispose_engine()
        core_db.init_engine(Config.SQLALCHEMY_DATABASE_URI)
        core_db.init_db()

        app = Flask("stage8-api-tests", template_folder=str(TEMPLATE_DIR))
        app.config["TESTING"] = True
        app.secret_key = "stage8-api"
        app.register_blueprint(studio_views.bp)
        app.register_blueprint(rag_bp)
        app.register_blueprint(studio_views.bp, url_prefix="/api", name="agents_api")
        self.client = app.test_client()

    def tearDown(self) -> None:
        self._dispose_engine()
        self._drop_schema(self._schema_name)
        Config.DATA_DIR = self._orig_data_dir
        Config.WORKSPACES_DIR = self._orig_workspaces_dir
        Config.SQLALCHEMY_DATABASE_URI = self._orig_db_uri
        self._tmp.cleanup()

    def _dispose_engine(self) -> None:
        if core_db._engine is not None:
            core_db._engine.dispose()
        core_db._engine = None
        core_db.SessionLocal = None

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

    def _create_model(
        self,
        *,
        name: str,
        provider: str = "vllm_remote",
        context_window_tokens: int = 256,
    ) -> LLMModel:
        with session_scope() as session:
            return LLMModel.create(
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

    def _create_mcp_server(self, *, name: str = "MCP Test") -> MCPServer:
        with session_scope() as session:
            return MCPServer.create(
                session,
                name=name,
                server_key=f"{name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:8]}",
                description="test",
                config_json=json.dumps({"command": "python3", "args": ["-V"]}),
                server_type="custom",
            )

    def _create_memory(self, *, description: str) -> Memory:
        with session_scope() as session:
            return Memory.create(session, description=description)

    def test_github_workspace_and_pull_request_json(self) -> None:
        def _integration_settings(provider: str):
            if provider == "github":
                return {"repo": "org/repo", "pat": "ghp_test"}
            return {}

        with (
            patch("web.views._load_integration_settings", side_effect=_integration_settings),
            patch("web.views._fetch_github_pull_requests", return_value=[{"number": 9, "title": "Update API", "author": "alice"}]),
            patch("web.views._fetch_github_actions", return_value=[{"name": "CI", "status": "success"}]),
            patch("web.views._fetch_github_contents", return_value={"entries": [{"path": "README.md", "type": "file"}], "file": None}),
            patch("web.views._fetch_github_pull_request_detail", return_value={"number": 9, "title": "Update API", "requested_reviewers": ["bob"]}),
            patch("web.views._fetch_github_pull_request_timeline", return_value=([{"id": 1, "body": "Looks good"}], ["alice"])),
        ):
            listing = self.client.get("/api/github")
            self.assertEqual(200, listing.status_code)
            listing_payload = listing.get_json() or {}
            self.assertTrue(bool(listing_payload.get("pull_requests")))

            detail = self.client.get("/api/github/pulls/9")
            self.assertEqual(200, detail.status_code)
            detail_payload = detail.get_json() or {}
            self.assertEqual(9, int((detail_payload.get("pull_request") or {}).get("number") or 0))

    def test_jira_and_confluence_json(self) -> None:
        def _integration_settings(provider: str):
            if provider == "jira":
                return {
                    "api_key": "jira-key",
                    "email": "owner@example.com",
                    "site": "https://example.atlassian.net",
                    "board": "Platform",
                }
            if provider == "confluence":
                return {
                    "api_key": "conf-key",
                    "email": "owner@example.com",
                    "site": "https://example.atlassian.net/wiki",
                    "space": "ENG",
                }
            return {}

        with (
            patch("web.views._load_integration_settings", side_effect=_integration_settings),
            patch("web.views._fetch_jira_board_by_name", return_value={"id": 11, "type": "scrum", "location": {"projectKey": "OPS"}}),
            patch("web.views._fetch_jira_board_configuration", return_value={"columns": []}),
            patch("web.views._fetch_jira_board_issues", return_value=[{"key": "OPS-1", "summary": "Fix alerts"}]),
            patch("web.views._build_jira_board_columns", return_value=([{"name": "To Do", "issues": [{"key": "OPS-1", "summary": "Fix alerts"}]}], [])),
            patch("web.views._fetch_jira_issue", return_value={"key": "OPS-1", "summary": "Fix alerts"}),
            patch("web.views._fetch_jira_issue_comments", return_value=[{"id": "1", "body": "Investigating"}]),
            patch("web.views._confluence_space_options", return_value=[{"value": "ENG", "label": "ENG - Engineering"}]),
            patch("web.views._fetch_confluence_pages", return_value=[{"id": "123", "title": "Runbook"}]),
            patch("web.views._fetch_confluence_page", return_value={"id": "123", "title": "Runbook", "body_text": "Checklist"}),
        ):
            jira_listing = self.client.get("/api/jira")
            self.assertEqual(200, jira_listing.status_code)
            jira_payload = jira_listing.get_json() or {}
            self.assertTrue(bool(jira_payload.get("board_columns")))

            jira_issue = self.client.get("/api/jira/issues/OPS-1")
            self.assertEqual(200, jira_issue.status_code)
            issue_payload = jira_issue.get_json() or {}
            self.assertEqual("OPS-1", (issue_payload.get("issue") or {}).get("key"))

            confluence_listing = self.client.get("/api/confluence")
            self.assertEqual(200, confluence_listing.status_code)
            confluence_payload = confluence_listing.get_json() or {}
            self.assertEqual("ENG", confluence_payload.get("space_key"))

    def test_confluence_refresh_api_persists_space_options(self) -> None:
        with (
            patch("web.views.sync_integrated_mcp_servers"),
            patch(
                "web.views._fetch_confluence_spaces",
                return_value=[{"value": "LLMCTL", "label": "LLMCTL - LLMCTL"}],
            ),
        ):
            refresh = self.client.post(
                "/api/settings/integrations/confluence",
                json={
                    "action": "refresh",
                    "confluence_api_key": "owner@example.com:token",
                    "confluence_site": "https://example.atlassian.net/wiki",
                },
            )
            self.assertEqual(200, refresh.status_code)
            refresh_payload = refresh.get_json() or {}
            self.assertEqual(
                [{"value": "LLMCTL", "label": "LLMCTL - LLMCTL"}],
                refresh_payload.get("confluence_space_options"),
            )

            listing = self.client.get("/api/settings/integrations/confluence")
            self.assertEqual(200, listing.status_code)
            listing_payload = listing.get_json() or {}
            self.assertEqual(
                [{"value": "LLMCTL", "label": "LLMCTL - LLMCTL"}],
                listing_payload.get("confluence_space_options"),
            )

    def test_chroma_collections_json(self) -> None:
        with (
            patch("web.views._resolved_chroma_settings", return_value={"host": "llmctl-chromadb", "port": "8000", "ssl": "false"}),
            patch("web.views._chroma_connected", return_value=True),
            patch("web.views._chroma_http_client", return_value=(_FakeChromaClient(), "llmctl-chromadb", 8000, None, None)),
        ):
            listing = self.client.get("/api/chroma/collections?page=1&per_page=20")
            self.assertEqual(200, listing.status_code)
            listing_payload = listing.get_json() or {}
            self.assertTrue(bool(listing_payload.get("collections")))

            detail = self.client.get("/api/chroma/collections/detail?name=docs")
            self.assertEqual(200, detail.status_code)
            detail_payload = detail.get_json() or {}
            self.assertEqual("docs", detail_payload.get("collection_name"))

            delete = self.client.post(
                "/api/chroma/collections/delete",
                json={"collection_name": "docs", "next": "detail"},
            )
            self.assertEqual(200, delete.status_code)
            self.assertTrue(bool((delete.get_json() or {}).get("ok")))

    def test_rag_chat_and_sources_json_routes(self) -> None:
        headers = {"Accept": "application/json"}
        meta = self.client.get("/api/rag/chat", headers=headers)
        self.assertEqual(200, meta.status_code)
        meta_payload = meta.get_json() or {}
        self.assertIn("chat_top_k", meta_payload)

        source_name = f"stage8-source-{uuid.uuid4().hex[:8]}"
        create = self.client.post(
            "/api/rag/sources",
            json={
                "name": source_name,
                "kind": "local",
                "local_path": "/workspace/docs",
                "index_schedule_value": "",
                "index_schedule_unit": "",
                "index_schedule_mode": "fresh",
            },
            headers=headers,
        )
        self.assertEqual(201, create.status_code)
        source_id = int(((create.get_json() or {}).get("source") or {}).get("id") or 0)
        self.assertGreater(source_id, 0)

        listing = self.client.get("/api/rag/sources", headers=headers)
        self.assertEqual(200, listing.status_code)
        listing_payload = listing.get_json() or {}
        self.assertTrue(
            any(int(item.get("id") or 0) == source_id for item in (listing_payload.get("sources") or []))
        )

        detail = self.client.get(f"/api/rag/sources/{source_id}", headers=headers)
        self.assertEqual(200, detail.status_code)
        detail_payload = detail.get_json() or {}
        self.assertEqual(source_id, int((detail_payload.get("source") or {}).get("id") or 0))

        edit = self.client.get(f"/api/rag/sources/{source_id}/edit", headers=headers)
        self.assertEqual(200, edit.status_code)

        update = self.client.post(
            f"/api/rag/sources/{source_id}",
            json={
                "name": f"{source_name}-updated",
                "kind": "local",
                "local_path": "/workspace/docs-updated",
                "index_schedule_value": 1,
                "index_schedule_unit": "days",
                "index_schedule_mode": "delta",
            },
            headers=headers,
        )
        self.assertEqual(200, update.status_code)

        delete = self.client.post(f"/api/rag/sources/{source_id}/delete", json={}, headers=headers)
        self.assertEqual(200, delete.status_code)
        self.assertTrue(bool((delete.get_json() or {}).get("ok")))

    def test_chat_runtime_and_thread_mutation_routes(self) -> None:
        model = self._create_model(name="Chat Runtime API Model")
        mcp_server = self._create_mcp_server(name="Runtime MCP")

        create = self.client.post(
            "/api/chat/threads",
            json={
                "title": "Launch Runtime",
                "model_id": model.id,
                "response_complexity": "high",
                "mcp_server_ids": [mcp_server.id],
                "rag_collections": [],
            },
        )
        self.assertEqual(200, create.status_code)
        create_payload = create.get_json() or {}
        self.assertTrue(bool(create_payload.get("ok")))
        thread_payload = create_payload.get("thread") or {}
        thread_id = int(thread_payload.get("id") or 0)
        self.assertGreater(thread_id, 0)

        runtime = self.client.get(f"/api/chat/runtime?thread_id={thread_id}")
        self.assertEqual(200, runtime.status_code)
        runtime_payload = runtime.get_json() or {}
        self.assertEqual(thread_id, int(runtime_payload.get("selected_thread_id") or 0))
        self.assertTrue(any(int(item.get("id") or 0) == model.id for item in runtime_payload.get("models", [])))
        self.assertTrue(any(int(item.get("id") or 0) == mcp_server.id for item in runtime_payload.get("mcp_servers", [])))
        self.assertTrue(any(int(item.get("id") or 0) == thread_id for item in runtime_payload.get("threads", [])))

        clear = self.client.post(f"/api/chat/threads/{thread_id}/clear")
        self.assertEqual(200, clear.status_code)
        clear_payload = clear.get_json() or {}
        self.assertTrue(bool(clear_payload.get("ok")))
        self.assertEqual([], (clear_payload.get("thread") or {}).get("messages"))

        archive = self.client.post(f"/api/chat/threads/{thread_id}/archive")
        self.assertEqual(200, archive.status_code)
        archive_payload = archive.get_json() or {}
        self.assertTrue(bool(archive_payload.get("ok")))
        self.assertEqual(thread_id, int(archive_payload.get("thread_id") or 0))

        runtime_after_archive = self.client.get("/api/chat/runtime")
        self.assertEqual(200, runtime_after_archive.status_code)
        runtime_after_archive_payload = runtime_after_archive.get_json() or {}
        self.assertFalse(
            any(int(item.get("id") or 0) == thread_id for item in runtime_after_archive_payload.get("threads", []))
        )

    def test_quick_settings_defaults_roundtrip_json(self) -> None:
        model = self._create_model(name="Quick Defaults Model")
        mcp_server = self._create_mcp_server(name="Quick Defaults MCP")

        save = self.client.post(
            "/api/quick/settings",
            json={
                "default_agent_id": None,
                "default_model_id": model.id,
                "default_mcp_server_ids": [mcp_server.id],
                "default_integration_keys": ["github"],
            },
        )
        self.assertEqual(200, save.status_code)
        save_payload = save.get_json() or {}
        self.assertTrue(bool(save_payload.get("ok")))
        quick_default_settings = save_payload.get("quick_default_settings") or {}
        self.assertEqual(model.id, quick_default_settings.get("default_model_id"))
        self.assertEqual([mcp_server.id], quick_default_settings.get("default_mcp_server_ids"))
        self.assertEqual(["github"], quick_default_settings.get("default_integration_keys"))

        meta = self.client.get("/api/quick")
        self.assertEqual(200, meta.status_code)
        meta_payload = meta.get_json() or {}
        self.assertEqual(model.id, meta_payload.get("default_model_id"))
        self.assertEqual([mcp_server.id], meta_payload.get("selected_mcp_server_ids"))
        self.assertEqual(["github"], meta_payload.get("selected_integration_keys"))

    def test_flowchart_catalog_handles_memories_without_title_field(self) -> None:
        self._create_memory(description="Remember to validate deployment readiness before promotion.")

        response = self.client.get("/api/flowcharts/new")
        self.assertEqual(200, response.status_code)
        payload = response.get_json() or {}
        catalog = payload.get("catalog") or {}
        memories = catalog.get("memories") or []
        self.assertGreaterEqual(len(memories), 1)
        self.assertTrue(all("title" in memory for memory in memories))
        self.assertTrue(
            any("Remember to validate deployment readiness" in str(memory.get("title") or "") for memory in memories)
        )

    def test_memories_api_lists_memory_nodes_with_flowchart_context(self) -> None:
        with session_scope() as session:
            orphan_memory = Memory.create(session, description="orphan-memory")
            memory_primary = Memory.create(session, description="release-summary")
            memory_secondary = Memory.create(session, description="deploy-checklist")
            flowchart_primary = Flowchart.create(session, name="Release")
            flowchart_secondary = Flowchart.create(session, name="Deploy")
            node_primary = FlowchartNode.create(
                session,
                flowchart_id=flowchart_primary.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                ref_id=memory_primary.id,
                x=0,
                y=0,
            )
            node_secondary = FlowchartNode.create(
                session,
                flowchart_id=flowchart_secondary.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                ref_id=memory_secondary.id,
                x=20,
                y=10,
            )
            orphan_memory_id = orphan_memory.id
            node_primary_id = node_primary.id
            node_secondary_id = node_secondary.id
            memory_primary_id = memory_primary.id
            memory_secondary_id = memory_secondary.id

        response = self.client.get("/api/memories?page=1&per_page=20")
        self.assertEqual(200, response.status_code)
        payload = response.get_json() or {}
        memories = payload.get("memories") or []
        self.assertEqual(2, len(memories))

        rows_by_node_id = {
            int(row.get("flowchart_node_id") or 0): row
            for row in memories
        }
        self.assertIn(node_primary_id, rows_by_node_id)
        self.assertIn(node_secondary_id, rows_by_node_id)

        primary_row = rows_by_node_id[node_primary_id]
        secondary_row = rows_by_node_id[node_secondary_id]
        self.assertEqual(memory_primary_id, int(primary_row.get("id") or 0))
        self.assertEqual("Release", primary_row.get("flowchart_name"))
        self.assertEqual(memory_secondary_id, int(secondary_row.get("id") or 0))
        self.assertEqual("Deploy", secondary_row.get("flowchart_name"))
        self.assertNotIn(
            orphan_memory_id,
            {int(row.get("id") or 0) for row in memories},
        )

    def test_memory_history_api_returns_artifacts_with_request_and_correlation_ids(self) -> None:
        with session_scope() as session:
            memory = Memory.create(session, description="release summary")
            flowchart = Flowchart.create(session, name="memory-history")
            flowchart_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                ref_id=memory.id,
                x=0,
                y=0,
                config_json=json.dumps({"action": "add"}, sort_keys=True),
            )
            flowchart_run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="completed",
            )
            flowchart_run_node = FlowchartRunNode.create(
                session,
                flowchart_run_id=flowchart_run.id,
                flowchart_node_id=flowchart_node.id,
                execution_index=1,
                status="succeeded",
                output_state_json="{}",
                routing_state_json="{}",
                input_context_json="{}",
            )
            NodeArtifact.create(
                session,
                flowchart_id=flowchart.id,
                flowchart_node_id=flowchart_node.id,
                flowchart_run_id=flowchart_run.id,
                flowchart_run_node_id=flowchart_run_node.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                artifact_type=NODE_ARTIFACT_TYPE_MEMORY,
                ref_id=memory.id,
                execution_index=1,
                variant_key=f"run-{flowchart_run.id}-node-run-{flowchart_run_node.id}",
                retention_mode="ttl",
                request_id="req-memory-stage8",
                correlation_id="corr-memory-stage8",
                payload_json=json.dumps(
                    {
                        "action": "add",
                        "effective_prompt": "release summary",
                        "mcp_server_keys": ["llmctl-mcp"],
                    },
                    sort_keys=True,
                ),
            )
            memory_id = memory.id

        response = self.client.get(f"/api/memories/{memory_id}/history?page=1&per_page=20")
        self.assertEqual(200, response.status_code)
        payload = response.get_json() or {}
        self.assertEqual(memory_id, int((payload.get("memory") or {}).get("id") or 0))
        self.assertEqual(f"memory-{memory_id}", payload.get("correlation_id"))
        self.assertTrue(str(payload.get("request_id") or "").startswith(f"memory-history-{memory_id}-"))
        artifacts = payload.get("artifacts") or []
        self.assertEqual(1, len(artifacts))
        self.assertEqual(NODE_ARTIFACT_TYPE_MEMORY, artifacts[0].get("artifact_type"))
        self.assertEqual("req-memory-stage8", artifacts[0].get("request_id"))
        self.assertEqual("corr-memory-stage8", artifacts[0].get("correlation_id"))
        self.assertEqual("add", (artifacts[0].get("payload") or {}).get("action"))

    def test_memory_history_api_can_filter_by_flowchart_node_id(self) -> None:
        with session_scope() as session:
            memory = Memory.create(session, description="history node filtering")
            flowchart = Flowchart.create(session, name="memory-history-filter")
            first_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                ref_id=memory.id,
                x=0,
                y=0,
            )
            second_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                ref_id=memory.id,
                x=200,
                y=0,
            )
            flowchart_run = FlowchartRun.create(
                session,
                flowchart_id=flowchart.id,
                status="completed",
            )
            first_run_node = FlowchartRunNode.create(
                session,
                flowchart_run_id=flowchart_run.id,
                flowchart_node_id=first_node.id,
                execution_index=1,
                status="succeeded",
                output_state_json="{}",
                routing_state_json="{}",
                input_context_json="{}",
            )
            second_run_node = FlowchartRunNode.create(
                session,
                flowchart_run_id=flowchart_run.id,
                flowchart_node_id=second_node.id,
                execution_index=2,
                status="succeeded",
                output_state_json="{}",
                routing_state_json="{}",
                input_context_json="{}",
            )
            NodeArtifact.create(
                session,
                flowchart_id=flowchart.id,
                flowchart_node_id=first_node.id,
                flowchart_run_id=flowchart_run.id,
                flowchart_run_node_id=first_run_node.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                artifact_type=NODE_ARTIFACT_TYPE_MEMORY,
                ref_id=memory.id,
                execution_index=1,
                variant_key=f"run-{flowchart_run.id}-node-run-{first_run_node.id}",
                retention_mode="ttl",
                payload_json=json.dumps({"action": "add"}, sort_keys=True),
            )
            NodeArtifact.create(
                session,
                flowchart_id=flowchart.id,
                flowchart_node_id=second_node.id,
                flowchart_run_id=flowchart_run.id,
                flowchart_run_node_id=second_run_node.id,
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                artifact_type=NODE_ARTIFACT_TYPE_MEMORY,
                ref_id=memory.id,
                execution_index=2,
                variant_key=f"run-{flowchart_run.id}-node-run-{second_run_node.id}",
                retention_mode="ttl",
                payload_json=json.dumps({"action": "retrieve"}, sort_keys=True),
            )
            memory_id = memory.id
            first_node_id = first_node.id

        response = self.client.get(
            f"/api/memories/{memory_id}/history?page=1&per_page=20&flowchart_node_id={first_node_id}"
        )
        self.assertEqual(200, response.status_code)
        payload = response.get_json() or {}
        self.assertEqual(first_node_id, int(payload.get("flowchart_node_id") or 0))
        artifacts = payload.get("artifacts") or []
        self.assertEqual(1, len(artifacts))
        self.assertEqual(first_node_id, int(artifacts[0].get("flowchart_node_id") or 0))
        self.assertEqual("add", (artifacts[0].get("payload") or {}).get("action"))


if __name__ == "__main__":
    unittest.main()

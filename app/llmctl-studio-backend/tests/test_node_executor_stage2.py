from __future__ import annotations

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
from sqlalchemy import select

os.environ.setdefault(
    "LLMCTL_STUDIO_DATABASE_URI",
    "postgresql+psycopg://llmctl:llmctl@127.0.0.1:15432/llmctl_studio",
)

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

import core.db as core_db
from core.config import Config
from core.db import session_scope
from core.models import AgentTask, IntegrationSetting
from services.integrations import (
    load_node_executor_settings,
    load_node_executor_runtime_settings,
    normalize_node_executor_run_metadata,
    node_executor_effective_config_summary,
    resolve_node_executor_k8s_image,
    resolve_node_executor_k8s_image_for_class,
    save_node_executor_settings,
)
from web import views as studio_views


class NodeExecutorStage2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._tmp_path = Path(self._tmp.name)
        self._orig_db_uri = Config.SQLALCHEMY_DATABASE_URI
        self._base_db_uri = os.environ["LLMCTL_STUDIO_DATABASE_URI"]
        self._schema_name = f"node_executor_stage2_{uuid.uuid4().hex}"
        self._create_schema(self._schema_name)
        Config.SQLALCHEMY_DATABASE_URI = self._with_search_path(
            self._base_db_uri,
            self._schema_name,
        )
        self._dispose_engine()
        core_db.init_engine(Config.SQLALCHEMY_DATABASE_URI)
        core_db.init_db()

        template_dir = STUDIO_SRC / "web" / "templates"
        app = Flask("node-executor-stage2-tests", template_folder=str(template_dir))
        app.config["TESTING"] = True
        app.secret_key = "node-executor-stage2-tests"
        app.register_blueprint(studio_views.bp)
        self.client = app.test_client()

    def tearDown(self) -> None:
        self._dispose_engine()
        self._drop_schema(self._schema_name)
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

    def test_node_executor_settings_bootstrap_defaults(self) -> None:
        settings = load_node_executor_settings()
        self.assertEqual("kubernetes", settings.get("provider"))
        self.assertEqual("0", settings.get("k8s_gpu_limit"))
        self.assertEqual("1800", settings.get("k8s_job_ttl_seconds"))
        self.assertEqual("default", settings.get("workspace_identity_key"))
        self.assertEqual("false", settings.get("agent_runtime_cutover_enabled"))
        self.assertTrue(bool(settings.get("k8s_frontier_image")))
        self.assertTrue(bool(settings.get("k8s_vllm_image")))

    def test_node_executor_settings_save_and_validate(self) -> None:
        with self.assertRaises(ValueError):
            save_node_executor_settings({"workspace_identity_key": "/tmp/workspace"})
        with self.assertRaises(ValueError):
            save_node_executor_settings({"k8s_image_pull_secrets_json": "{}"})
        with self.assertRaises(ValueError):
            save_node_executor_settings({"provider": "docker"})

        updated = save_node_executor_settings(
            {
                "provider": "kubernetes",
                "workspace_identity_key": "workspace-prod",
                "k8s_image": "llmctl-executor@sha256:" + ("a" * 64),
                "k8s_image_tag": "release-2026-02-18",
                "k8s_gpu_limit": "2",
                "k8s_job_ttl_seconds": "2400",
                "agent_runtime_cutover_enabled": "true",
            }
        )
        self.assertEqual("kubernetes", updated.get("provider"))
        self.assertEqual("workspace-prod", updated.get("workspace_identity_key"))
        self.assertEqual("release-2026-02-18", updated.get("k8s_image_tag"))
        self.assertEqual("2", updated.get("k8s_gpu_limit"))
        self.assertEqual("2400", updated.get("k8s_job_ttl_seconds"))
        self.assertEqual("true", updated.get("agent_runtime_cutover_enabled"))

    def test_node_executor_settings_db_overrides_env_defaults(self) -> None:
        save_node_executor_settings({"k8s_namespace": "llmctl"})
        with patch.object(Config, "NODE_EXECUTOR_PROVIDER", "workspace"):
            settings = load_node_executor_settings()
        self.assertEqual("kubernetes", settings.get("provider"))
        self.assertEqual("llmctl", settings.get("k8s_namespace"))

    def test_run_metadata_normalization_rules(self) -> None:
        with self.assertRaises(ValueError):
            normalize_node_executor_run_metadata(
                {
                    "selected_provider": "docker",
                    "dispatch_status": "dispatch_submitted",
                }
            )
        normalized = normalize_node_executor_run_metadata(
            {
                "selected_provider": "kubernetes",
                "final_provider": "kubernetes",
                "provider_dispatch_id": "kubernetes:default/job-123",
                "workspace_identity": "default",
                "dispatch_status": "dispatch_confirmed",
                "fallback_attempted": "false",
                "fallback_reason": "",
                "dispatch_uncertain": "false",
                "api_failure_category": "api_unreachable",
                "cli_fallback_used": "false",
                "cli_preflight_passed": "",
            }
        )
        self.assertEqual("kubernetes", normalized.get("final_provider"))
        self.assertEqual("dispatch_confirmed", normalized.get("dispatch_status"))
        self.assertEqual("", normalized.get("fallback_reason"))
        self.assertEqual("false", normalized.get("fallback_attempted"))

    def test_effective_config_summary_redacts_kubeconfig(self) -> None:
        save_node_executor_settings({"k8s_kubeconfig": "apiVersion: v1"})
        summary = node_executor_effective_config_summary()
        self.assertEqual("true", summary.get("k8s_kubeconfig_is_set"))
        self.assertTrue(str(summary.get("k8s_kubeconfig_fingerprint") or "").startswith("sha256:"))
        settings = load_node_executor_settings(include_secrets=False)
        self.assertEqual("", settings.get("k8s_kubeconfig"))
        self.assertEqual(
            settings.get("agent_runtime_cutover_enabled"),
            summary.get("agent_runtime_cutover_enabled"),
        )
        runtime_settings = load_node_executor_runtime_settings()
        self.assertEqual("apiVersion: v1", runtime_settings.get("k8s_kubeconfig"))
        with session_scope() as session:
            row = (
                session.execute(
                    select(IntegrationSetting).where(
                        IntegrationSetting.provider == "node_executor",
                        IntegrationSetting.key == "k8s_kubeconfig",
                    )
                )
                .scalars()
                .first()
            )
        self.assertIsNotNone(row)
        self.assertTrue(str(row.value).startswith("enc:v1:"))

    def test_runtime_settings_include_image_tag_for_executor_image_selection(self) -> None:
        save_node_executor_settings(
            {
                "k8s_frontier_image": "ghcr.io/acme/llmctl-executor-frontier:latest",
                "k8s_frontier_image_tag": "v2026.02.18",
                "k8s_vllm_image": "ghcr.io/acme/llmctl-executor-vllm:latest",
                "k8s_vllm_image_tag": "v2026.02.19",
            }
        )
        runtime_settings = load_node_executor_runtime_settings()
        self.assertEqual("v2026.02.18", runtime_settings.get("k8s_frontier_image_tag"))
        self.assertEqual("v2026.02.19", runtime_settings.get("k8s_vllm_image_tag"))
        self.assertEqual(
            "ghcr.io/acme/llmctl-executor-frontier:v2026.02.18",
            resolve_node_executor_k8s_image_for_class(
                runtime_settings,
                "frontier",
            ),
        )
        self.assertEqual(
            "ghcr.io/acme/llmctl-executor-vllm:v2026.02.19",
            resolve_node_executor_k8s_image_for_class(
                runtime_settings,
                "vllm",
            ),
        )

    def test_runtime_route_updates_node_executor_settings(self) -> None:
        response = self.client.post(
            "/settings/runtime/node-executor",
            data={
                "provider": "kubernetes",
                "dispatch_timeout_seconds": "120",
                "execution_timeout_seconds": "2400",
                "log_collection_timeout_seconds": "45",
                "cancel_grace_timeout_seconds": "20",
                "cancel_force_kill_enabled": "true",
                "workspace_identity_key": "default",
                "agent_runtime_cutover_enabled": "true",
                "k8s_namespace": "default",
                "k8s_image": "llmctl-executor-frontier:latest",
                "k8s_image_tag": "dev-2026-02-18",
                "k8s_frontier_image": "llmctl-executor-frontier:latest",
                "k8s_frontier_image_tag": "dev-2026-02-18",
                "k8s_vllm_image": "llmctl-executor-vllm:latest",
                "k8s_vllm_image_tag": "gpu-2026-02-18",
                "k8s_in_cluster": "true",
                "k8s_service_account": "executor",
                "k8s_gpu_limit": "1",
                "k8s_job_ttl_seconds": "900",
                "k8s_kubeconfig": "",
                "k8s_image_pull_secrets_json": "[]",
            },
            follow_redirects=False,
        )
        self.assertEqual(302, response.status_code)
        self.assertIn("/settings/runtime", response.headers["Location"])

        settings = load_node_executor_settings()
        self.assertEqual("kubernetes", settings.get("provider"))
        self.assertEqual("120", settings.get("dispatch_timeout_seconds"))
        self.assertEqual("true", settings.get("k8s_in_cluster"))
        self.assertEqual("dev-2026-02-18", settings.get("k8s_image_tag"))
        self.assertEqual("dev-2026-02-18", settings.get("k8s_frontier_image_tag"))
        self.assertEqual("gpu-2026-02-18", settings.get("k8s_vllm_image_tag"))
        self.assertEqual("1", settings.get("k8s_gpu_limit"))
        self.assertEqual("900", settings.get("k8s_job_ttl_seconds"))
        self.assertEqual("true", settings.get("agent_runtime_cutover_enabled"))

    def test_agent_task_node_executor_metadata_defaults(self) -> None:
        with session_scope() as session:
            task = AgentTask.create(session, prompt="hello")
            task_id = task.id

        with session_scope() as session:
            stored = session.execute(
                select(AgentTask).where(AgentTask.id == task_id)
            ).scalar_one()
            self.assertEqual("kubernetes", stored.selected_provider)
            self.assertEqual("kubernetes", stored.final_provider)
            self.assertEqual("dispatch_pending", stored.dispatch_status)
            self.assertFalse(stored.fallback_attempted)
            self.assertFalse(stored.dispatch_uncertain)
            self.assertEqual("default", stored.workspace_identity)

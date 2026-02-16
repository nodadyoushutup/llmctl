from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask
from sqlalchemy import select

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio" / "src"
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
    save_node_executor_settings,
)
from web import views as studio_views


class NodeExecutorStage2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._tmp_path = Path(self._tmp.name)
        self._orig_db_uri = Config.SQLALCHEMY_DATABASE_URI
        Config.SQLALCHEMY_DATABASE_URI = f"sqlite:///{self._tmp_path / 'node-executor-stage2.sqlite3'}"
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
        Config.SQLALCHEMY_DATABASE_URI = self._orig_db_uri
        self._tmp.cleanup()

    def _dispose_engine(self) -> None:
        if core_db._engine is not None:
            core_db._engine.dispose()
        core_db._engine = None
        core_db.SessionLocal = None

    def test_node_executor_settings_bootstrap_defaults(self) -> None:
        settings = load_node_executor_settings()
        self.assertEqual("workspace", settings.get("provider"))
        self.assertEqual("workspace", settings.get("fallback_provider"))
        self.assertEqual("true", settings.get("fallback_enabled"))
        self.assertEqual("10", settings.get("docker_api_stall_seconds"))
        self.assertEqual("default", settings.get("workspace_identity_key"))

    def test_node_executor_settings_save_and_validate(self) -> None:
        with self.assertRaises(ValueError):
            save_node_executor_settings({"docker_api_stall_seconds": "12"})
        with self.assertRaises(ValueError):
            save_node_executor_settings({"workspace_identity_key": "/tmp/workspace"})
        with self.assertRaises(ValueError):
            save_node_executor_settings({"docker_env_json": "[]"})
        with self.assertRaises(ValueError):
            save_node_executor_settings({"k8s_image_pull_secrets_json": "{}"})

        updated = save_node_executor_settings(
            {
                "provider": "docker",
                "fallback_provider": "workspace",
                "fallback_enabled": "true",
                "fallback_on_dispatch_error": "true",
                "docker_api_stall_seconds": "15",
                "workspace_identity_key": "workspace-prod",
                "docker_image": "llmctl-executor:latest",
                "k8s_image": "llmctl-executor@sha256:" + ("a" * 64),
            }
        )
        self.assertEqual("docker", updated.get("provider"))
        self.assertEqual("15", updated.get("docker_api_stall_seconds"))
        self.assertEqual("workspace-prod", updated.get("workspace_identity_key"))

    def test_node_executor_settings_db_overrides_env_defaults(self) -> None:
        save_node_executor_settings(
            {
                "provider": "docker",
                "docker_host": "unix:///var/run/docker.sock",
            }
        )
        with patch.object(Config, "NODE_EXECUTOR_PROVIDER", "kubernetes"), patch.object(
            Config, "NODE_EXECUTOR_DOCKER_HOST", "unix:///tmp/env-docker.sock"
        ):
            settings = load_node_executor_settings()
        self.assertEqual("docker", settings.get("provider"))
        self.assertEqual("unix:///var/run/docker.sock", settings.get("docker_host"))

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
                "selected_provider": "docker",
                "final_provider": "docker",
                "provider_dispatch_id": "docker:abc123",
                "workspace_identity": "default",
                "dispatch_status": "fallback_started",
                "fallback_attempted": "true",
                "fallback_reason": "dispatch_timeout",
                "dispatch_uncertain": "false",
                "api_failure_category": "api_unreachable",
                "cli_fallback_used": "true",
                "cli_preflight_passed": "true",
            }
        )
        self.assertEqual("workspace", normalized.get("final_provider"))
        self.assertEqual("fallback_started", normalized.get("dispatch_status"))
        self.assertEqual("dispatch_timeout", normalized.get("fallback_reason"))

    def test_effective_config_summary_redacts_kubeconfig(self) -> None:
        save_node_executor_settings({"k8s_kubeconfig": "apiVersion: v1"})
        summary = node_executor_effective_config_summary()
        self.assertEqual("true", summary.get("k8s_kubeconfig_is_set"))
        self.assertTrue(str(summary.get("k8s_kubeconfig_fingerprint") or "").startswith("sha256:"))
        settings = load_node_executor_settings(include_secrets=False)
        self.assertEqual("", settings.get("k8s_kubeconfig"))
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

    def test_runtime_route_updates_node_executor_settings(self) -> None:
        response = self.client.post(
            "/settings/runtime/node-executor",
            data={
                "provider": "docker",
                "fallback_provider": "workspace",
                "fallback_enabled": "true",
                "fallback_on_dispatch_error": "true",
                "dispatch_timeout_seconds": "120",
                "execution_timeout_seconds": "2400",
                "log_collection_timeout_seconds": "45",
                "cancel_grace_timeout_seconds": "20",
                "cancel_force_kill_enabled": "true",
                "workspace_root": "/tmp/workspaces",
                "workspace_identity_key": "default",
                "docker_host": "unix:///var/run/docker.sock",
                "docker_image": "llmctl-executor:latest",
                "docker_network": "bridge",
                "docker_pull_policy": "if_not_present",
                "docker_env_json": "{\"A\":\"B\"}",
                "docker_api_stall_seconds": "5",
                "k8s_namespace": "default",
                "k8s_image": "llmctl-executor:latest",
                "k8s_in_cluster": "true",
                "k8s_service_account": "executor",
                "k8s_kubeconfig": "",
                "k8s_image_pull_secrets_json": "[]",
            },
            follow_redirects=False,
        )
        self.assertEqual(302, response.status_code)
        self.assertIn("/settings/runtime", response.headers["Location"])

        settings = load_node_executor_settings()
        self.assertEqual("docker", settings.get("provider"))
        self.assertEqual("120", settings.get("dispatch_timeout_seconds"))
        self.assertEqual("5", settings.get("docker_api_stall_seconds"))
        self.assertEqual("true", settings.get("k8s_in_cluster"))

    def test_agent_task_node_executor_metadata_defaults(self) -> None:
        with session_scope() as session:
            task = AgentTask.create(session, prompt="hello")
            task_id = task.id

        with session_scope() as session:
            stored = session.execute(
                select(AgentTask).where(AgentTask.id == task_id)
            ).scalar_one()
            self.assertEqual("workspace", stored.selected_provider)
            self.assertEqual("workspace", stored.final_provider)
            self.assertEqual("dispatch_pending", stored.dispatch_status)
            self.assertFalse(stored.fallback_attempted)
            self.assertFalse(stored.dispatch_uncertain)
            self.assertEqual("default", stored.workspace_identity)

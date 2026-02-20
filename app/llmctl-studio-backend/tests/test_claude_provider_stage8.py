from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask
from sqlalchemy import select

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

import core.db as core_db
from core.config import Config
from core.db import session_scope
from core.models import IntegrationSetting, LLMModel
import services.tasks as studio_tasks
import web.views as studio_views


class ClaudeProviderRuntimeStage8UnitTests(unittest.TestCase):
    def test_resolve_claude_auth_prefers_integration_setting(self) -> None:
        env = {"ANTHROPIC_API_KEY": "env-key"}
        with patch.object(studio_tasks, "_load_claude_auth_key", return_value="db-key"):
            key, source = studio_tasks._resolve_claude_auth_key(env)
        self.assertEqual("db-key", key)
        self.assertEqual("integration_settings", source)

    def test_resolve_claude_auth_falls_back_to_environment(self) -> None:
        env = {"ANTHROPIC_API_KEY": "env-key"}
        with patch.object(studio_tasks, "_load_claude_auth_key", return_value=""):
            key, source = studio_tasks._resolve_claude_auth_key(env)
        self.assertEqual("env-key", key)
        self.assertEqual("environment", source)

    def test_claude_cli_diagnostics_reports_missing_command(self) -> None:
        with patch.object(studio_tasks.Config, "CLAUDE_CMD", "missing-claude"), patch(
            "services.tasks.shutil.which", return_value=None
        ):
            diagnostics = studio_tasks._claude_cli_diagnostics(env={})
        self.assertFalse(diagnostics["installed"])
        self.assertEqual("", diagnostics["path"])
        self.assertIn("not on PATH", str(diagnostics["error"]))

    def test_ensure_claude_cli_ready_attempts_install_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            script_path = Path(tmp_dir) / "install-claude.sh"
            script_path.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            script_path.chmod(0o755)
            missing = {
                "command": "claude",
                "path": "",
                "installed": False,
                "version": "",
                "error": "missing",
            }
            ready = {
                "command": "claude",
                "path": "/usr/bin/claude",
                "installed": True,
                "version": "claude 1.2.3",
                "error": "",
            }
            with patch.object(studio_tasks.Config, "CLAUDE_CLI_AUTO_INSTALL", True), patch.object(
                studio_tasks.Config, "CLAUDE_CLI_REQUIRE_READY", True
            ), patch.object(
                studio_tasks, "_resolve_claude_install_script", return_value=script_path
            ), patch.object(
                studio_tasks, "_claude_cli_diagnostics", side_effect=[missing, ready]
            ), patch(
                "services.tasks.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=["bash", str(script_path)], returncode=0, stdout="", stderr=""
                ),
            ) as run_mock:
                diagnostics = studio_tasks._ensure_claude_cli_ready(env={})
        self.assertTrue(diagnostics["installed"])
        self.assertEqual("claude 1.2.3", diagnostics["version"])
        self.assertEqual(1, run_mock.call_count)

    def test_run_llm_claude_requires_api_key_when_policy_enabled(self) -> None:
        with patch.object(
            studio_tasks, "_is_executor_node_execution_context", return_value=True
        ), patch.object(
            studio_tasks.Config, "CLAUDE_AUTH_REQUIRE_API_KEY", True
        ), patch.object(
            studio_tasks, "_resolve_claude_auth_key", return_value=("", "")
        ):
            result = studio_tasks._run_llm(
                provider="claude",
                prompt="hello",
                mcp_configs={},
                model_config={},
                env={},
            )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("ANTHROPIC_API_KEY", result.stderr)

    def test_run_llm_claude_executor_context_uses_frontier_sdk_path(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["sdk:claude"],
            returncode=0,
            stdout="ok",
            stderr="",
        )
        with patch.object(
            studio_tasks, "_is_executor_node_execution_context", return_value=True
        ), patch.object(
            studio_tasks,
            "_run_frontier_llm_sdk",
            return_value=completed,
        ) as sdk_mock, patch(
            "services.tasks.subprocess.run",
            side_effect=AssertionError("claude CLI subprocess execution is forbidden"),
        ), patch(
            "services.tasks.subprocess.Popen",
            side_effect=AssertionError("claude CLI subprocess execution is forbidden"),
        ):
            result = studio_tasks._run_llm(
                provider="claude",
                prompt="hello",
                mcp_configs={},
                model_config={"model": "claude-3-7-sonnet-latest"},
                env={},
            )
        self.assertEqual(0, result.returncode)
        self.assertEqual("ok", result.stdout)
        self.assertEqual(1, sdk_mock.call_count)

    def test_provider_model_options_include_curated_and_custom_claude_models(self) -> None:
        with patch.object(studio_views, "discover_vllm_local_models", return_value=[]):
            options = studio_views._provider_model_options(
                settings={"claude_models": "custom-claude-model"},
                models=[],
            )
        self.assertIn("custom-claude-model", options.get("claude", []))
        self.assertIn("claude-3-7-sonnet-latest", options.get("claude", []))


class ClaudeProviderRuntimeStage8WebTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp_dir = Path(self._tmp.name)
        self._orig_db_uri = Config.SQLALCHEMY_DATABASE_URI
        Config.SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_dir / 'claude-stage8.sqlite3'}"
        self._dispose_engine()
        core_db.init_engine(Config.SQLALCHEMY_DATABASE_URI)
        core_db.init_db()

        template_dir = STUDIO_SRC / "web" / "templates"
        app = Flask("claude-stage8-tests", template_folder=str(template_dir))
        app.config["TESTING"] = True
        app.secret_key = "claude-stage8"
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

    def test_settings_provider_claude_renders_runtime_diagnostics(self) -> None:
        diagnostics = {
            "command": "claude",
            "cli_installed": False,
            "cli_path": "",
            "cli_version": "",
            "cli_error": "missing",
            "cli_ready": False,
            "auth_required": True,
            "auth_ready": False,
            "auth_source": "",
            "auth_status": "missing",
            "auto_install_enabled": False,
            "require_cli_ready": True,
        }
        with patch.object(studio_views, "claude_runtime_diagnostics", return_value=diagnostics):
            response = self.client.get("/settings/provider/claude")
        self.assertEqual(200, response.status_code)
        html = response.get_data(as_text=True)
        self.assertIn("Runtime diagnostics", html)
        self.assertIn("cli missing", html)
        self.assertIn("missing API key", html)

    def test_update_claude_settings_writes_db_integration_setting(self) -> None:
        response = self.client.post(
            "/settings/provider/claude",
            data={"claude_api_key": "stage8-secret"},
            follow_redirects=False,
        )
        self.assertEqual(302, response.status_code)
        with session_scope() as session:
            row = session.execute(
                select(IntegrationSetting).where(
                    IntegrationSetting.provider == "llm",
                    IntegrationSetting.key == "claude_api_key",
                )
            ).scalar_one()
            self.assertEqual("stage8-secret", row.value)

    def test_create_model_allows_custom_claude_model(self) -> None:
        response = self.client.post(
            "/models",
            data={
                "name": "Claude Custom",
                "description": "",
                "provider": "claude",
                "claude_model": "claude-custom-freeform-model",
            },
            follow_redirects=False,
        )
        self.assertEqual(302, response.status_code)
        location = str(response.headers.get("Location") or "")
        self.assertIn("/models/", location)
        model_id = int(location.rstrip("/").split("/")[-1])
        with session_scope() as session:
            model = session.get(LLMModel, model_id)
            self.assertIsNotNone(model)
            self.assertEqual("claude", model.provider)
            self.assertIn("claude-custom-freeform-model", model.config_json or "")


if __name__ == "__main__":
    unittest.main()

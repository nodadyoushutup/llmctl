from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
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
from core.models import IntegrationSetting
from core.vllm_models import discover_vllm_local_models
import web.views as studio_views


class VllmLocalQwenActionStage9Tests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp_dir = Path(self._tmp.name)
        self._orig_db_uri = Config.SQLALCHEMY_DATABASE_URI
        Config.SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_dir / 'vllm-local-qwen-stage9.sqlite3'}"
        self._dispose_engine()
        core_db.init_engine(Config.SQLALCHEMY_DATABASE_URI)
        core_db.init_db()

        template_dir = STUDIO_SRC / "web" / "templates"
        app = Flask("vllm-local-qwen-stage9-tests", template_folder=str(template_dir))
        app.config["TESTING"] = True
        app.secret_key = "vllm-local-qwen-stage9"
        app.register_blueprint(studio_views.bp)
        self.client = app.test_client()
        with studio_views._huggingface_download_jobs_lock:
            studio_views._huggingface_download_jobs.clear()

    def tearDown(self) -> None:
        self._dispose_engine()
        Config.SQLALCHEMY_DATABASE_URI = self._orig_db_uri
        self._tmp.cleanup()

    def _dispose_engine(self) -> None:
        if core_db._engine is not None:
            core_db._engine.dispose()
        core_db._engine = None
        core_db.SessionLocal = None

    def _set_setting(self, key: str, value: str) -> None:
        with session_scope() as session:
            IntegrationSetting.create(session, provider="llm", key=key, value=value)

    def test_qwen_action_payload_is_download_when_model_missing(self) -> None:
        with patch.object(studio_views, "_qwen_model_downloaded", return_value=False):
            payload = studio_views._qwen_action_payload()
        self.assertFalse(bool(payload.get("installed")))
        self.assertEqual("download", payload.get("action"))

    def test_discover_vllm_local_models_ignores_hidden_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / ".download-venv").mkdir()
            model_dir = root / "sample-model"
            model_dir.mkdir()
            (model_dir / "model.json").write_text(
                '{"name":"Sample","model":"/app/data/models/sample-model"}\n',
                encoding="utf-8",
            )
            with patch.object(Config, "VLLM_LOCAL_CUSTOM_MODELS_DIR", str(root)), patch.object(
                Config, "VLLM_LOCAL_FALLBACK_MODEL", "/app/data/models/qwen2.5-0.5b-instruct"
            ):
                models = discover_vllm_local_models()
        values = [item["value"] for item in models]
        self.assertEqual(["/app/data/models/sample-model"], values)

    def test_qwen_action_payload_is_remove_when_model_present(self) -> None:
        with patch.object(studio_views, "_qwen_model_downloaded", return_value=True):
            payload = studio_views._qwen_action_payload()
        self.assertTrue(bool(payload.get("installed")))
        self.assertEqual("remove", payload.get("action"))

    def test_qwen_container_path_uses_configured_custom_models_dir(self) -> None:
        with patch.object(Config, "VLLM_LOCAL_CUSTOM_MODELS_DIR", "/app/data/models"):
            path = studio_views._qwen_model_container_path()
        self.assertEqual("/app/data/models/qwen2.5-0.5b-instruct", path)

    def test_toggle_qwen_download_invokes_downloader(self) -> None:
        with patch.object(studio_views, "_qwen_model_downloaded", return_value=False), patch.object(
            studio_views,
            "_start_huggingface_download_job",
            return_value=({"id": "job-qwen-form-1", "status": "queued"}, True),
        ) as start_job:
            response = self.client.post(
                "/settings/provider/vllm-local/qwen",
                data={"qwen_action": "download"},
                follow_redirects=False,
            )
        self.assertEqual(302, response.status_code)
        start_job.assert_called_once_with(
            kind="qwen",
            model_id=studio_views._qwen_model_id(),
            model_dir_name=studio_views._qwen_model_dir_name(),
            token="",
            model_container_path=studio_views._qwen_model_container_path(),
        )

    def test_toggle_qwen_download_uses_huggingface_token_when_configured(self) -> None:
        self._set_setting("vllm_local_hf_token", "hf_test_token")
        with patch.object(studio_views, "_qwen_model_downloaded", return_value=False), patch.object(
            studio_views,
            "_start_huggingface_download_job",
            return_value=({"id": "job-qwen-form-2", "status": "queued"}, True),
        ) as start_job:
            response = self.client.post(
                "/settings/provider/vllm-local/qwen",
                data={"qwen_action": "download"},
                follow_redirects=False,
            )
        self.assertEqual(302, response.status_code)
        start_job.assert_called_once_with(
            kind="qwen",
            model_id=studio_views._qwen_model_id(),
            model_dir_name=studio_views._qwen_model_dir_name(),
            token="hf_test_token",
            model_container_path=studio_views._qwen_model_container_path(),
        )

    def test_update_vllm_local_settings_persists_huggingface_token(self) -> None:
        response = self.client.post(
            "/settings/provider/vllm-local",
            data={
                "vllm_local_model": "",
                "vllm_local_hf_token": "hf_saved_token",
            },
            follow_redirects=False,
        )
        self.assertEqual(302, response.status_code)
        with session_scope() as session:
            row = session.execute(
                select(IntegrationSetting).where(
                    IntegrationSetting.provider == "llm",
                    IntegrationSetting.key == "vllm_local_hf_token",
                )
            ).scalar_one_or_none()
            self.assertIsNotNone(row)
            self.assertEqual("hf_saved_token", row.value)

    def test_update_huggingface_integration_settings_persists_token(self) -> None:
        response = self.client.post(
            "/settings/integrations/huggingface",
            data={"vllm_local_hf_token": "hf_saved_token"},
            follow_redirects=False,
        )
        self.assertEqual(302, response.status_code)
        with session_scope() as session:
            row = session.execute(
                select(IntegrationSetting).where(
                    IntegrationSetting.provider == "llm",
                    IntegrationSetting.key == "vllm_local_hf_token",
                )
            ).scalar_one_or_none()
            self.assertIsNotNone(row)
            self.assertEqual("hf_saved_token", row.value)

    def test_update_vllm_local_settings_keeps_existing_huggingface_token(self) -> None:
        self._set_setting("vllm_local_hf_token", "hf_existing_token")
        response = self.client.post(
            "/settings/provider/vllm-local",
            data={"vllm_local_model": ""},
            follow_redirects=False,
        )
        self.assertEqual(302, response.status_code)
        with session_scope() as session:
            row = session.execute(
                select(IntegrationSetting).where(
                    IntegrationSetting.provider == "llm",
                    IntegrationSetting.key == "vllm_local_hf_token",
                )
            ).scalar_one_or_none()
            self.assertIsNotNone(row)
            self.assertEqual("hf_existing_token", row.value)

    def test_settings_sidebar_expands_active_integrations_section(self) -> None:
        response = self.client.get("/settings/integrations/huggingface")
        self.assertEqual(200, response.status_code)
        html = response.get_data(as_text=True)
        self.assertRegex(
            html,
            re.compile(
                r'<button[^>]*data-nav-section-toggle[^>]*aria-expanded="true"[^>]*>'
                r'\s*<span class="nav-section-title">Settings</span>',
                re.DOTALL,
            ),
        )
        self.assertRegex(
            html,
            re.compile(
                r'<a\s+href="/settings/integrations"\s+class="nav-item is-active"\s*>',
                re.DOTALL,
            ),
        )

    def test_vllm_local_settings_payload_hides_generic_hf_download_without_token(self) -> None:
        payload = studio_views._vllm_local_settings_payload({})
        huggingface = payload.get("huggingface")
        self.assertIsInstance(huggingface, dict)
        self.assertFalse(bool(huggingface.get("configured")))

    def test_vllm_local_settings_payload_shows_generic_hf_download_with_token(self) -> None:
        payload = studio_views._vllm_local_settings_payload({"vllm_local_hf_token": "hf_test_token"})
        huggingface = payload.get("huggingface")
        self.assertIsInstance(huggingface, dict)
        self.assertTrue(bool(huggingface.get("configured")))

    def test_vllm_local_settings_payload_includes_downloaded_model_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            model_dir = Path(tmp_dir) / "sample-model"
            model_dir.mkdir()
            with patch.object(Config, "VLLM_LOCAL_CUSTOM_MODELS_DIR", tmp_dir), patch.object(
                studio_views,
                "discover_vllm_local_models",
                return_value=[
                    {
                        "label": "Sample Model",
                        "value": "/app/data/models/sample-model",
                        "path": str(model_dir),
                    }
                ],
            ):
                payload = studio_views._vllm_local_settings_payload({})
        huggingface = payload.get("huggingface")
        self.assertIsInstance(huggingface, dict)
        downloaded_models = huggingface.get("downloaded_models")
        self.assertIsInstance(downloaded_models, list)
        self.assertEqual(1, len(downloaded_models))
        first = downloaded_models[0]
        self.assertEqual("sample-model", first.get("dir_name"))
        self.assertEqual("Downloaded", first.get("status"))

    def test_generic_huggingface_download_requires_token(self) -> None:
        with patch.object(studio_views, "_start_huggingface_download_job") as start_job:
            response = self.client.post(
                "/settings/provider/vllm-local/huggingface",
                data={"vllm_local_hf_model_id": "Qwen/Qwen2.5-7B-Instruct"},
                follow_redirects=False,
            )
        self.assertEqual(302, response.status_code)
        start_job.assert_not_called()

    def test_generic_huggingface_download_rejects_invalid_model_id(self) -> None:
        self._set_setting("vllm_local_hf_token", "hf_test_token")
        with patch.object(studio_views, "_start_huggingface_download_job") as start_job:
            response = self.client.post(
                "/settings/provider/vllm-local/huggingface",
                data={"vllm_local_hf_model_id": "https://huggingface.co/Qwen/Qwen2.5-7B-Instruct"},
                follow_redirects=False,
            )
        self.assertEqual(302, response.status_code)
        start_job.assert_not_called()

    def test_generic_huggingface_download_skips_when_target_exists(self) -> None:
        self._set_setting("vllm_local_hf_token", "hf_test_token")
        with patch.object(
            studio_views,
            "_model_directory_has_downloaded_contents",
            return_value=True,
        ), patch.object(studio_views, "_start_huggingface_download_job") as start_job:
            response = self.client.post(
                "/settings/provider/vllm-local/huggingface",
                data={"vllm_local_hf_model_id": "Qwen/Qwen2.5-7B-Instruct"},
                follow_redirects=False,
            )
        self.assertEqual(302, response.status_code)
        start_job.assert_not_called()

    def test_generic_huggingface_download_invokes_downloader(self) -> None:
        self._set_setting("vllm_local_hf_token", "hf_test_token")
        with patch.object(
            studio_views,
            "_model_directory_has_downloaded_contents",
            return_value=False,
        ), patch.object(
            studio_views,
            "_start_huggingface_download_job",
            return_value=({"id": "job-hf-form-1", "status": "queued"}, True),
        ) as start_job:
            response = self.client.post(
                "/settings/provider/vllm-local/huggingface",
                data={"vllm_local_hf_model_id": "Qwen/Qwen2.5-7B-Instruct"},
                follow_redirects=False,
            )
        self.assertEqual(302, response.status_code)
        start_job.assert_called_once_with(
            kind="huggingface",
            model_id="Qwen/Qwen2.5-7B-Instruct",
            model_dir_name="qwen2.5-7b-instruct",
            token="hf_test_token",
            model_container_path=studio_views._vllm_local_model_container_path(
                "qwen2.5-7b-instruct"
            ),
        )

    def test_start_qwen_download_endpoint_queues_background_job(self) -> None:
        with patch.object(studio_views, "_qwen_model_downloaded", return_value=False), patch.object(
            studio_views,
            "_start_huggingface_download_job",
            return_value=({"id": "job-qwen-1", "status": "queued"}, True),
        ) as start_job:
            response = self.client.post(
                "/settings/provider/vllm-local/qwen/start",
                data={"qwen_action": "download"},
            )
        self.assertEqual(202, response.status_code)
        payload = response.get_json()
        self.assertIsInstance(payload, dict)
        self.assertTrue(bool(payload.get("ok")))
        self.assertTrue(bool(payload.get("created")))
        start_job.assert_called_once_with(
            kind="qwen",
            model_id=studio_views._qwen_model_id(),
            model_dir_name=studio_views._qwen_model_dir_name(),
            token="",
            model_container_path=studio_views._qwen_model_container_path(),
        )

    def test_start_huggingface_download_job_uses_dedicated_queue(self) -> None:
        async_result = SimpleNamespace(id="job-hf-queue-1")
        with patch.object(
            studio_views.run_huggingface_download_task,
            "apply_async",
            return_value=async_result,
        ) as enqueue:
            job, created = studio_views._start_huggingface_download_job(
                kind="huggingface",
                model_id="Qwen/Qwen2.5-7B-Instruct",
                model_dir_name="qwen2.5-7b-instruct",
                token="hf_test_token",
                model_container_path=studio_views._vllm_local_model_container_path(
                    "qwen2.5-7b-instruct"
                ),
            )
        self.assertTrue(created)
        self.assertEqual("job-hf-queue-1", job.get("id"))
        enqueue.assert_called_once()
        self.assertEqual(
            studio_views.HUGGINGFACE_DOWNLOAD_QUEUE,
            enqueue.call_args.kwargs.get("queue"),
        )

    def test_start_generic_huggingface_download_requires_token(self) -> None:
        response = self.client.post(
            "/settings/provider/vllm-local/huggingface/start",
            data={"vllm_local_hf_model_id": "Qwen/Qwen2.5-7B-Instruct"},
        )
        self.assertEqual(400, response.status_code)
        payload = response.get_json()
        self.assertIsInstance(payload, dict)
        self.assertFalse(bool(payload.get("ok")))

    def test_start_generic_huggingface_download_endpoint_queues_background_job(self) -> None:
        self._set_setting("vllm_local_hf_token", "hf_test_token")
        with patch.object(
            studio_views,
            "_model_directory_has_downloaded_contents",
            return_value=False,
        ), patch.object(
            studio_views,
            "_start_huggingface_download_job",
            return_value=({"id": "job-hf-1", "status": "queued"}, True),
        ) as start_job:
            response = self.client.post(
                "/settings/provider/vllm-local/huggingface/start",
                data={"vllm_local_hf_model_id": "Qwen/Qwen2.5-7B-Instruct"},
            )
        self.assertEqual(202, response.status_code)
        payload = response.get_json()
        self.assertIsInstance(payload, dict)
        self.assertTrue(bool(payload.get("ok")))
        self.assertTrue(bool(payload.get("created")))
        start_job.assert_called_once_with(
            kind="huggingface",
            model_id="Qwen/Qwen2.5-7B-Instruct",
            model_dir_name="qwen2.5-7b-instruct",
            token="hf_test_token",
            model_container_path=studio_views._vllm_local_model_container_path(
                "qwen2.5-7b-instruct"
            ),
        )

    def test_huggingface_download_status_endpoint_returns_job_snapshot(self) -> None:
        with patch.object(
            studio_views,
            "_get_huggingface_download_job",
            return_value={
                "id": "job-123",
                "status": "running",
                "phase": "downloading",
                "percent": 42.0,
            },
        ):
            response = self.client.get("/settings/provider/vllm-local/downloads/job-123")
        self.assertEqual(200, response.status_code)
        payload = response.get_json()
        self.assertIsInstance(payload, dict)
        job = payload.get("download_job")
        self.assertIsInstance(job, dict)
        self.assertEqual("job-123", job.get("id"))
        self.assertEqual("running", job.get("status"))
        self.assertEqual("downloading", job.get("phase"))
        self.assertEqual(42.0, job.get("percent"))

    def test_delete_downloaded_huggingface_model_route_removes_selected_model(self) -> None:
        with session_scope() as session:
            IntegrationSetting.create(
                session,
                provider="llm",
                key="vllm_local_model",
                value="/app/data/models/sample-model",
            )
        with patch.object(
            studio_views,
            "_find_downloaded_vllm_local_model",
            return_value={
                "dir_name": "sample-model",
                "label": "Sample Model",
                "value": "/app/data/models/sample-model",
                "target_dir": "/tmp/sample-model",
                "container_path": "/app/data/models/sample-model",
                "status": "Downloaded",
            },
        ), patch.object(
            studio_views, "_remove_vllm_local_model_directory", return_value=True
        ) as remove_model:
            response = self.client.post(
                "/settings/provider/vllm-local/huggingface/delete",
                data={"model_dir_name": "sample-model"},
                follow_redirects=False,
            )
        self.assertEqual(302, response.status_code)
        remove_model.assert_called_once_with("sample-model")
        with session_scope() as session:
            row = session.execute(
                select(IntegrationSetting).where(
                    IntegrationSetting.provider == "llm",
                    IntegrationSetting.key == "vllm_local_model",
                )
            ).scalar_one_or_none()
            self.assertIsNone(row)

    def test_toggle_qwen_remove_clears_selected_model(self) -> None:
        with session_scope() as session:
            IntegrationSetting.create(
                session,
                provider="llm",
                key="vllm_local_model",
                value="/app/models/custom/qwen2.5-0.5b-instruct",
            )

        with patch.object(studio_views, "_remove_qwen_model_directory", return_value=True), patch.object(
            studio_views, "_qwen_model_directory", return_value=Path("/tmp/qwen2.5-0.5b-instruct")
        ), patch.object(
            studio_views, "_qwen_model_container_path", return_value="/app/models/custom/qwen2.5-0.5b-instruct"
        ):
            response = self.client.post(
                "/settings/provider/vllm-local/qwen",
                data={"qwen_action": "remove"},
                follow_redirects=False,
            )
        self.assertEqual(302, response.status_code)
        with session_scope() as session:
            row = session.execute(
                select(IntegrationSetting).where(
                    IntegrationSetting.provider == "llm",
                    IntegrationSetting.key == "vllm_local_model",
                )
            ).scalar_one_or_none()
            self.assertIsNone(row)


if __name__ == "__main__":
    unittest.main()

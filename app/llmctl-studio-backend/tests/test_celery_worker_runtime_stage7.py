from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKER_RUN_PATH = REPO_ROOT / "app" / "llmctl-celery-worker" / "run.py"

_SPEC = importlib.util.spec_from_file_location("llmctl_celery_worker_run", WORKER_RUN_PATH)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover
    raise RuntimeError("Failed to load llmctl-celery-worker run.py module.")
worker_run = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(worker_run)


class CeleryWorkerRuntimeStage7Tests(unittest.TestCase):
    def test_normalize_mode_prefers_explicit_cli_mode(self) -> None:
        mode, extra_args = worker_run._normalize_mode(["beat", "--loglevel", "debug"])
        self.assertEqual("beat", mode)
        self.assertEqual(["--loglevel", "debug"], extra_args)

    def test_normalize_mode_falls_back_to_env_mode(self) -> None:
        with patch.dict(os.environ, {"LLMCTL_CELERY_WORKER_MODE": "worker"}, clear=False):
            mode, extra_args = worker_run._normalize_mode(["--queues", "q1"])
        self.assertEqual("worker", mode)
        self.assertEqual(["--queues", "q1"], extra_args)

    def test_normalize_mode_invalid_env_defaults_to_worker(self) -> None:
        with patch.dict(os.environ, {"LLMCTL_CELERY_WORKER_MODE": "invalid"}, clear=False):
            mode, extra_args = worker_run._normalize_mode([])
        self.assertEqual("worker", mode)
        self.assertEqual([], extra_args)

    def test_set_pythonpath_prefixes_backend_source(self) -> None:
        src_path = Path("/repo/app/llmctl-studio-backend/src")
        with patch.dict(os.environ, {"PYTHONPATH": "/existing/path"}, clear=False):
            worker_run._set_pythonpath(src_path)
            self.assertEqual(
                f"{src_path}{os.pathsep}/existing/path",
                os.environ.get("PYTHONPATH"),
            )

    def test_build_worker_command_includes_celery_app_and_all_default_queues(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            command = worker_run._build_worker_command([])
        self.assertEqual(sys.executable, command[0])
        self.assertEqual(
            [
                "-m",
                "celery",
                "-A",
                "services.celery_app:celery_app",
                "worker",
                "--loglevel",
                "info",
                "--concurrency",
                "2",
                "--hostname",
                "llmctl-celery-worker@%h",
                "--queues",
                worker_run.DEFAULT_WORKER_QUEUES,
            ],
            command[1:],
        )

    def test_build_worker_command_applies_overrides_and_extra_args(self) -> None:
        with patch.dict(
            os.environ,
            {
                "CELERY_WORKER_QUEUES": "custom.queue",
                "CELERY_WORKER_CONCURRENCY": "4",
                "CELERY_WORKER_LOGLEVEL": "warning",
                "CELERY_WORKER_HOSTNAME": "custom@%h",
            },
            clear=False,
        ):
            command = worker_run._build_worker_command(["--pool", "solo"])
        self.assertIn("--queues", command)
        self.assertIn("custom.queue", command)
        self.assertIn("--concurrency", command)
        self.assertIn("4", command)
        self.assertIn("--loglevel", command)
        self.assertIn("warning", command)
        self.assertIn("--hostname", command)
        self.assertIn("custom@%h", command)
        self.assertEqual(["--pool", "solo"], command[-2:])

    def test_build_worker_command_skips_queue_flag_when_queue_is_blank(self) -> None:
        with patch.dict(os.environ, {"CELERY_WORKER_QUEUES": "   "}, clear=False):
            command = worker_run._build_worker_command([])
        self.assertNotIn("--queues", command)

    def test_build_beat_command_uses_data_dir_files_and_extra_args(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(
                os.environ,
                {
                    "LLMCTL_STUDIO_DATA_DIR": tmp,
                    "CELERY_BEAT_LOGLEVEL": "debug",
                },
                clear=False,
            ):
                command = worker_run._build_beat_command(Path("/repo"), ["--max-interval", "15"])
        self.assertEqual(sys.executable, command[0])
        self.assertEqual("beat", command[5])
        self.assertIn("--loglevel", command)
        self.assertIn("debug", command)
        self.assertIn("--schedule", command)
        self.assertIn(str(Path(tmp) / "celerybeat-schedule"), command)
        self.assertIn("--pidfile", command)
        self.assertIn(str(Path(tmp) / "celerybeat.pid"), command)
        self.assertEqual(["--max-interval", "15"], command[-2:])

    def test_main_execs_worker_command_with_backend_pythonpath(self) -> None:
        fake_repo_root = Path("/workspace/llmctl")
        expected_src = fake_repo_root / "app" / "llmctl-studio-backend" / "src"
        with (
            patch.object(worker_run, "_repo_root", return_value=fake_repo_root),
            patch.object(worker_run.os, "chdir") as chdir_mock,
            patch.object(worker_run.os, "execv") as execv_mock,
            patch.object(worker_run.sys, "argv", ["run.py", "worker", "--loglevel", "debug"]),
            patch.dict(os.environ, {}, clear=True),
        ):
            result = worker_run.main()
            self.assertTrue(os.environ.get("PYTHONPATH", "").startswith(str(expected_src)))
        self.assertIsNone(result)
        chdir_mock.assert_called_once_with(fake_repo_root)
        execv_mock.assert_called_once()
        executable, command = execv_mock.call_args.args
        self.assertEqual(sys.executable, executable)
        self.assertEqual(sys.executable, command[0])
        self.assertIn("services.celery_app:celery_app", command)


if __name__ == "__main__":
    unittest.main()

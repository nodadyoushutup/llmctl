#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

CELERY_APP = "services.celery_app:celery_app"
DEFAULT_MODE = "worker"
WORKER_MODES = {"worker", "beat"}
DEFAULT_WORKER_QUEUES = ",".join(
    [
        "llmctl_studio",
        "llmctl_studio.downloads.huggingface",
        "llmctl_studio.rag.index",
        "llmctl_studio.rag.drive",
        "llmctl_studio.rag.git",
    ]
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _backend_src_path(repo_root: Path) -> Path:
    return repo_root / "app" / "llmctl-studio-backend" / "src"


def _normalize_mode(argv: list[str]) -> tuple[str, list[str]]:
    if argv and argv[0] in WORKER_MODES:
        return argv[0], argv[1:]
    mode = os.getenv("LLMCTL_CELERY_WORKER_MODE", DEFAULT_MODE).strip().lower()
    if mode not in WORKER_MODES:
        mode = DEFAULT_MODE
    return mode, argv


def _set_pythonpath(src_path: Path) -> None:
    current = os.getenv("PYTHONPATH", "").strip()
    if current:
        os.environ["PYTHONPATH"] = f"{src_path}{os.pathsep}{current}"
    else:
        os.environ["PYTHONPATH"] = str(src_path)


def _build_worker_command(extra_args: list[str]) -> list[str]:
    queues = os.getenv("CELERY_WORKER_QUEUES", DEFAULT_WORKER_QUEUES).strip()
    concurrency = os.getenv("CELERY_WORKER_CONCURRENCY", "2").strip() or "2"
    loglevel = os.getenv("CELERY_WORKER_LOGLEVEL", "info").strip() or "info"
    hostname = os.getenv("CELERY_WORKER_HOSTNAME", "llmctl-celery-worker@%h").strip()
    if not hostname:
        hostname = "llmctl-celery-worker@%h"

    command = [
        sys.executable,
        "-m",
        "celery",
        "-A",
        CELERY_APP,
        "worker",
        "--loglevel",
        loglevel,
        "--concurrency",
        concurrency,
        "--hostname",
        hostname,
    ]
    if queues:
        command.extend(["--queues", queues])
    command.extend(extra_args)
    return command


def _build_beat_command(repo_root: Path, extra_args: list[str]) -> list[str]:
    loglevel = os.getenv("CELERY_BEAT_LOGLEVEL", "info").strip() or "info"
    data_dir = Path(os.getenv("LLMCTL_STUDIO_DATA_DIR", str(repo_root / "data")))
    data_dir.mkdir(parents=True, exist_ok=True)
    schedule_file = str(data_dir / "celerybeat-schedule")
    pid_file = str(data_dir / "celerybeat.pid")
    command = [
        sys.executable,
        "-m",
        "celery",
        "-A",
        CELERY_APP,
        "beat",
        "--loglevel",
        loglevel,
        "--schedule",
        schedule_file,
        "--pidfile",
        pid_file,
    ]
    command.extend(extra_args)
    return command


def main() -> int:
    repo_root = _repo_root()
    src_path = _backend_src_path(repo_root)
    _set_pythonpath(src_path)
    os.chdir(repo_root)

    mode, extra_args = _normalize_mode(sys.argv[1:])
    if mode == "beat":
        command = _build_beat_command(repo_root, extra_args)
    else:
        command = _build_worker_command(extra_args)
    os.execv(command[0], command)


if __name__ == "__main__":
    raise SystemExit(main())

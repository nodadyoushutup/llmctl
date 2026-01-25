#!/usr/bin/env python3
import os
import subprocess
import sys
from pathlib import Path


def _should_start_worker(debug: bool) -> bool:
    if os.getenv("CELERY_AUTOSTART", "true").lower() != "true":
        return False
    if debug and os.getenv("WERKZEUG_RUN_MAIN") != "true":
        return False
    return True


def _should_start_beat(debug: bool) -> bool:
    default = os.getenv("CELERY_AUTOSTART", "true")
    if os.getenv("CELERY_BEAT_AUTOSTART", default).lower() != "true":
        return False
    if debug and os.getenv("WERKZEUG_RUN_MAIN") != "true":
        return False
    return True


def _start_celery_worker(src_path: Path, repo_root: Path) -> subprocess.Popen | None:
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    if not _should_start_worker(debug):
        return None

    concurrency = os.getenv("CELERY_WORKER_CONCURRENCY", "6")
    loglevel = os.getenv("CELERY_WORKER_LOGLEVEL", "info")
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{src_path}{os.pathsep}{env.get('PYTHONPATH', '')}".strip(
        os.pathsep
    )
    command = [
        sys.executable,
        "-m",
        "celery",
        "-A",
        "services.celery_app:celery_app",
        "worker",
        "--loglevel",
        loglevel,
        "--concurrency",
        concurrency,
    ]
    return subprocess.Popen(command, cwd=repo_root, env=env)


def _start_celery_beat(src_path: Path, repo_root: Path) -> subprocess.Popen | None:
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    if not _should_start_beat(debug):
        return None

    loglevel = os.getenv("CELERY_BEAT_LOGLEVEL", "info")
    data_dir = Path(os.getenv("LLMCTL_STUDIO_DATA_DIR", repo_root / "data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    schedule_file = data_dir / "celerybeat-schedule"
    pid_file = data_dir / "celerybeat.pid"
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{src_path}{os.pathsep}{env.get('PYTHONPATH', '')}".strip(
        os.pathsep
    )
    command = [
        sys.executable,
        "-m",
        "celery",
        "-A",
        "services.celery_app:celery_app",
        "beat",
        "--loglevel",
        loglevel,
        "--schedule",
        str(schedule_file),
        "--pidfile",
        str(pid_file),
    ]
    return subprocess.Popen(command, cwd=repo_root, env=env)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    src_path = repo_root / "app" / "llmctl-studio" / "src"
    sys.path.insert(0, str(src_path))

    os.chdir(repo_root)

    from web.app import create_app

    app = create_app()
    host = os.getenv("FLASK_HOST", "0.0.0.0")
    port = int(os.getenv("FLASK_PORT", "5055"))
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    worker = _start_celery_worker(src_path, repo_root)
    beat = _start_celery_beat(src_path, repo_root)
    try:
        app.run(host=host, port=port, debug=debug)
    finally:
        if worker is not None:
            worker.terminate()
            try:
                worker.wait(timeout=10)
            except subprocess.TimeoutExpired:
                worker.kill()
        if beat is not None:
            beat.terminate()
            try:
                beat.wait(timeout=10)
            except subprocess.TimeoutExpired:
                beat.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

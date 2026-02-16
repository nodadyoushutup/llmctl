#!/usr/bin/env python3
import os
import subprocess
import sys
from pathlib import Path

TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    if raw in TRUE_VALUES:
        return True
    if raw in FALSE_VALUES:
        return False
    return default


def _build_runtime_env(src_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{src_path}{os.pathsep}{env.get('PYTHONPATH', '')}".strip(
        os.pathsep
    )
    return env


def _env_float(name: str, default: float, minimum: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        parsed = float(raw)
    except ValueError:
        return default
    if parsed < minimum:
        return default
    return parsed


def _run_database_preflight() -> None:
    if not _env_flag("LLMCTL_STUDIO_DB_HEALTHCHECK_ENABLED", True):
        return

    from core.config import Config
    from core.db import run_startup_db_healthcheck

    timeout_seconds = _env_float(
        "LLMCTL_STUDIO_DB_HEALTHCHECK_TIMEOUT_SECONDS",
        60.0,
        0.0,
    )
    interval_seconds = _env_float(
        "LLMCTL_STUDIO_DB_HEALTHCHECK_INTERVAL_SECONDS",
        2.0,
        0.1,
    )
    run_startup_db_healthcheck(
        Config.SQLALCHEMY_DATABASE_URI,
        timeout_seconds=timeout_seconds,
        interval_seconds=interval_seconds,
    )


def _should_start_worker(debug: bool) -> bool:
    if not _env_flag("CELERY_AUTOSTART", True):
        return False
    if debug and os.getenv("WERKZEUG_RUN_MAIN") != "true":
        return False
    return True


def _should_start_rag_worker(debug: bool) -> bool:
    if not _env_flag("RAG_CELERY_AUTOSTART", _env_flag("CELERY_AUTOSTART", True)):
        return False
    if debug and os.getenv("WERKZEUG_RUN_MAIN") != "true":
        return False
    return True


def _should_start_beat(debug: bool) -> bool:
    if not _env_flag("CELERY_BEAT_AUTOSTART", _env_flag("CELERY_AUTOSTART", True)):
        return False
    if debug and os.getenv("WERKZEUG_RUN_MAIN") != "true":
        return False
    return True


def _start_celery_worker(src_path: Path, repo_root: Path) -> subprocess.Popen | None:
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    if not _should_start_worker(debug):
        return None

    queue_name = "llmctl_studio"
    concurrency = os.getenv("CELERY_WORKER_CONCURRENCY", "6")
    loglevel = os.getenv("CELERY_WORKER_LOGLEVEL", "info")
    env = _build_runtime_env(src_path)
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
        "--queues",
        queue_name,
        "--hostname",
        "llmctl-studio-default@%h",
    ]
    return subprocess.Popen(command, cwd=repo_root, env=env)


def _start_rag_celery_worker(src_path: Path, repo_root: Path) -> subprocess.Popen | None:
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    if not _should_start_rag_worker(debug):
        return None

    queue_name = os.getenv(
        "RAG_CELERY_WORKER_QUEUES",
        "llmctl_studio.rag.index,llmctl_studio.rag.drive,llmctl_studio.rag.git",
    )
    concurrency = os.getenv(
        "RAG_CELERY_WORKER_CONCURRENCY",
        os.getenv("CELERY_WORKER_CONCURRENCY", "6"),
    )
    loglevel = os.getenv(
        "RAG_CELERY_WORKER_LOGLEVEL",
        os.getenv("CELERY_WORKER_LOGLEVEL", "info"),
    )
    env = _build_runtime_env(src_path)
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
        "--queues",
        queue_name,
        "--hostname",
        "llmctl-studio-rag@%h",
    ]
    return subprocess.Popen(command, cwd=repo_root, env=env)


def _start_huggingface_download_worker(src_path: Path, repo_root: Path) -> subprocess.Popen | None:
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    if not _should_start_worker(debug):
        return None

    queue_name = os.getenv(
        "HUGGINGFACE_DOWNLOAD_CELERY_WORKER_QUEUE",
        "llmctl_studio.downloads.huggingface",
    )
    concurrency = os.getenv("HUGGINGFACE_DOWNLOAD_CELERY_WORKER_CONCURRENCY", "1")
    loglevel = os.getenv(
        "HUGGINGFACE_DOWNLOAD_CELERY_WORKER_LOGLEVEL",
        os.getenv("CELERY_WORKER_LOGLEVEL", "info"),
    )
    env = _build_runtime_env(src_path)
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
        "--queues",
        queue_name,
        "--hostname",
        "llmctl-studio-hf-download@%h",
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
    env = _build_runtime_env(src_path)
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


def _terminate_process(process: subprocess.Popen | None) -> None:
    if process is None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


def _should_use_gunicorn(debug: bool) -> bool:
    raw = os.getenv("LLMCTL_STUDIO_USE_GUNICORN", "").strip().lower()
    if raw in TRUE_VALUES:
        return True
    if raw in FALSE_VALUES:
        return False
    return not debug


def _start_gunicorn(src_path: Path, repo_root: Path) -> subprocess.Popen:
    command = [
        sys.executable,
        "-m",
        "gunicorn",
        "-c",
        "python:web.gunicorn_config",
        "web.app:create_app()",
    ]
    return subprocess.Popen(
        command,
        cwd=repo_root,
        env=_build_runtime_env(src_path),
    )


def _run_flask_dev_server(host: str, port: int, debug: bool) -> int:
    from web.app import create_app
    from web.realtime import socketio

    app = create_app()
    socketio.run(app, host=host, port=port, debug=debug)
    return 0


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    src_path = repo_root / "app" / "llmctl-studio" / "src"
    sys.path.insert(0, str(src_path))

    os.chdir(repo_root)

    _run_database_preflight()

    host = os.getenv("FLASK_HOST", "0.0.0.0")
    port = int(os.getenv("FLASK_PORT", "5055"))
    debug = _env_flag("FLASK_DEBUG", False)
    worker = _start_celery_worker(src_path, repo_root)
    rag_worker = _start_rag_celery_worker(src_path, repo_root)
    hf_download_worker = _start_huggingface_download_worker(src_path, repo_root)
    beat = _start_celery_beat(src_path, repo_root)
    web_process: subprocess.Popen | None = None
    try:
        if _should_use_gunicorn(debug):
            web_process = _start_gunicorn(src_path, repo_root)
            return web_process.wait()
        return _run_flask_dev_server(host, port, debug)
    except KeyboardInterrupt:
        if web_process is not None:
            _terminate_process(web_process)
        return 0
    finally:
        _terminate_process(hf_download_worker)
        _terminate_process(rag_worker)
        _terminate_process(worker)
        _terminate_process(beat)


if __name__ == "__main__":
    raise SystemExit(main())

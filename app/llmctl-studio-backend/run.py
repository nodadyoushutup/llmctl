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
    src_path = repo_root / "app" / "llmctl-studio-backend" / "src"
    sys.path.insert(0, str(src_path))

    os.chdir(repo_root)

    _run_database_preflight()

    host = os.getenv("FLASK_HOST", "0.0.0.0")
    port = int(os.getenv("FLASK_PORT", "5055"))
    debug = _env_flag("FLASK_DEBUG", False)
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


if __name__ == "__main__":
    raise SystemExit(main())

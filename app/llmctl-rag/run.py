from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from config import load_config
from web_app import create_app


def _should_start_worker(debug: bool) -> bool:
    if os.getenv("CELERY_AUTOSTART", "true").lower() != "true":
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
        "celery_app:celery_app",
        "worker",
        "--loglevel",
        loglevel,
        "--concurrency",
        concurrency,
    ]
    return subprocess.Popen(command, cwd=repo_root, env=env)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    src_path = repo_root / "app" / "llmctl-rag"
    sys.path.insert(0, str(src_path))
    os.chdir(repo_root)

    app = create_app()
    config = load_config()
    port = config.web_port
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    worker = _start_celery_worker(src_path, repo_root)
    try:
        app.run(host="0.0.0.0", port=port, debug=debug)
    finally:
        if worker is not None:
            worker.terminate()
            try:
                worker.wait(timeout=10)
            except subprocess.TimeoutExpired:
                worker.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

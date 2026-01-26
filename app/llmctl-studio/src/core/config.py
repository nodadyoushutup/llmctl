from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


class Config:
    DATA_DIR = str(
        _ensure_dir(Path(os.getenv("LLMCTL_STUDIO_DATA_DIR", REPO_ROOT / "data")))
    )
    WORKSPACES_DIR = str(
        _ensure_dir(
            Path(
                os.getenv(
                    "LLMCTL_STUDIO_WORKSPACES_DIR",
                    Path(DATA_DIR) / "workspaces",
                )
            )
        )
    )
    SCRIPTS_DIR = str(_ensure_dir(Path(DATA_DIR) / "scripts"))
    ATTACHMENTS_DIR = str(_ensure_dir(Path(DATA_DIR) / "attachments"))
    SSH_KEYS_DIR = str(_ensure_dir(Path(DATA_DIR) / "ssh-keys"))
    DATABASE_FILENAME = os.getenv("LLMCTL_STUDIO_DB_NAME", "llmctl-studio.sqlite3")
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{Path(DATA_DIR) / DATABASE_FILENAME}"

    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev")

    CELERY_REDIS_HOST = os.getenv("CELERY_REDIS_HOST", "127.0.0.1")
    CELERY_REDIS_PORT = int(os.getenv("CELERY_REDIS_PORT", "6380"))
    CELERY_REDIS_BROKER_DB = os.getenv("CELERY_REDIS_BROKER_DB", "0")
    CELERY_REDIS_BACKEND_DB = os.getenv("CELERY_REDIS_BACKEND_DB", "1")
    _DEFAULT_CELERY_BROKER_URL = (
        f"redis://{CELERY_REDIS_HOST}:{CELERY_REDIS_PORT}/{CELERY_REDIS_BROKER_DB}"
    )
    _DEFAULT_CELERY_RESULT_BACKEND = (
        f"redis://{CELERY_REDIS_HOST}:{CELERY_REDIS_PORT}/{CELERY_REDIS_BACKEND_DB}"
    )
    CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", _DEFAULT_CELERY_BROKER_URL)
    _CELERY_RESULT_BACKEND_ENV = os.getenv("CELERY_RESULT_BACKEND")
    if _CELERY_RESULT_BACKEND_ENV is None and CELERY_BROKER_URL.startswith(
        "filesystem://"
    ):
        CELERY_RESULT_BACKEND = (
            f"db+sqlite:///{Path(DATA_DIR) / 'celery-results.sqlite3'}"
        )
    else:
        CELERY_RESULT_BACKEND = _CELERY_RESULT_BACKEND_ENV or _DEFAULT_CELERY_RESULT_BACKEND
    CELERY_BROKER_TRANSPORT_OPTIONS = None
    if CELERY_BROKER_URL.startswith("filesystem://"):
        CELERY_BROKER_TRANSPORT_OPTIONS = {
            "data_folder_in": str(_ensure_dir(Path(DATA_DIR) / "celery" / "in")),
            "data_folder_out": str(_ensure_dir(Path(DATA_DIR) / "celery" / "out")),
            "data_folder_processed": str(
                _ensure_dir(Path(DATA_DIR) / "celery" / "processed")
            ),
            "store_processed": True,
        }

    AGENT_POLL_SECONDS = float(os.getenv("AGENT_POLL_SECONDS", "1"))
    CELERY_REVOKE_ON_STOP = os.getenv("CELERY_REVOKE_ON_STOP", "false").lower() == "true"
    WORKSPACE_CLEANUP_ENABLED = (
        os.getenv("WORKSPACE_CLEANUP_ENABLED", "true").lower() == "true"
    )
    WORKSPACE_CLEANUP_INTERVAL_SECONDS = float(
        os.getenv("WORKSPACE_CLEANUP_INTERVAL_SECONDS", "300")
    )

    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "")
    CODEX_CMD = os.getenv("CODEX_CMD", "codex")
    CODEX_MODEL = os.getenv("CODEX_MODEL", "")
    CODEX_SKIP_GIT_REPO_CHECK = (
        os.getenv("CODEX_SKIP_GIT_REPO_CHECK", "false").lower() == "true"
    )
    GEMINI_CMD = os.getenv("GEMINI_CMD", "gemini")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "")
    CLAUDE_CMD = os.getenv("CLAUDE_CMD", "claude")
    CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "")

    GITHUB_MCP_URL = os.getenv("GITHUB_MCP_URL", "")

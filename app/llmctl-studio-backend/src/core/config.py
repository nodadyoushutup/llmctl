from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote_plus

REPO_ROOT = Path(__file__).resolve().parents[4]


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int = 0) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= minimum else default


def _env_float(name: str, default: float, *, minimum: float = 0.0) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value >= minimum else default


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    text = value.strip()
    return text or default


def _env_path_prefix(name: str, default: str) -> str:
    value = _env_str(name, default).strip()
    if value == "/":
        return "/"
    return f"/{value.strip('/')}"


def _build_studio_database_uri() -> str:
    direct_uri = os.getenv("LLMCTL_STUDIO_DATABASE_URI", "").strip()
    if direct_uri:
        return direct_uri

    host = os.getenv("LLMCTL_POSTGRES_HOST", "").strip()
    port = os.getenv("LLMCTL_POSTGRES_PORT", "").strip()
    database = os.getenv("LLMCTL_POSTGRES_DB", "").strip()
    user = os.getenv("LLMCTL_POSTGRES_USER", "").strip()
    password = os.getenv("LLMCTL_POSTGRES_PASSWORD", "").strip()
    if not all((host, port, database, user, password)):
        return ""
    safe_user = quote_plus(user)
    safe_password = quote_plus(password)
    return (
        f"postgresql+psycopg://{safe_user}:{safe_password}@{host}:{port}/{database}"
    )


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
    SQLALCHEMY_DATABASE_URI = _build_studio_database_uri()
    if not SQLALCHEMY_DATABASE_URI:
        raise RuntimeError(
            "PostgreSQL is required. Set LLMCTL_STUDIO_DATABASE_URI or "
            "LLMCTL_POSTGRES_HOST, LLMCTL_POSTGRES_PORT, LLMCTL_POSTGRES_DB, "
            "LLMCTL_POSTGRES_USER, and LLMCTL_POSTGRES_PASSWORD."
        )
    if SQLALCHEMY_DATABASE_URI.lower().startswith("sqlite:"):
        raise RuntimeError(
            "SQLite is no longer supported. Configure LLMCTL_STUDIO_DATABASE_URI "
            "with a PostgreSQL URL."
        )
    if not SQLALCHEMY_DATABASE_URI.lower().startswith("postgresql"):
        raise RuntimeError(
            "Only PostgreSQL is supported for LLMCTL_STUDIO_DATABASE_URI."
        )

    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev")
    API_PREFIX = _env_path_prefix("LLMCTL_STUDIO_API_PREFIX", "/api")
    REACT_ONLY_RUNTIME = _env_bool("LLMCTL_STUDIO_REACT_ONLY_RUNTIME", True)
    PREFERRED_URL_SCHEME = os.getenv("LLMCTL_STUDIO_PREFERRED_URL_SCHEME", "http")

    # Reverse proxy trust controls. Keep disabled unless explicitly enabled.
    PROXY_FIX_ENABLED = _env_bool("LLMCTL_STUDIO_PROXY_FIX_ENABLED", False)
    PROXY_FIX_X_FOR = _env_int("LLMCTL_STUDIO_PROXY_FIX_X_FOR", 1, minimum=0)
    PROXY_FIX_X_PROTO = _env_int("LLMCTL_STUDIO_PROXY_FIX_X_PROTO", 1, minimum=0)
    PROXY_FIX_X_HOST = _env_int("LLMCTL_STUDIO_PROXY_FIX_X_HOST", 1, minimum=0)
    PROXY_FIX_X_PORT = _env_int("LLMCTL_STUDIO_PROXY_FIX_X_PORT", 1, minimum=0)
    PROXY_FIX_X_PREFIX = _env_int("LLMCTL_STUDIO_PROXY_FIX_X_PREFIX", 1, minimum=0)

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
        CELERY_RESULT_BACKEND = "cache+memory://"
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
    SOCKETIO_REDIS_DB = _env_str(
        "LLMCTL_STUDIO_SOCKETIO_REDIS_DB",
        CELERY_REDIS_BROKER_DB,
    )
    _DEFAULT_SOCKETIO_MESSAGE_QUEUE = (
        f"redis://{CELERY_REDIS_HOST}:{CELERY_REDIS_PORT}/{SOCKETIO_REDIS_DB}"
    )
    SOCKETIO_MESSAGE_QUEUE = _env_str(
        "LLMCTL_STUDIO_SOCKETIO_MESSAGE_QUEUE",
        _DEFAULT_SOCKETIO_MESSAGE_QUEUE,
    )
    SOCKETIO_ASYNC_MODE = _env_str("LLMCTL_STUDIO_SOCKETIO_ASYNC_MODE", "threading")
    SOCKETIO_PATH = _env_str("LLMCTL_STUDIO_SOCKETIO_PATH", "socket.io")
    SOCKETIO_CORS_ALLOWED_ORIGINS = _env_str(
        "LLMCTL_STUDIO_SOCKETIO_CORS_ALLOWED_ORIGINS",
        "*",
    )
    SOCKETIO_TRANSPORTS = _env_str(
        "LLMCTL_STUDIO_SOCKETIO_TRANSPORTS",
        "websocket,polling",
    )
    SOCKETIO_PING_INTERVAL = _env_float(
        "LLMCTL_STUDIO_SOCKETIO_PING_INTERVAL",
        25.0,
        minimum=1.0,
    )
    SOCKETIO_PING_TIMEOUT = _env_float(
        "LLMCTL_STUDIO_SOCKETIO_PING_TIMEOUT",
        60.0,
        minimum=1.0,
    )
    SOCKETIO_MONITOR_CLIENTS = _env_bool("LLMCTL_STUDIO_SOCKETIO_MONITOR_CLIENTS", True)
    SOCKETIO_LOGGER = _env_bool("LLMCTL_STUDIO_SOCKETIO_LOGGER", False)
    SOCKETIO_ENGINEIO_LOGGER = _env_bool(
        "LLMCTL_STUDIO_SOCKETIO_ENGINEIO_LOGGER",
        False,
    )

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
    CLAUDE_CLI_AUTO_INSTALL = (
        os.getenv("CLAUDE_CLI_AUTO_INSTALL", "false").lower() == "true"
    )
    CLAUDE_CLI_REQUIRE_READY = (
        os.getenv("CLAUDE_CLI_REQUIRE_READY", "true").lower() == "true"
    )
    CLAUDE_CLI_INSTALL_SCRIPT = os.getenv(
        "CLAUDE_CLI_INSTALL_SCRIPT",
        "scripts/install/install-claude-cli.sh",
    )
    CLAUDE_AUTH_REQUIRE_API_KEY = (
        os.getenv("CLAUDE_AUTH_REQUIRE_API_KEY", "true").lower() == "true"
    )
    VLLM_LOCAL_CMD = os.getenv("VLLM_LOCAL_CMD", "vllm")
    VLLM_REMOTE_BASE_URL = os.getenv("VLLM_REMOTE_BASE_URL", "")
    VLLM_REMOTE_API_KEY = os.getenv("VLLM_REMOTE_API_KEY", "")
    _VLLM_LOCAL_CUSTOM_MODELS_DIR_ENV = os.getenv(
        "LLMCTL_STUDIO_VLLM_LOCAL_CUSTOM_MODELS_DIR"
    )
    if _VLLM_LOCAL_CUSTOM_MODELS_DIR_ENV:
        VLLM_LOCAL_CUSTOM_MODELS_DIR = str(Path(_VLLM_LOCAL_CUSTOM_MODELS_DIR_ENV))
    else:
        VLLM_LOCAL_CUSTOM_MODELS_DIR = str(_ensure_dir(Path(DATA_DIR) / "models"))
    VLLM_LOCAL_FALLBACK_MODEL = os.getenv(
        "VLLM_LOCAL_FALLBACK_MODEL", ""
    )
    VLLM_REMOTE_DEFAULT_MODEL = os.getenv("VLLM_REMOTE_DEFAULT_MODEL", "GLM-4.7-Flash")

    CHROMA_HOST = os.getenv("CHROMA_HOST", "")
    CHROMA_PORT = os.getenv("CHROMA_PORT", "")
    CHROMA_SSL = os.getenv("CHROMA_SSL", "false")

    GITHUB_MCP_URL = os.getenv("GITHUB_MCP_URL", "")

    NODE_EXECUTOR_PROVIDER = os.getenv("LLMCTL_NODE_EXECUTOR_PROVIDER", "kubernetes")
    NODE_EXECUTOR_DISPATCH_TIMEOUT_SECONDS = os.getenv(
        "LLMCTL_NODE_EXECUTOR_DISPATCH_TIMEOUT_SECONDS",
        "300",
    )
    NODE_EXECUTOR_EXECUTION_TIMEOUT_SECONDS = os.getenv(
        "LLMCTL_NODE_EXECUTOR_EXECUTION_TIMEOUT_SECONDS",
        "1800",
    )
    NODE_EXECUTOR_LOG_COLLECTION_TIMEOUT_SECONDS = os.getenv(
        "LLMCTL_NODE_EXECUTOR_LOG_COLLECTION_TIMEOUT_SECONDS",
        "30",
    )
    NODE_EXECUTOR_CANCEL_GRACE_TIMEOUT_SECONDS = os.getenv(
        "LLMCTL_NODE_EXECUTOR_CANCEL_GRACE_TIMEOUT_SECONDS",
        "15",
    )
    NODE_EXECUTOR_CANCEL_FORCE_KILL_ENABLED = (
        os.getenv("LLMCTL_NODE_EXECUTOR_CANCEL_FORCE_KILL_ENABLED", "true")
        .strip()
        .lower()
        in {"1", "true", "yes", "on"}
    )
    NODE_EXECUTOR_WORKSPACE_IDENTITY_KEY = os.getenv(
        "LLMCTL_NODE_EXECUTOR_WORKSPACE_IDENTITY_KEY",
        "default",
    )
    NODE_EXECUTOR_AGENT_RUNTIME_CUTOVER_ENABLED = (
        os.getenv("LLMCTL_NODE_EXECUTOR_AGENT_RUNTIME_CUTOVER_ENABLED", "false")
        .strip()
        .lower()
        in {"1", "true", "yes", "on"}
    )
    NODE_EXECUTOR_K8S_NAMESPACE = os.getenv(
        "LLMCTL_NODE_EXECUTOR_K8S_NAMESPACE",
        "default",
    )
    NODE_EXECUTOR_K8S_IMAGE = os.getenv(
        "LLMCTL_NODE_EXECUTOR_K8S_IMAGE",
        "llmctl-executor-frontier:latest",
    )
    NODE_EXECUTOR_K8S_FRONTIER_IMAGE = os.getenv(
        "LLMCTL_NODE_EXECUTOR_K8S_FRONTIER_IMAGE",
        NODE_EXECUTOR_K8S_IMAGE or "llmctl-executor-frontier:latest",
    )
    NODE_EXECUTOR_K8S_VLLM_IMAGE = os.getenv(
        "LLMCTL_NODE_EXECUTOR_K8S_VLLM_IMAGE",
        "llmctl-executor-vllm:latest",
    )
    NODE_EXECUTOR_K8S_FRONTIER_IMAGE_TAG = os.getenv(
        "LLMCTL_NODE_EXECUTOR_K8S_FRONTIER_IMAGE_TAG",
        "",
    )
    NODE_EXECUTOR_K8S_VLLM_IMAGE_TAG = os.getenv(
        "LLMCTL_NODE_EXECUTOR_K8S_VLLM_IMAGE_TAG",
        "",
    )
    NODE_EXECUTOR_K8S_IN_CLUSTER = (
        os.getenv("LLMCTL_NODE_EXECUTOR_K8S_IN_CLUSTER", "false")
        .strip()
        .lower()
        in {"1", "true", "yes", "on"}
    )
    NODE_EXECUTOR_K8S_SERVICE_ACCOUNT = os.getenv(
        "LLMCTL_NODE_EXECUTOR_K8S_SERVICE_ACCOUNT",
        "",
    )
    NODE_EXECUTOR_K8S_GPU_LIMIT = os.getenv(
        "LLMCTL_NODE_EXECUTOR_K8S_GPU_LIMIT",
        "0",
    )
    NODE_EXECUTOR_K8S_JOB_TTL_SECONDS = os.getenv(
        "LLMCTL_NODE_EXECUTOR_K8S_JOB_TTL_SECONDS",
        "1800",
    )
    NODE_EXECUTOR_K8S_IMAGE_PULL_SECRETS_JSON = os.getenv(
        "LLMCTL_NODE_EXECUTOR_K8S_IMAGE_PULL_SECRETS_JSON",
        "",
    )

from __future__ import annotations

import os
import sys
from multiprocessing import cpu_count
from pathlib import Path

TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}


def _as_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= minimum else default


def _as_str(name: str, default: str) -> str:
    value = os.getenv(name, "").strip()
    return value or default


def _as_optional_str(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


def _as_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    if raw in TRUE_VALUES:
        return True
    if raw in FALSE_VALUES:
        return False
    return default


def _as_mode(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default

    for base in (8, 10):
        try:
            value = int(raw, base)
        except ValueError:
            continue
        if 0 <= value <= 0o777:
            return value
    return default


def _default_bind() -> str:
    host = _as_str("FLASK_HOST", "0.0.0.0")
    port = _as_int("FLASK_PORT", 5055, minimum=1)
    return f"{host}:{port}"


def _default_workers() -> int:
    cores = max(1, cpu_count())
    return max(2, min(8, (cores * 2) + 1))


def _warn(message: str) -> None:
    print(f"[gunicorn-config] {message}", file=sys.stderr)


def _socket_path_is_usable(path: str) -> bool:
    socket_path = Path(path)
    parent = socket_path.parent if str(socket_path.parent) else Path(".")
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False

    if not os.access(parent, os.W_OK | os.X_OK):
        return False

    if socket_path.exists() and not os.access(socket_path, os.W_OK):
        return False

    return True


def _resolve_control_socket(path: str) -> tuple[str, bool]:
    if _socket_path_is_usable(path):
        return path, False

    fallback = "/tmp/gunicorn.ctl"
    if path != fallback and _socket_path_is_usable(fallback):
        _warn(
            f"control socket path '{path}' is not writable; "
            f"falling back to '{fallback}'."
        )
        return fallback, False

    _warn(
        f"control socket path '{path}' is not writable and fallback "
        f"'{fallback}' is unavailable; disabling Gunicorn control socket."
    )
    return path, True


bind = _as_str("GUNICORN_BIND", _default_bind())
workers = _as_int("GUNICORN_WORKERS", _default_workers(), minimum=1)
threads = _as_int("GUNICORN_THREADS", 4, minimum=1)
worker_class = _as_str("GUNICORN_WORKER_CLASS", "gthread")
worker_connections = _as_int("GUNICORN_WORKER_CONNECTIONS", 1000, minimum=1)
timeout = _as_int("GUNICORN_TIMEOUT", 120, minimum=1)
graceful_timeout = _as_int("GUNICORN_GRACEFUL_TIMEOUT", 30, minimum=1)
keepalive = _as_int("GUNICORN_KEEPALIVE", 5, minimum=1)
loglevel = _as_str("GUNICORN_LOG_LEVEL", "info")
accesslog = _as_str("GUNICORN_ACCESS_LOG", "-")
errorlog = _as_str("GUNICORN_ERROR_LOG", "-")
max_requests = _as_int("GUNICORN_MAX_REQUESTS", 1000, minimum=1)
max_requests_jitter = _as_int("GUNICORN_MAX_REQUESTS_JITTER", 100, minimum=0)
certfile = _as_optional_str("GUNICORN_CERTFILE")
keyfile = _as_optional_str("GUNICORN_KEYFILE")
ca_certs = _as_optional_str("GUNICORN_CA_CERTS")
control_socket = _as_str("GUNICORN_CONTROL_SOCKET", "/tmp/gunicorn.ctl")
control_socket_mode = _as_mode("GUNICORN_CONTROL_SOCKET_MODE", 0o660)
control_socket_disable = _as_bool("GUNICORN_CONTROL_SOCKET_DISABLE", False)

if not control_socket_disable:
    control_socket, auto_disable = _resolve_control_socket(control_socket)
    if auto_disable:
        control_socket_disable = True

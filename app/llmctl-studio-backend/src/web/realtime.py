from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from flask import Flask, request
from flask_socketio import SocketIO, emit, join_room, leave_room

REALTIME_NAMESPACE = "/rt"

logger = logging.getLogger(__name__)


def _default_message_queue_url() -> str | None:
    explicit = str(os.getenv("LLMCTL_STUDIO_SOCKETIO_MESSAGE_QUEUE", "")).strip()
    if explicit:
        return explicit
    redis_host = str(os.getenv("CELERY_REDIS_HOST", "127.0.0.1")).strip() or "127.0.0.1"
    redis_port = str(os.getenv("CELERY_REDIS_PORT", "6380")).strip() or "6380"
    redis_db = str(
        os.getenv(
            "LLMCTL_STUDIO_SOCKETIO_REDIS_DB",
            os.getenv("CELERY_REDIS_BROKER_DB", "0"),
        )
    ).strip() or "0"
    return f"redis://{redis_host}:{redis_port}/{redis_db}"


socketio = SocketIO(
    async_mode=str(os.getenv("LLMCTL_STUDIO_SOCKETIO_ASYNC_MODE", "threading")),
    message_queue=_default_message_queue_url(),
)

_metrics_lock = Lock()
_metrics = {
    "connect_total": 0,
    "disconnect_total": 0,
    "health_total": 0,
    "open_connections": 0,
}
_ALLOWED_ROOM_PREFIXES = {
    "task",
    "run",
    "flowchart",
    "flowchart_run",
    "flowchart_node",
    "thread",
    "download_job",
}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_cors_allowed_origins(raw_value: str) -> str | list[str]:
    value = (raw_value or "").strip()
    if not value:
        return "*"
    if value == "*":
        return "*"
    origins = [item.strip() for item in value.split(",") if item.strip()]
    return origins if origins else "*"


def _parse_transports(raw_value: str) -> list[str] | None:
    values = [item.strip() for item in (raw_value or "").split(",") if item.strip()]
    return values or None


def _metrics_snapshot() -> dict[str, int]:
    with _metrics_lock:
        return dict(_metrics)


def _normalize_room_keys(payload: dict[str, Any] | None) -> list[str]:
    if not isinstance(payload, dict):
        return []
    raw_rooms = payload.get("rooms")
    if not isinstance(raw_rooms, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in raw_rooms:
        room = str(raw or "").strip()
        if not room or room in seen:
            continue
        prefix, _, suffix = room.partition(":")
        if prefix not in _ALLOWED_ROOM_PREFIXES:
            continue
        if not suffix:
            continue
        seen.add(room)
        normalized.append(room)
    return normalized


def _increment_metric(name: str, delta: int = 1) -> dict[str, int]:
    with _metrics_lock:
        _metrics[name] = int(_metrics.get(name, 0)) + delta
        if name == "disconnect_total":
            _metrics["open_connections"] = max(0, _metrics["open_connections"] - 1)
        if name == "connect_total":
            _metrics["open_connections"] = int(_metrics.get("open_connections", 0)) + 1
        return dict(_metrics)


def init_socketio(app: Flask) -> None:
    socketio.init_app(
        app,
        async_mode=str(app.config.get("SOCKETIO_ASYNC_MODE", "threading")),
        message_queue=str(app.config.get("SOCKETIO_MESSAGE_QUEUE", "")).strip() or None,
        cors_allowed_origins=_parse_cors_allowed_origins(
            str(app.config.get("SOCKETIO_CORS_ALLOWED_ORIGINS", "*"))
        ),
        path=str(app.config.get("SOCKETIO_PATH", "socket.io")).strip() or "socket.io",
        logger=bool(app.config.get("SOCKETIO_LOGGER", False)),
        engineio_logger=bool(app.config.get("SOCKETIO_ENGINEIO_LOGGER", False)),
        ping_interval=float(app.config.get("SOCKETIO_PING_INTERVAL", 25.0)),
        ping_timeout=float(app.config.get("SOCKETIO_PING_TIMEOUT", 60.0)),
        monitor_clients=bool(app.config.get("SOCKETIO_MONITOR_CLIENTS", True)),
        transports=_parse_transports(str(app.config.get("SOCKETIO_TRANSPORTS", ""))),
    )
    app.extensions["llmctl.socketio"] = socketio


def emit_realtime(
    event_name: str,
    payload: dict[str, Any] | None = None,
    *,
    room: str | None = None,
    namespace: str = REALTIME_NAMESPACE,
) -> None:
    try:
        socketio.emit(event_name, payload or {}, room=room, namespace=namespace)
    except Exception:
        logger.exception(
            "Realtime emit failed event=%s room=%s namespace=%s",
            event_name,
            room,
            namespace,
        )


@socketio.on("connect", namespace=REALTIME_NAMESPACE)
def _on_connect(auth: dict[str, Any] | None = None):
    metrics = _increment_metric("connect_total")
    transport = str(request.args.get("transport", "") or "unknown")
    logger.info(
        "Socket connect sid=%s namespace=%s transport=%s open=%s",
        request.sid,
        REALTIME_NAMESPACE,
        transport,
        metrics.get("open_connections", 0),
    )
    emit(
        "rt.connected",
        {
            "ok": True,
            "namespace": REALTIME_NAMESPACE,
            "sid": request.sid,
            "server_time": _utcnow_iso(),
            "transport": transport,
            "metrics": metrics,
            "auth_provided": bool(auth),
        },
        namespace=REALTIME_NAMESPACE,
    )


@socketio.on("disconnect", namespace=REALTIME_NAMESPACE)
def _on_disconnect(*_args: Any):
    metrics = _increment_metric("disconnect_total")
    logger.info(
        "Socket disconnect sid=%s namespace=%s open=%s",
        request.sid,
        REALTIME_NAMESPACE,
        metrics.get("open_connections", 0),
    )


@socketio.on("rt.health", namespace=REALTIME_NAMESPACE)
def _on_health(payload: dict[str, Any] | None = None):
    metrics = _increment_metric("health_total")
    return {
        "ok": True,
        "namespace": REALTIME_NAMESPACE,
        "server_time": _utcnow_iso(),
        "metrics": metrics,
        "echo": payload or {},
    }


@socketio.on("rt.subscribe", namespace=REALTIME_NAMESPACE)
def _on_subscribe(payload: dict[str, Any] | None = None):
    rooms = _normalize_room_keys(payload)
    for room in rooms:
        join_room(room)
    if rooms:
        logger.info(
            "Socket subscribe sid=%s namespace=%s rooms=%s",
            request.sid,
            REALTIME_NAMESPACE,
            ",".join(rooms),
        )
    return {
        "ok": True,
        "rooms": rooms,
        "namespace": REALTIME_NAMESPACE,
        "server_time": _utcnow_iso(),
    }


@socketio.on("rt.unsubscribe", namespace=REALTIME_NAMESPACE)
def _on_unsubscribe(payload: dict[str, Any] | None = None):
    rooms = _normalize_room_keys(payload)
    for room in rooms:
        leave_room(room)
    if rooms:
        logger.info(
            "Socket unsubscribe sid=%s namespace=%s rooms=%s",
            request.sid,
            REALTIME_NAMESPACE,
            ",".join(rooms),
        )
    return {
        "ok": True,
        "rooms": rooms,
        "namespace": REALTIME_NAMESPACE,
        "server_time": _utcnow_iso(),
    }


def realtime_status_payload() -> dict[str, Any]:
    return {
        "ok": True,
        "namespace": REALTIME_NAMESPACE,
        "server_time": _utcnow_iso(),
        "metrics": _metrics_snapshot(),
    }

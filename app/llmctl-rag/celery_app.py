from __future__ import annotations

import os

from celery import Celery


def _env(key: str, default: str) -> str:
    value = (os.getenv(key) or "").strip()
    return value or default


BROKER_URL = _env(
    "LLMCTL_RAG_CELERY_BROKER_URL",
    _env("CELERY_BROKER_URL", "redis://192.168.1.36:6379/0"),
)
RESULT_BACKEND = _env(
    "LLMCTL_RAG_CELERY_RESULT_BACKEND",
    _env("CELERY_RESULT_BACKEND", ""),
)

celery_app = Celery("llmctl_rag")
celery_config = {
    "broker_url": BROKER_URL,
    "task_track_started": True,
    "task_serializer": "json",
    "accept_content": ["json"],
    "result_serializer": "json",
    "timezone": "UTC",
}
if RESULT_BACKEND:
    celery_config["result_backend"] = RESULT_BACKEND
celery_app.conf.update(celery_config)

import tasks_worker  # noqa: E402,F401

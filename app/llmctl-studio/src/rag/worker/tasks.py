from __future__ import annotations

import logging
from typing import Any

try:
    from celery.utils.log import get_task_logger
except ModuleNotFoundError:  # pragma: no cover
    def get_task_logger(name: str):
        return logging.getLogger(name)

try:
    from services.celery_app import celery_app
except ModuleNotFoundError:  # pragma: no cover
    class _NoopCeleryApp:
        def task(self, *args, **kwargs):
            def _decorator(fn):
                fn.run = fn
                fn.apply_async = lambda *a, **k: None
                return fn

            return _decorator

    celery_app = _NoopCeleryApp()

from rag.repositories.sources import get_source

logger = get_task_logger(__name__)

DECOMMISSIONED_MESSAGE = (
    "Standalone RAG index jobs are decommissioned. Use flowchart RAG nodes instead."
)

INDEX_MODE_FRESH = "fresh"
INDEX_MODE_DELTA = "delta"
TASK_KIND_INDEX = "index"
TASK_STATUS_QUEUED = "queued"
TASK_STATUS_CANCELLED = "cancelled"
TASK_STATUS_FAILED = "failed"
TASK_STATUS_PAUSED = "paused"
TASK_STATUS_PAUSING = "pausing"
TASK_STATUS_SUCCEEDED = "succeeded"
TASK_ACTIVE_STATUSES: set[str] = set()


def get_task(task_id: int):
    _ = task_id
    return None


def task_meta(task) -> dict[str, Any]:
    _ = task
    return {}


def set_task_meta(task_id: int, meta: dict[str, Any]):
    _ = task_id, meta
    return None


def append_task_output(task_id: int, message: str):
    _ = task_id, message
    return None


def mark_task_running(task_id: int, *, celery_task_id: str | None = None):
    _ = task_id, celery_task_id
    return None


def mark_task_finished(
    task_id: int,
    *,
    status: str,
    output: str | None = None,
    error: str | None = None,
):
    _ = task_id, status, output, error
    return None


def mark_task_paused(
    task_id: int,
    *,
    message: str = "Task paused. Resume to continue indexing from checkpoint.",
):
    _ = task_id, message
    return None


def list_active_tasks(
    kind: str | None = None,
    source_id: int | None = None,
):
    _ = kind, source_id
    return []


@celery_app.task(bind=True, name="rag.worker.tasks.run_index_task")
def run_index_task(
    self,
    task_id: int,
    source_id: int,
    reset: bool = False,
    index_mode: str = INDEX_MODE_FRESH,
):
    _ = self, task_id, source_id, reset, index_mode
    logger.warning(DECOMMISSIONED_MESSAGE)
    return {
        "ok": False,
        "deprecated": True,
        "error": DECOMMISSIONED_MESSAGE,
    }


def start_source_index_job(
    source_id: int,
    *,
    reset: bool = False,
    index_mode: str = INDEX_MODE_FRESH,
    trigger_mode: str = "manual",
):
    _ = reset, index_mode, trigger_mode
    source = get_source(source_id)
    if not source:
        raise ValueError("Source not found.")
    logger.warning(DECOMMISSIONED_MESSAGE)
    return None


def resume_source_index_job(source_id: int):
    _ = source_id
    logger.warning(DECOMMISSIONED_MESSAGE)
    return None


def pause_source_index_job(source_id: int):
    _ = source_id
    logger.warning(DECOMMISSIONED_MESSAGE)
    return None


def cancel_source_index_job(source_id: int):
    _ = source_id
    logger.warning(DECOMMISSIONED_MESSAGE)
    return None


def source_index_job_snapshot(source_id: int) -> dict[str, Any]:
    source = get_source(source_id)
    if not source:
        raise ValueError("Source not found.")
    return {
        "running": False,
        "status": None,
        "index_mode": None,
        "source_id": source_id,
        "last_started_at": None,
        "last_finished_at": None,
        "last_error": getattr(source, "last_error", None),
        "last_indexed_at": (
            source.last_indexed_at.isoformat() if getattr(source, "last_indexed_at", None) else None
        ),
        "can_resume": False,
        "paused_job_id": None,
        "progress": None,
        "decommissioned": True,
        "message": DECOMMISSIONED_MESSAGE,
    }

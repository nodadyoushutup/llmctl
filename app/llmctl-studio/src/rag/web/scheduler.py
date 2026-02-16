from __future__ import annotations

import os
import threading
from datetime import datetime, timezone

from core.db import utcnow
from core.models import RAG_INDEX_TRIGGER_SCHEDULED
from rag.repositories.index_jobs import has_active_index_job
from rag.repositories.sources import list_due_sources, schedule_source_next_index
from rag.worker.tasks import start_source_index_job

_SOURCE_SCHEDULER_STOP = threading.Event()
_SOURCE_SCHEDULER_LOCK = threading.Lock()
_SOURCE_SCHEDULER_THREAD: threading.Thread | None = None


def _coerce_datetime_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def source_scheduler_enabled() -> bool:
    value = (
        os.getenv("LLMCTL_STUDIO_RAG_SOURCE_SCHEDULER", "true") or ""
    ).strip().lower()
    return value in {"1", "true", "yes", "on"}


def source_scheduler_poll_seconds() -> float:
    raw = (
        os.getenv("LLMCTL_STUDIO_RAG_SOURCE_SCHEDULER_POLL_SECONDS", "15") or ""
    ).strip()
    try:
        parsed = float(raw)
    except ValueError:
        return 15.0
    return max(5.0, parsed)


def run_scheduled_source_indexes_once(*, now: datetime | None = None) -> int:
    now_utc = _coerce_datetime_utc(now) or utcnow()
    started = 0
    for source in list_due_sources(now=now_utc):
        if has_active_index_job(source_id=source.id):
            continue
        schedule_mode = (getattr(source, "index_schedule_mode", "fresh") or "fresh").strip().lower()
        job = start_source_index_job(
            source.id,
            reset=False,
            index_mode=schedule_mode,
            trigger_mode=RAG_INDEX_TRIGGER_SCHEDULED,
        )
        if job is None:
            continue
        schedule_source_next_index(source.id, from_time=now_utc)
        started += 1
    return started


def _source_scheduler_loop() -> None:
    poll_seconds = source_scheduler_poll_seconds()
    while not _SOURCE_SCHEDULER_STOP.is_set():
        try:
            run_scheduled_source_indexes_once()
        except Exception:
            pass
        _SOURCE_SCHEDULER_STOP.wait(poll_seconds)


def start_source_scheduler() -> None:
    global _SOURCE_SCHEDULER_THREAD
    if not source_scheduler_enabled():
        return
    with _SOURCE_SCHEDULER_LOCK:
        if _SOURCE_SCHEDULER_THREAD and _SOURCE_SCHEDULER_THREAD.is_alive():
            return
        _SOURCE_SCHEDULER_STOP.clear()
        thread = threading.Thread(
            target=_source_scheduler_loop,
            name="llmctl-studio-rag-source-scheduler",
            daemon=True,
        )
        _SOURCE_SCHEDULER_THREAD = thread
        thread.start()


def stop_source_scheduler(timeout: float = 2.0) -> None:
    global _SOURCE_SCHEDULER_THREAD
    with _SOURCE_SCHEDULER_LOCK:
        thread = _SOURCE_SCHEDULER_THREAD
        if not thread:
            return
        _SOURCE_SCHEDULER_STOP.set()
    thread.join(timeout=timeout)
    with _SOURCE_SCHEDULER_LOCK:
        if _SOURCE_SCHEDULER_THREAD is thread:
            _SOURCE_SCHEDULER_THREAD = None
        _SOURCE_SCHEDULER_STOP.clear()

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select

from core.db import session_scope, utcnow
from core.models import (
    RAG_INDEX_JOB_ACTIVE_STATUSES,
    RAG_INDEX_JOB_KIND_INDEX,
    RAG_INDEX_JOB_STATUS_CANCELLED,
    RAG_INDEX_JOB_STATUS_CHOICES,
    RAG_INDEX_JOB_STATUS_FAILED,
    RAG_INDEX_JOB_STATUS_PAUSED,
    RAG_INDEX_JOB_STATUS_PAUSING,
    RAG_INDEX_JOB_STATUS_QUEUED,
    RAG_INDEX_JOB_STATUS_RUNNING,
    RAG_INDEX_JOB_STATUS_SUCCEEDED,
    RAG_INDEX_MODE_CHOICES,
    RAG_INDEX_MODE_FRESH,
    RAG_INDEX_TRIGGER_CHOICES,
    RAG_INDEX_TRIGGER_MANUAL,
    RAGIndexJob,
)

INDEX_JOB_META_DEFAULTS: dict[str, Any] = {
    "checkpoint": {
        "stage": None,
        "cursor": None,
        "updated_at": None,
    },
    "progress": {
        "phase": "queued",
        "message": None,
        "percent": 0.0,
        "files_total": 0,
        "files_completed": 0,
        "chunks_total": 0,
        "chunks_indexed": 0,
    },
}


def list_index_jobs(
    *,
    limit: int | None = 200,
    source_id: int | None = None,
) -> list[RAGIndexJob]:
    with session_scope() as session:
        stmt = select(RAGIndexJob).order_by(RAGIndexJob.created_at.desc())
        if source_id is not None:
            stmt = stmt.where(RAGIndexJob.source_id == source_id)
        if limit is not None:
            stmt = stmt.limit(limit)
        return session.execute(stmt).scalars().all()


def get_index_job(job_id: int) -> RAGIndexJob | None:
    with session_scope() as session:
        return session.get(RAGIndexJob, job_id)


def create_index_job(
    *,
    source_id: int,
    kind: str = RAG_INDEX_JOB_KIND_INDEX,
    status: str = RAG_INDEX_JOB_STATUS_QUEUED,
    mode: str = RAG_INDEX_MODE_FRESH,
    trigger_mode: str = RAG_INDEX_TRIGGER_MANUAL,
    meta: dict[str, Any] | None = None,
) -> RAGIndexJob:
    if int(source_id) <= 0:
        raise ValueError("source_id must be a positive integer.")
    normalized_mode = _normalize_mode(mode)
    normalized_trigger = _normalize_trigger_mode(trigger_mode)
    normalized_status = _normalize_status(status)
    meta_json = _serialize_meta(meta)
    with session_scope() as session:
        job = RAGIndexJob.create(
            session,
            kind=(kind or RAG_INDEX_JOB_KIND_INDEX).strip().lower() or RAG_INDEX_JOB_KIND_INDEX,
            source_id=source_id,
            status=normalized_status,
            mode=normalized_mode,
            trigger_mode=normalized_trigger,
            meta_json=meta_json,
        )
        return job


def delete_index_job(job_id: int) -> None:
    with session_scope() as session:
        job = session.get(RAGIndexJob, job_id)
        if job:
            job.delete(session)


def update_index_job(job_id: int, **fields: Any) -> RAGIndexJob | None:
    with session_scope() as session:
        job = session.get(RAGIndexJob, job_id)
        if not job:
            return None
        for key, value in fields.items():
            if hasattr(job, key):
                setattr(job, key, value)
        job.updated_at = utcnow()
        return job.save(session)


def set_index_job_celery_id(job_id: int, celery_task_id: str | None) -> RAGIndexJob | None:
    return update_index_job(job_id, celery_task_id=celery_task_id)


def mark_index_job_running(
    job_id: int,
    *,
    celery_task_id: str | None = None,
    progress_message: str | None = None,
) -> RAGIndexJob | None:
    return _update_index_job_meta_and_fields(
        job_id,
        fields={
            "status": RAG_INDEX_JOB_STATUS_RUNNING,
            "started_at": utcnow(),
            "celery_task_id": celery_task_id,
        },
        progress={"phase": "running", "message": progress_message},
    )


def mark_index_job_finished(
    job_id: int,
    *,
    status: str,
    output: str | None = None,
    error: str | None = None,
    progress_message: str | None = None,
) -> RAGIndexJob | None:
    normalized_status = _normalize_status(status)
    if normalized_status in RAG_INDEX_JOB_ACTIVE_STATUSES:
        raise ValueError("Finished status must be terminal.")
    phase = {
        RAG_INDEX_JOB_STATUS_SUCCEEDED: "succeeded",
        RAG_INDEX_JOB_STATUS_FAILED: "failed",
        RAG_INDEX_JOB_STATUS_CANCELLED: "cancelled",
        RAG_INDEX_JOB_STATUS_PAUSED: "paused",
    }.get(normalized_status, normalized_status)
    fields: dict[str, Any] = {
        "status": normalized_status,
        "finished_at": utcnow(),
        "error": error,
    }
    if output is not None:
        fields["output"] = output
    return _update_index_job_meta_and_fields(
        job_id,
        fields=fields,
        progress={"phase": phase, "message": progress_message},
    )


def pause_index_job(
    job_id: int,
    *,
    message: str = "Pause requested by user.",
) -> RAGIndexJob | None:
    with session_scope() as session:
        job = session.get(RAGIndexJob, job_id)
        if not job:
            return None
        if job.status == RAG_INDEX_JOB_STATUS_QUEUED:
            job.status = RAG_INDEX_JOB_STATUS_PAUSED
            job.finished_at = utcnow()
        elif job.status in {RAG_INDEX_JOB_STATUS_RUNNING, RAG_INDEX_JOB_STATUS_PAUSING}:
            job.status = RAG_INDEX_JOB_STATUS_PAUSING
        _merge_meta_progress(job, {"phase": job.status, "message": message})
        job.error = None
        job.updated_at = utcnow()
        return job.save(session)


def resume_index_job(job_id: int) -> RAGIndexJob | None:
    with session_scope() as session:
        job = session.get(RAGIndexJob, job_id)
        if not job:
            return None
        if job.status != RAG_INDEX_JOB_STATUS_PAUSED:
            return job
        job.status = RAG_INDEX_JOB_STATUS_QUEUED
        job.started_at = None
        job.finished_at = None
        job.error = None
        job.celery_task_id = None
        _merge_meta_progress(job, {"phase": "queued", "message": "Resumed by user."})
        job.updated_at = utcnow()
        return job.save(session)


def cancel_index_job(
    job_id: int,
    *,
    message: str = "Index job cancelled by user.",
) -> RAGIndexJob | None:
    return _update_index_job_meta_and_fields(
        job_id,
        fields={
            "status": RAG_INDEX_JOB_STATUS_CANCELLED,
            "error": message,
            "finished_at": utcnow(),
        },
        progress={"phase": "cancelled", "message": message},
    )


def latest_index_job(
    *,
    source_id: int | None = None,
    statuses: set[str] | None = None,
) -> RAGIndexJob | None:
    with session_scope() as session:
        stmt = select(RAGIndexJob)
        if source_id is not None:
            stmt = stmt.where(RAGIndexJob.source_id == source_id)
        if statuses:
            stmt = stmt.where(RAGIndexJob.status.in_(list(statuses)))
        stmt = stmt.order_by(RAGIndexJob.created_at.desc())
        return session.execute(stmt).scalars().first()


def list_active_index_jobs(*, source_id: int | None = None) -> list[RAGIndexJob]:
    with session_scope() as session:
        stmt = select(RAGIndexJob).where(
            RAGIndexJob.status.in_(RAG_INDEX_JOB_ACTIVE_STATUSES)
        )
        if source_id is not None:
            stmt = stmt.where(RAGIndexJob.source_id == source_id)
        stmt = stmt.order_by(RAGIndexJob.created_at.desc())
        return session.execute(stmt).scalars().all()


def active_index_job(*, source_id: int | None = None) -> RAGIndexJob | None:
    jobs = list_active_index_jobs(source_id=source_id)
    return jobs[0] if jobs else None


def has_active_index_job(*, source_id: int | None = None) -> bool:
    return active_index_job(source_id=source_id) is not None


def index_job_meta(job: RAGIndexJob) -> dict[str, Any]:
    raw = (job.meta_json or "").strip()
    if not raw:
        return _default_meta()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return _default_meta()
    if not isinstance(payload, dict):
        return _default_meta()
    return _normalize_meta(payload)


def set_index_job_meta(job_id: int, meta: dict[str, Any]) -> RAGIndexJob | None:
    return update_index_job(job_id, meta_json=_serialize_meta(meta))


def update_index_job_checkpoint(
    job_id: int,
    checkpoint: dict[str, Any],
) -> RAGIndexJob | None:
    normalized = checkpoint if isinstance(checkpoint, dict) else {}
    normalized = {**normalized, "updated_at": utcnow().isoformat()}
    return _update_index_job_meta_and_fields(
        job_id,
        fields={},
        checkpoint=normalized,
    )


def update_index_job_progress(
    job_id: int,
    progress: dict[str, Any],
) -> RAGIndexJob | None:
    return _update_index_job_meta_and_fields(
        job_id,
        fields={},
        progress=progress if isinstance(progress, dict) else {},
    )


def format_dt(value: datetime | None) -> str | None:
    if not value:
        return None
    return value.isoformat()


def _update_index_job_meta_and_fields(
    job_id: int,
    *,
    fields: dict[str, Any],
    checkpoint: dict[str, Any] | None = None,
    progress: dict[str, Any] | None = None,
) -> RAGIndexJob | None:
    with session_scope() as session:
        job = session.get(RAGIndexJob, job_id)
        if not job:
            return None
        for key, value in fields.items():
            if hasattr(job, key):
                setattr(job, key, value)
        if checkpoint is not None:
            _merge_meta_checkpoint(job, checkpoint)
        if progress is not None:
            _merge_meta_progress(job, progress)
        job.updated_at = utcnow()
        return job.save(session)


def _merge_meta_checkpoint(job: RAGIndexJob, checkpoint: dict[str, Any]) -> None:
    meta = index_job_meta(job)
    current = meta.get("checkpoint") if isinstance(meta.get("checkpoint"), dict) else {}
    current.update(checkpoint)
    meta["checkpoint"] = current
    job.meta_json = json.dumps(meta, sort_keys=True)


def _merge_meta_progress(job: RAGIndexJob, progress: dict[str, Any]) -> None:
    meta = index_job_meta(job)
    current = meta.get("progress") if isinstance(meta.get("progress"), dict) else {}
    for key, value in progress.items():
        if value is None:
            continue
        current[key] = value
    meta["progress"] = current
    job.meta_json = json.dumps(meta, sort_keys=True)


def _serialize_meta(meta: dict[str, Any] | None) -> str:
    return json.dumps(_normalize_meta(meta or {}), sort_keys=True)


def _normalize_meta(meta: dict[str, Any]) -> dict[str, Any]:
    defaults = _default_meta()

    checkpoint_payload = meta.get("checkpoint")
    if isinstance(checkpoint_payload, dict):
        defaults["checkpoint"].update(checkpoint_payload)

    progress_payload = meta.get("progress")
    if isinstance(progress_payload, dict):
        defaults["progress"].update(progress_payload)

    phase = str(defaults["progress"].get("phase") or "queued").strip().lower()
    if not phase:
        phase = "queued"
    defaults["progress"]["phase"] = phase

    percent_value = defaults["progress"].get("percent", 0.0)
    try:
        defaults["progress"]["percent"] = max(0.0, min(100.0, float(percent_value)))
    except (TypeError, ValueError):
        defaults["progress"]["percent"] = 0.0

    for key in (
        "files_total",
        "files_completed",
        "chunks_total",
        "chunks_indexed",
    ):
        try:
            defaults["progress"][key] = max(0, int(defaults["progress"].get(key, 0)))
        except (TypeError, ValueError):
            defaults["progress"][key] = 0

    return defaults


def _default_meta() -> dict[str, Any]:
    return {
        "checkpoint": dict(INDEX_JOB_META_DEFAULTS["checkpoint"]),
        "progress": dict(INDEX_JOB_META_DEFAULTS["progress"]),
    }


def _normalize_status(value: str) -> str:
    status = (value or RAG_INDEX_JOB_STATUS_QUEUED).strip().lower()
    if status not in RAG_INDEX_JOB_STATUS_CHOICES:
        raise ValueError(
            "Index job status must be queued, running, pausing, paused, succeeded, failed, or cancelled."
        )
    return status


def _normalize_mode(value: str) -> str:
    mode = (value or RAG_INDEX_MODE_FRESH).strip().lower()
    if mode not in RAG_INDEX_MODE_CHOICES:
        raise ValueError("Index mode must be fresh or delta.")
    return mode


def _normalize_trigger_mode(value: str) -> str:
    trigger_mode = (value or RAG_INDEX_TRIGGER_MANUAL).strip().lower()
    if trigger_mode not in RAG_INDEX_TRIGGER_CHOICES:
        raise ValueError("Trigger mode must be manual or scheduled.")
    return trigger_mode

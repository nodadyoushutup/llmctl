from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select

from db import init_db, session_scope, utcnow
from models import Task

TASK_KIND_INDEX = "index"

TASK_STATUS_QUEUED = "queued"
TASK_STATUS_RUNNING = "running"
TASK_STATUS_PAUSING = "pausing"
TASK_STATUS_PAUSED = "paused"
TASK_STATUS_SUCCEEDED = "succeeded"
TASK_STATUS_FAILED = "failed"
TASK_STATUS_CANCELLED = "cancelled"

TASK_ACTIVE_STATUSES = {
    TASK_STATUS_QUEUED,
    TASK_STATUS_RUNNING,
    TASK_STATUS_PAUSING,
}


def list_tasks(limit: int | None = 200) -> list[Task]:
    init_db()
    with session_scope() as session:
        stmt = select(Task).order_by(Task.created_at.desc())
        if limit:
            stmt = stmt.limit(limit)
        return session.execute(stmt).scalars().all()


def get_task(task_id: int) -> Task | None:
    init_db()
    with session_scope() as session:
        return session.get(Task, task_id)


def get_tasks(task_ids: list[int]) -> list[Task]:
    if not task_ids:
        return []
    init_db()
    with session_scope() as session:
        stmt = select(Task).where(Task.id.in_(task_ids))
        return session.execute(stmt).scalars().all()


def create_task(
    *,
    kind: str,
    status: str = TASK_STATUS_QUEUED,
    source_id: int | None = None,
    meta: dict[str, Any] | None = None,
) -> Task:
    init_db()
    meta_json = json.dumps(meta, sort_keys=True) if meta else None
    with session_scope() as session:
        task = Task.create(
            session,
            kind=kind,
            status=status,
            source_id=source_id,
            meta_json=meta_json,
        )
        return task


def delete_task(task_id: int) -> None:
    init_db()
    with session_scope() as session:
        task = session.get(Task, task_id)
        if task:
            task.delete(session)


def update_task(task_id: int, **fields: Any) -> Task | None:
    init_db()
    with session_scope() as session:
        task = session.get(Task, task_id)
        if not task:
            return None
        for key, value in fields.items():
            if hasattr(task, key):
                setattr(task, key, value)
        task.updated_at = utcnow()
        return task.save(session)


def set_task_celery_id(task_id: int, celery_task_id: str | None) -> Task | None:
    return update_task(task_id, celery_task_id=celery_task_id)


def mark_task_running(task_id: int, *, celery_task_id: str | None = None) -> Task | None:
    return update_task(
        task_id,
        status=TASK_STATUS_RUNNING,
        started_at=utcnow(),
        celery_task_id=celery_task_id,
    )


def mark_task_finished(
    task_id: int,
    *,
    status: str,
    output: str | None = None,
    error: str | None = None,
) -> Task | None:
    fields: dict[str, Any] = {
        "status": status,
        "finished_at": utcnow(),
        "error": error,
    }
    if output is not None:
        fields["output"] = output
    return update_task(task_id, **fields)


def mark_task_paused(
    task_id: int, *, message: str = "Task paused."
) -> Task | None:
    init_db()
    with session_scope() as session:
        task = session.get(Task, task_id)
        if not task:
            return None
        existing = task.output or ""
        if message and (not existing or message not in existing):
            task.output = f"{existing}\n{message}" if existing else message
        task.status = TASK_STATUS_PAUSED
        task.finished_at = utcnow()
        task.error = None
        task.updated_at = utcnow()
        return task.save(session)


def cancel_task(task_id: int, *, message: str = "Task cancelled by user.") -> Task | None:
    init_db()
    with session_scope() as session:
        task = session.get(Task, task_id)
        if not task:
            return None
        if task.status not in TASK_ACTIVE_STATUSES:
            return task
        existing = task.output or ""
        task.output = f"{existing}\n{message}" if existing else message
        task.status = TASK_STATUS_CANCELLED
        task.error = message
        task.finished_at = utcnow()
        task.updated_at = utcnow()
        return task.save(session)


def pause_task(
    task_id: int, *, message: str = "Pause requested by user."
) -> Task | None:
    init_db()
    with session_scope() as session:
        task = session.get(Task, task_id)
        if not task:
            return None
        if task.status == TASK_STATUS_QUEUED:
            existing = task.output or ""
            task.output = f"{existing}\n{message}" if existing else message
            task.status = TASK_STATUS_PAUSED
            task.finished_at = utcnow()
            task.error = None
            task.updated_at = utcnow()
            return task.save(session)
        if task.status in {TASK_STATUS_RUNNING, TASK_STATUS_PAUSING}:
            existing = task.output or ""
            task.output = f"{existing}\n{message}" if existing else message
            task.status = TASK_STATUS_PAUSING
            task.error = None
            task.updated_at = utcnow()
            return task.save(session)
        return task


def resume_task(task_id: int) -> Task | None:
    init_db()
    with session_scope() as session:
        task = session.get(Task, task_id)
        if not task:
            return None
        if task.status != TASK_STATUS_PAUSED:
            return task
        task.status = TASK_STATUS_QUEUED
        task.started_at = None
        task.finished_at = None
        task.error = None
        task.celery_task_id = None
        task.updated_at = utcnow()
        return task.save(session)


def append_task_output(task_id: int, message: str) -> Task | None:
    if not message:
        return None
    init_db()
    with session_scope() as session:
        task = session.get(Task, task_id)
        if not task:
            return None
        existing = task.output or ""
        if existing:
            task.output = f"{existing}\n{message}"
        else:
            task.output = message
        task.updated_at = utcnow()
        return task.save(session)


def task_meta(task: Task) -> dict[str, Any]:
    raw = (task.meta_json or "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def set_task_meta(task_id: int, meta: dict[str, Any]) -> Task | None:
    meta_json = json.dumps(meta or {}, sort_keys=True)
    return update_task(task_id, meta_json=meta_json)


def latest_task(
    kind: str | None = None,
    source_id: int | None = None,
    statuses: set[str] | None = None,
) -> Task | None:
    init_db()
    with session_scope() as session:
        stmt = select(Task)
        if kind:
            stmt = stmt.where(Task.kind == kind)
        if source_id is not None:
            stmt = stmt.where(Task.source_id == source_id)
        if statuses:
            stmt = stmt.where(Task.status.in_(list(statuses)))
        stmt = stmt.order_by(Task.created_at.desc())
        return session.execute(stmt).scalars().first()


def latest_paused_task(
    kind: str | None = None, source_id: int | None = None
) -> Task | None:
    return latest_task(
        kind=kind,
        source_id=source_id,
        statuses={TASK_STATUS_PAUSED},
    )


def latest_finished_task(kind: str | None = None) -> Task | None:
    init_db()
    with session_scope() as session:
        stmt = select(Task).where(Task.finished_at.is_not(None))
        if kind:
            stmt = stmt.where(Task.kind == kind)
        stmt = stmt.order_by(Task.finished_at.desc())
        return session.execute(stmt).scalars().first()


def active_task(kind: str | None = None, source_id: int | None = None) -> Task | None:
    init_db()
    with session_scope() as session:
        stmt = select(Task).where(Task.status.in_(TASK_ACTIVE_STATUSES))
        if kind:
            stmt = stmt.where(Task.kind == kind)
        if source_id is not None:
            stmt = stmt.where(Task.source_id == source_id)
        stmt = stmt.order_by(Task.created_at.desc())
        return session.execute(stmt).scalars().first()


def list_active_tasks(
    kind: str | None = None, source_id: int | None = None
) -> list[Task]:
    init_db()
    with session_scope() as session:
        stmt = select(Task).where(Task.status.in_(TASK_ACTIVE_STATUSES))
        if kind:
            stmt = stmt.where(Task.kind == kind)
        if source_id is not None:
            stmt = stmt.where(Task.source_id == source_id)
        stmt = stmt.order_by(Task.created_at.desc())
        return session.execute(stmt).scalars().all()


def has_active_task(kind: str | None = None, source_id: int | None = None) -> bool:
    return active_task(kind=kind, source_id=source_id) is not None


def format_dt(value: datetime | None) -> str | None:
    if not value:
        return None
    return value.isoformat()

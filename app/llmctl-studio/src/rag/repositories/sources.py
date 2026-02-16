from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re

from sqlalchemy import select

from core.config import Config
from core.db import session_scope, utcnow
from core.models import (
    RAG_INDEX_MODE_CHOICES,
    RAG_INDEX_MODE_FRESH,
    RAG_SOURCE_KIND_CHOICES,
    RAG_SOURCE_KIND_GITHUB,
    RAG_SOURCE_KIND_GOOGLE_DRIVE,
    RAG_SOURCE_KIND_LOCAL,
    RAG_SOURCE_SCHEDULE_UNIT_CHOICES,
    RAGSource,
)

SCHEDULE_UNITS = tuple(RAG_SOURCE_SCHEDULE_UNIT_CHOICES)


@dataclass(frozen=True)
class RAGSourceInput:
    name: str
    kind: str
    local_path: str | None = None
    git_repo: str | None = None
    git_branch: str | None = None
    drive_folder_id: str | None = None
    index_schedule_value: int | str | None = None
    index_schedule_unit: str | None = None
    index_schedule_mode: str | None = None


def is_valid_kind(kind: str) -> bool:
    return kind in RAG_SOURCE_KIND_CHOICES


def list_sources(limit: int | None = None) -> list[RAGSource]:
    with session_scope() as session:
        stmt = select(RAGSource).order_by(RAGSource.created_at.desc())
        if limit is not None:
            stmt = stmt.limit(limit)
        return session.execute(stmt).scalars().all()


def get_source(source_id: int) -> RAGSource | None:
    with session_scope() as session:
        return session.get(RAGSource, source_id)


def create_source(payload: RAGSourceInput) -> RAGSource:
    cleaned = _normalize_payload(payload)
    with session_scope() as session:
        source = RAGSource.create(
            session,
            name=cleaned.name,
            kind=cleaned.kind,
            local_path=cleaned.local_path,
            git_repo=cleaned.git_repo,
            git_branch=cleaned.git_branch,
            git_dir=None,
            drive_folder_id=cleaned.drive_folder_id,
            collection="pending",
            index_schedule_value=cleaned.index_schedule_value,
            index_schedule_unit=cleaned.index_schedule_unit,
            index_schedule_mode=cleaned.index_schedule_mode,
            next_index_at=_next_index_at_for_schedule(
                cleaned.index_schedule_value,
                cleaned.index_schedule_unit,
            ),
        )
        source.collection = _collection_name(cleaned.name, source.id)
        if source.kind == RAG_SOURCE_KIND_GITHUB:
            source.git_dir = str(_default_git_dir(source.id))
        elif source.kind == RAG_SOURCE_KIND_GOOGLE_DRIVE:
            source.local_path = str(_default_drive_dir(source.id))
        return source.save(session)


def update_source(source_id: int, payload: RAGSourceInput) -> RAGSource:
    cleaned = _normalize_payload(payload)
    with session_scope() as session:
        source = session.get(RAGSource, source_id)
        if not source:
            raise ValueError("Source not found.")

        source.name = cleaned.name
        source.kind = cleaned.kind
        source.local_path = cleaned.local_path
        source.git_repo = cleaned.git_repo
        source.git_branch = cleaned.git_branch
        source.drive_folder_id = cleaned.drive_folder_id

        schedule_changed = (
            source.index_schedule_value != cleaned.index_schedule_value
            or source.index_schedule_unit != cleaned.index_schedule_unit
            or source.index_schedule_mode != cleaned.index_schedule_mode
        )
        source.index_schedule_value = cleaned.index_schedule_value
        source.index_schedule_unit = cleaned.index_schedule_unit
        source.index_schedule_mode = cleaned.index_schedule_mode
        if source.index_schedule_value and source.index_schedule_unit:
            if schedule_changed or source.next_index_at is None:
                source.next_index_at = _next_index_at_for_schedule(
                    source.index_schedule_value,
                    source.index_schedule_unit,
                )
        else:
            source.next_index_at = None

        if source.kind == RAG_SOURCE_KIND_GITHUB:
            source.local_path = None
            source.drive_folder_id = None
            source.git_dir = source.git_dir or str(_default_git_dir(source.id))
        elif source.kind == RAG_SOURCE_KIND_GOOGLE_DRIVE:
            source.git_repo = None
            source.git_branch = None
            source.git_dir = None
            source.local_path = str(_default_drive_dir(source.id))
        else:
            source.git_repo = None
            source.git_branch = None
            source.git_dir = None
            source.drive_folder_id = None

        updated = source.save(session)

    from rag.repositories.source_file_states import delete_source_file_states

    delete_source_file_states(source_id)
    return updated


def delete_source(source_id: int) -> None:
    from rag.repositories.source_file_states import delete_source_file_states

    delete_source_file_states(source_id)
    with session_scope() as session:
        source = session.get(RAGSource, source_id)
        if source:
            source.delete(session)


def update_source_index(
    source_id: int,
    *,
    last_indexed_at: datetime | None,
    last_error: str | None,
    indexed_file_count: int | None = None,
    indexed_chunk_count: int | None = None,
    indexed_file_types: str | None = None,
) -> None:
    with session_scope() as session:
        source = session.get(RAGSource, source_id)
        if not source:
            return
        source.last_indexed_at = last_indexed_at
        source.last_error = last_error
        if indexed_file_count is not None:
            source.indexed_file_count = indexed_file_count
        if indexed_chunk_count is not None:
            source.indexed_chunk_count = indexed_chunk_count
        if indexed_file_types is not None:
            source.indexed_file_types = indexed_file_types
        source.updated_at = utcnow()
        source.save(session)


def list_due_sources(
    *, now: datetime | None = None, limit: int = 200
) -> list[RAGSource]:
    due_at = now or utcnow()
    if due_at.tzinfo is None:
        due_at = due_at.replace(tzinfo=timezone.utc)
    with session_scope() as session:
        stmt = (
            select(RAGSource)
            .where(RAGSource.next_index_at.is_not(None), RAGSource.next_index_at <= due_at)
            .order_by(RAGSource.next_index_at.asc(), RAGSource.id.asc())
            .limit(max(1, int(limit)))
        )
        return session.execute(stmt).scalars().all()


def schedule_source_next_index(
    source_id: int,
    *,
    from_time: datetime | None = None,
) -> datetime | None:
    with session_scope() as session:
        source = session.get(RAGSource, source_id)
        if not source:
            return None
        source.next_index_at = _next_index_at_for_schedule(
            source.index_schedule_value,
            source.index_schedule_unit,
            from_time=from_time,
        )
        source.updated_at = utcnow()
        source.save(session)
        return source.next_index_at


def clear_source_next_index(source_id: int) -> None:
    with session_scope() as session:
        source = session.get(RAGSource, source_id)
        if not source:
            return
        source.next_index_at = None
        source.updated_at = utcnow()
        source.save(session)


def _normalize_payload(payload: RAGSourceInput) -> RAGSourceInput:
    name = (payload.name or "").strip()
    kind = (payload.kind or "").strip().lower()
    local_path = (payload.local_path or "").strip() or None
    git_repo = (payload.git_repo or "").strip() or None
    git_branch = (payload.git_branch or "").strip() or None
    drive_folder_id = (payload.drive_folder_id or "").strip() or None
    index_schedule_value = _normalize_schedule_value(payload.index_schedule_value)
    index_schedule_unit = _normalize_schedule_unit(payload.index_schedule_unit)
    index_schedule_mode = _normalize_schedule_mode(payload.index_schedule_mode)

    if not name:
        raise ValueError("Source name is required.")
    if kind not in RAG_SOURCE_KIND_CHOICES:
        raise ValueError("Source kind must be local, github, or google_drive.")
    if kind == RAG_SOURCE_KIND_LOCAL and not local_path:
        raise ValueError("Local path is required for local sources.")
    if kind == RAG_SOURCE_KIND_GITHUB and not git_repo:
        raise ValueError("GitHub repo is required for GitHub sources.")
    if kind == RAG_SOURCE_KIND_GOOGLE_DRIVE and not drive_folder_id:
        raise ValueError("Google Drive folder ID is required for Google Drive sources.")
    if (index_schedule_value is None) != (index_schedule_unit is None):
        raise ValueError("Index schedule requires both interval value and unit.")

    return RAGSourceInput(
        name=name,
        kind=kind,
        local_path=local_path,
        git_repo=git_repo,
        git_branch=git_branch,
        drive_folder_id=drive_folder_id,
        index_schedule_value=index_schedule_value,
        index_schedule_unit=index_schedule_unit,
        index_schedule_mode=index_schedule_mode,
    )


def _normalize_schedule_value(value: int | str | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        parsed = value
    else:
        raw = str(value).strip()
        if not raw:
            return None
        try:
            parsed = int(raw)
        except ValueError as exc:
            raise ValueError("Index schedule interval must be a whole number.") from exc
    if parsed <= 0:
        raise ValueError("Index schedule interval must be greater than zero.")
    return parsed


def _normalize_schedule_unit(value: str | None) -> str | None:
    unit = (value or "").strip().lower()
    if not unit:
        return None
    if unit not in RAG_SOURCE_SCHEDULE_UNIT_CHOICES:
        raise ValueError(
            "Index schedule unit must be minutes, hours, days, or weeks."
        )
    return unit


def _normalize_schedule_mode(value: str | None) -> str:
    mode = (value or RAG_INDEX_MODE_FRESH).strip().lower()
    if mode not in RAG_INDEX_MODE_CHOICES:
        raise ValueError("Index schedule mode must be fresh or delta.")
    return mode


def _next_index_at_for_schedule(
    schedule_value: int | None,
    schedule_unit: str | None,
    *,
    from_time: datetime | None = None,
) -> datetime | None:
    if not schedule_value or not schedule_unit:
        return None
    base = from_time or utcnow()
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    if schedule_unit == "minutes":
        delta = timedelta(minutes=schedule_value)
    elif schedule_unit == "hours":
        delta = timedelta(hours=schedule_value)
    elif schedule_unit == "days":
        delta = timedelta(days=schedule_value)
    elif schedule_unit == "weeks":
        delta = timedelta(weeks=schedule_value)
    else:
        return None
    return base + delta


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.strip().lower())
    slug = slug.strip("_")
    return slug[:32] if slug else "source"


def _collection_name(name: str, source_id: int) -> str:
    slug = _slugify(name)
    return f"{slug}_{source_id}"


def _default_git_dir(source_id: int) -> Path:
    return _rag_sources_root() / f"source-{source_id}"


def _default_drive_dir(source_id: int) -> Path:
    return _rag_sources_root() / f"source-{source_id}-drive"


def _rag_sources_root() -> Path:
    path = Path(Config.DATA_DIR) / "rag" / "sources"
    path.mkdir(parents=True, exist_ok=True)
    return path

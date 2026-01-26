from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re

from sqlalchemy import select

from db import DATA_DIR, init_db, session_scope, utcnow
from models import Source


_KIND_LOCAL = "local"
_KIND_GITHUB = "github"
_KIND_VALUES = {_KIND_LOCAL, _KIND_GITHUB}


@dataclass(frozen=True)
class SourceInput:
    name: str
    kind: str
    local_path: str | None = None
    git_repo: str | None = None
    git_branch: str | None = None


def is_valid_kind(kind: str) -> bool:
    return kind in _KIND_VALUES


def list_sources() -> list[Source]:
    init_db()
    with session_scope() as session:
        return (
            session.execute(select(Source).order_by(Source.created_at.desc()))
            .scalars()
            .all()
        )


def get_source(source_id: int) -> Source | None:
    init_db()
    with session_scope() as session:
        return session.get(Source, source_id)


def create_source(payload: SourceInput) -> Source:
    init_db()
    cleaned = _normalize_payload(payload)
    with session_scope() as session:
        source = Source.create(
            session,
            name=cleaned.name,
            kind=cleaned.kind,
            local_path=cleaned.local_path,
            git_repo=cleaned.git_repo,
            git_branch=cleaned.git_branch,
            git_dir=None,
            collection="pending",
        )
        source.collection = _collection_name(cleaned.name, source.id)
        if source.kind == _KIND_GITHUB:
            source.git_dir = str(_default_git_dir(source.id))
        return source.save(session)


def delete_source(source_id: int) -> None:
    init_db()
    with session_scope() as session:
        source = session.get(Source, source_id)
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
    init_db()
    with session_scope() as session:
        source = session.get(Source, source_id)
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


def _normalize_payload(payload: SourceInput) -> SourceInput:
    name = (payload.name or "").strip()
    kind = (payload.kind or "").strip().lower()
    local_path = (payload.local_path or "").strip() or None
    git_repo = (payload.git_repo or "").strip() or None
    git_branch = (payload.git_branch or "").strip() or None
    if not name:
        raise ValueError("Source name is required.")
    if kind not in _KIND_VALUES:
        raise ValueError("Source kind must be local or github.")
    if kind == _KIND_LOCAL and not local_path:
        raise ValueError("Local path is required for local sources.")
    if kind == _KIND_GITHUB and not git_repo:
        raise ValueError("GitHub repo is required for GitHub sources.")
    return SourceInput(
        name=name,
        kind=kind,
        local_path=local_path,
        git_repo=git_repo,
        git_branch=git_branch or None,
    )


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.strip().lower())
    slug = slug.strip("_")
    return slug[:32] if slug else "source"


def _collection_name(name: str, source_id: int) -> str:
    slug = _slugify(name)
    return f"{slug}_{source_id}"


def _default_git_dir(source_id: int) -> Path:
    return DATA_DIR / "sources" / f"source-{source_id}"

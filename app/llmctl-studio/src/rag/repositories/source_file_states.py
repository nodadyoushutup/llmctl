from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select

from core.db import session_scope
from core.models import RAGSourceFileState


@dataclass(frozen=True)
class SourceFileStateInput:
    path: str
    fingerprint: str
    indexed: bool
    doc_type: str | None = None
    chunk_count: int = 0


@dataclass(frozen=True)
class SourceFileStats:
    indexed_file_count: int
    indexed_chunk_count: int
    indexed_file_types: dict[str, int]


def list_source_file_states(source_id: int) -> list[RAGSourceFileState]:
    with session_scope() as session:
        stmt = (
            select(RAGSourceFileState)
            .where(RAGSourceFileState.source_id == source_id)
            .order_by(RAGSourceFileState.path.asc())
        )
        return session.execute(stmt).scalars().all()


def delete_source_file_states(source_id: int, *, paths: list[str] | None = None) -> None:
    with session_scope() as session:
        if not paths:
            stmt = select(RAGSourceFileState).where(RAGSourceFileState.source_id == source_id)
            for row in session.execute(stmt).scalars().all():
                row.delete(session)
            return

        for chunk in _chunked_unique_paths(paths):
            if not chunk:
                continue
            stmt = select(RAGSourceFileState).where(
                RAGSourceFileState.source_id == source_id,
                RAGSourceFileState.path.in_(chunk),
            )
            for row in session.execute(stmt).scalars().all():
                row.delete(session)


def upsert_source_file_states(source_id: int, states: list[SourceFileStateInput]) -> None:
    if not states:
        return
    by_path: dict[str, SourceFileStateInput] = {}
    for item in states:
        path = str(item.path or "").strip()
        fingerprint = str(item.fingerprint or "").strip()
        if not path or not fingerprint:
            continue
        by_path[path] = SourceFileStateInput(
            path=path,
            fingerprint=fingerprint,
            indexed=bool(item.indexed),
            doc_type=(str(item.doc_type).strip() if item.doc_type else None),
            chunk_count=max(0, int(item.chunk_count or 0)),
        )
    if not by_path:
        return

    paths = list(by_path)
    with session_scope() as session:
        existing_by_path: dict[str, RAGSourceFileState] = {}
        for chunk in _chunked_unique_paths(paths):
            if not chunk:
                continue
            stmt = select(RAGSourceFileState).where(
                RAGSourceFileState.source_id == source_id,
                RAGSourceFileState.path.in_(chunk),
            )
            for row in session.execute(stmt).scalars().all():
                existing_by_path[row.path] = row

        for path, payload in by_path.items():
            existing = existing_by_path.get(path)
            if existing:
                existing.fingerprint = payload.fingerprint
                existing.indexed = 1 if payload.indexed else 0
                existing.doc_type = payload.doc_type if payload.indexed else None
                existing.chunk_count = payload.chunk_count if payload.indexed else 0
                existing.save(session)
                continue
            RAGSourceFileState.create(
                session,
                source_id=source_id,
                path=payload.path,
                fingerprint=payload.fingerprint,
                indexed=1 if payload.indexed else 0,
                doc_type=payload.doc_type if payload.indexed else None,
                chunk_count=payload.chunk_count if payload.indexed else 0,
            )


def summarize_source_file_states(source_id: int) -> SourceFileStats:
    with session_scope() as session:
        stmt = (
            select(
                RAGSourceFileState.doc_type,
                func.count(RAGSourceFileState.id),
                func.coalesce(func.sum(RAGSourceFileState.chunk_count), 0),
            )
            .where(
                RAGSourceFileState.source_id == source_id,
                RAGSourceFileState.indexed == 1,
            )
            .group_by(RAGSourceFileState.doc_type)
        )
        rows = session.execute(stmt).all()

    indexed_file_types: dict[str, int] = {}
    indexed_file_count = 0
    indexed_chunk_count = 0
    for doc_type, file_count, chunk_count in rows:
        parsed_file_count = int(file_count or 0)
        parsed_chunk_count = int(chunk_count or 0)
        indexed_file_count += parsed_file_count
        indexed_chunk_count += parsed_chunk_count
        label = str(doc_type or "").strip()
        if label:
            indexed_file_types[label] = indexed_file_types.get(label, 0) + parsed_file_count

    return SourceFileStats(
        indexed_file_count=indexed_file_count,
        indexed_chunk_count=indexed_chunk_count,
        indexed_file_types=indexed_file_types,
    )


def _chunked_unique_paths(paths: list[str], *, chunk_size: int = 500) -> list[list[str]]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for path in paths:
        value = str(path or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        cleaned.append(value)
    return [cleaned[index : index + chunk_size] for index in range(0, len(cleaned), chunk_size)]

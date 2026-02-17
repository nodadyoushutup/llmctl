"""Queue contracts for Stage 2 RAG worker topology planning."""

from __future__ import annotations

from rag.contracts import RAG_QUEUE_DRIVE, RAG_QUEUE_GIT, RAG_QUEUE_INDEX

RAG_QUEUE_BY_SOURCE_KIND = {
    "local": RAG_QUEUE_INDEX,
    "drive": RAG_QUEUE_DRIVE,
    "git": RAG_QUEUE_GIT,
    "github": RAG_QUEUE_GIT,
    "google_drive": RAG_QUEUE_DRIVE,
}


def queue_for_source_kind(source_kind: str) -> str:
    return RAG_QUEUE_BY_SOURCE_KIND.get((source_kind or "").strip().lower(), RAG_QUEUE_INDEX)

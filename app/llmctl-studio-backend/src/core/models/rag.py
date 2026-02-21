from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db import BaseModel, utcnow

from .constants import RAG_INDEX_MODE_FRESH

class RAGSource(BaseModel):
    __tablename__ = "rag_sources"
    __table_args__ = (
        UniqueConstraint("collection", name="uq_rag_sources_collection"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    local_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    git_repo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    git_branch: Mapped[str | None] = mapped_column(String(128), nullable=True)
    git_dir: Mapped[str | None] = mapped_column(Text, nullable=True)
    drive_folder_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    collection: Mapped[str] = mapped_column(String(128), nullable=False)
    last_indexed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    indexed_file_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    indexed_chunk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    indexed_file_types: Mapped[str | None] = mapped_column(Text, nullable=True)
    index_schedule_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    index_schedule_unit: Mapped[str | None] = mapped_column(String(16), nullable=True)
    index_schedule_mode: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=RAG_INDEX_MODE_FRESH,
        server_default=text("'fresh'"),
    )
    next_index_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    file_states: Mapped[list["RAGSourceFileState"]] = relationship(
        "RAGSourceFileState",
        back_populates="source",
        cascade="all, delete-orphan",
        order_by="RAGSourceFileState.path.asc()",
    )


class RAGSourceFileState(BaseModel):
    __tablename__ = "rag_source_file_states"
    __table_args__ = (
        UniqueConstraint("source_id", "path", name="uq_rag_source_file_source_path"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("rag_sources.id"), nullable=False, index=True
    )
    path: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(80), nullable=False)
    indexed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    doc_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    source: Mapped["RAGSource"] = relationship(
        "RAGSource", back_populates="file_states"
    )


class RAGRetrievalAudit(BaseModel):
    __tablename__ = "rag_retrieval_audits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    runtime_kind: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unknown", index=True
    )
    flowchart_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("flowchart_runs.id"), nullable=True, index=True
    )
    flowchart_node_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("flowchart_run_nodes.id"), nullable=True, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    collection: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    path: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    retrieval_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class RAGSetting(BaseModel):
    __tablename__ = "rag_settings"
    __table_args__ = (
        UniqueConstraint("provider", "key", name="uq_rag_settings_provider_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )



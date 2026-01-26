from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db import BaseModel, utcnow


class Source(BaseModel):
    __tablename__ = "sources"
    __table_args__ = (UniqueConstraint("collection", name="uq_sources_collection"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    local_path: Mapped[str | None] = mapped_column(Text)
    git_repo: Mapped[str | None] = mapped_column(String(255))
    git_branch: Mapped[str | None] = mapped_column(String(128))
    git_dir: Mapped[str | None] = mapped_column(Text)
    collection: Mapped[str] = mapped_column(String(128), nullable=False)
    last_indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    indexed_file_count: Mapped[int | None] = mapped_column(Integer)
    indexed_chunk_count: Mapped[int | None] = mapped_column(Integer)
    indexed_file_types: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class Task(BaseModel):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    source_id: Mapped[int | None] = mapped_column(Integer, index=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(255))
    output: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    meta_json: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class IntegrationSetting(BaseModel):
    __tablename__ = "integration_settings"
    __table_args__ = (
        UniqueConstraint("provider", "key", name="uq_integration_provider_key"),
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

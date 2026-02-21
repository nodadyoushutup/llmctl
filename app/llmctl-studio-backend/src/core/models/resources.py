from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db import BaseModel, utcnow

from .associations import (
    agent_task_attachments,
    agent_task_mcp_servers,
    agent_task_scripts,
    chat_thread_mcp_servers,
    flowchart_node_attachments,
    flowchart_node_mcp_servers,
    flowchart_node_scripts,
)
from .constants import (
    MCP_SERVER_TYPE_CUSTOM,
    MCP_SERVER_TYPE_INTEGRATED,
    ensure_legacy_skill_script_writable,
)

class MCPServer(BaseModel):
    __tablename__ = "mcp_servers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    server_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    config_json: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
    )
    server_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default=MCP_SERVER_TYPE_CUSTOM
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    flowchart_nodes: Mapped[list["FlowchartNode"]] = relationship(
        "FlowchartNode",
        secondary=flowchart_node_mcp_servers,
        back_populates="mcp_servers",
    )
    chat_threads: Mapped[list["ChatThread"]] = relationship(
        "ChatThread",
        secondary=chat_thread_mcp_servers,
        back_populates="mcp_servers",
    )
    tasks: Mapped[list["AgentTask"]] = relationship(
        "AgentTask",
        secondary=agent_task_mcp_servers,
        back_populates="mcp_servers",
    )

    @property
    def is_integrated(self) -> bool:
        return (self.server_type or MCP_SERVER_TYPE_CUSTOM) == MCP_SERVER_TYPE_INTEGRATED


class Script(BaseModel):
    __tablename__ = "scripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    script_type: Mapped[str] = mapped_column(String(32), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    tasks: Mapped[list["AgentTask"]] = relationship(
        "AgentTask", secondary=agent_task_scripts, back_populates="scripts"
    )
    flowchart_nodes: Mapped[list["FlowchartNode"]] = relationship(
        "FlowchartNode",
        secondary=flowchart_node_scripts,
        back_populates="scripts",
    )

    @classmethod
    def create(cls, session, **kwargs):
        ensure_legacy_skill_script_writable(kwargs.get("script_type"))
        return super().create(session, **kwargs)


class Attachment(BaseModel):
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    tasks: Mapped[list["AgentTask"]] = relationship(
        "AgentTask", secondary=agent_task_attachments, back_populates="attachments"
    )
    flowchart_nodes: Mapped[list["FlowchartNode"]] = relationship(
        "FlowchartNode",
        secondary=flowchart_node_attachments,
        back_populates="attachments",
    )


class Memory(BaseModel):
    __tablename__ = "memories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)

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



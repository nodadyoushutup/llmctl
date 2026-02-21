from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db import BaseModel, utcnow

from .associations import chat_thread_mcp_servers
from .constants import CHAT_THREAD_STATUS_ACTIVE, CHAT_TURN_STATUS_SUCCEEDED

class ChatThread(BaseModel):
    __tablename__ = "chat_threads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(
        String(255), nullable=False, default="New Chat", server_default=text("'New Chat'")
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=CHAT_THREAD_STATUS_ACTIVE,
        server_default=text("'active'"),
        index=True,
    )
    model_id: Mapped[int | None] = mapped_column(
        ForeignKey("llm_models.id"), nullable=True, index=True
    )
    response_complexity: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="medium",
        server_default=text("'medium'"),
    )
    selected_rag_collections_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    compaction_summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    model: Mapped["LLMModel | None"] = relationship("LLMModel", lazy="joined")
    mcp_servers: Mapped[list["MCPServer"]] = relationship(
        "MCPServer",
        secondary=chat_thread_mcp_servers,
        back_populates="chat_threads",
    )
    messages: Mapped[list["ChatMessage"]] = relationship(
        "ChatMessage",
        back_populates="thread",
        cascade="all, delete-orphan",
        order_by="ChatMessage.id.asc()",
    )
    turns: Mapped[list["ChatTurn"]] = relationship(
        "ChatTurn",
        back_populates="thread",
        cascade="all, delete-orphan",
        order_by="ChatTurn.id.asc()",
    )
    activity_events: Mapped[list["ChatActivityEvent"]] = relationship(
        "ChatActivityEvent",
        back_populates="thread",
        cascade="all, delete-orphan",
        order_by="ChatActivityEvent.id.asc()",
    )


class ChatMessage(BaseModel):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    thread_id: Mapped[int] = mapped_column(
        ForeignKey("chat_threads.id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_estimate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    thread: Mapped["ChatThread"] = relationship("ChatThread", back_populates="messages")


class ChatTurn(BaseModel):
    __tablename__ = "chat_turns"
    __table_args__ = (
        UniqueConstraint("thread_id", "request_id", name="uq_chat_turns_thread_request"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    thread_id: Mapped[int] = mapped_column(
        ForeignKey("chat_threads.id"), nullable=False, index=True
    )
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model_id: Mapped[int | None] = mapped_column(
        ForeignKey("llm_models.id"), nullable=True, index=True
    )
    user_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("chat_messages.id"), nullable=True, index=True
    )
    assistant_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("chat_messages.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=CHAT_TURN_STATUS_SUCCEEDED,
        server_default=text("'succeeded'"),
        index=True,
    )
    reason_code: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    selected_rag_collections_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    selected_mcp_server_keys_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    rag_health_state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    context_limit_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    context_usage_before: Mapped[int | None] = mapped_column(Integer, nullable=True)
    context_usage_after: Mapped[int | None] = mapped_column(Integer, nullable=True)
    history_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rag_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mcp_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    compaction_applied: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    compaction_metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    citation_metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    runtime_metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    thread: Mapped["ChatThread"] = relationship("ChatThread", back_populates="turns")
    model: Mapped["LLMModel | None"] = relationship("LLMModel", lazy="joined")
    user_message: Mapped["ChatMessage | None"] = relationship(
        "ChatMessage", foreign_keys=[user_message_id]
    )
    assistant_message: Mapped["ChatMessage | None"] = relationship(
        "ChatMessage", foreign_keys=[assistant_message_id]
    )
    activity_events: Mapped[list["ChatActivityEvent"]] = relationship(
        "ChatActivityEvent",
        back_populates="turn",
        cascade="all, delete-orphan",
        order_by="ChatActivityEvent.id.asc()",
    )


class ChatActivityEvent(BaseModel):
    __tablename__ = "chat_activity_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    thread_id: Mapped[int] = mapped_column(
        ForeignKey("chat_threads.id"), nullable=False, index=True
    )
    turn_id: Mapped[int | None] = mapped_column(
        ForeignKey("chat_turns.id"), nullable=True, index=True
    )
    event_class: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    reason_code: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    thread: Mapped["ChatThread"] = relationship(
        "ChatThread", back_populates="activity_events"
    )
    turn: Mapped["ChatTurn | None"] = relationship(
        "ChatTurn", back_populates="activity_events"
    )



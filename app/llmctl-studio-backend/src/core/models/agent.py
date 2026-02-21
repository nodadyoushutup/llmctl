from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db import BaseModel, utcnow

from .associations import (
    agent_skill_bindings,
    agent_task_attachments,
    agent_task_mcp_servers,
    agent_task_scripts,
)
from .constants import NODE_EXECUTOR_DISPATCH_PENDING, NODE_EXECUTOR_PROVIDER_KUBERNETES

class LLMModel(BaseModel):
    __tablename__ = "llm_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    config_json: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    tasks: Mapped[list["AgentTask"]] = relationship(
        "AgentTask", back_populates="model"
    )
    flowchart_nodes: Mapped[list["FlowchartNode"]] = relationship(
        "FlowchartNode", back_populates="model"
    )


class Agent(BaseModel):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    role_id: Mapped[int | None] = mapped_column(
        ForeignKey("roles.id"), nullable=True, index=True
    )
    prompt_json: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    autonomous_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    role: Mapped["Role | None"] = relationship(
        "Role", back_populates="agents", lazy="joined"
    )
    runs: Mapped[list["Run"]] = relationship(
        "Run",
        back_populates="agent",
    )
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_run_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    run_max_loops: Mapped[int | None] = mapped_column(Integer, nullable=True)
    run_end_requested: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    last_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    last_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_stopped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    priorities: Mapped[list["AgentPriority"]] = relationship(
        "AgentPriority",
        back_populates="agent",
        cascade="all, delete-orphan",
        order_by="AgentPriority.position.asc(), AgentPriority.id.asc()",
    )
    skills: Mapped[list["Skill"]] = relationship(
        "Skill",
        secondary=agent_skill_bindings,
        back_populates="agents",
        order_by=agent_skill_bindings.c.position.asc(),
    )


class AgentPriority(BaseModel):
    __tablename__ = "agent_priorities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    agent: Mapped["Agent"] = relationship("Agent", back_populates="priorities")


class Run(BaseModel):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="stopped", nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_run_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    run_max_loops: Mapped[int | None] = mapped_column(Integer, nullable=True)
    run_end_requested: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    last_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_stopped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    agent: Mapped["Agent"] = relationship("Agent", back_populates="runs")


class Role(BaseModel):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    details_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    agents: Mapped[list["Agent"]] = relationship("Agent", back_populates="role")


class AgentTask(BaseModel):
    __tablename__ = "agent_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("agents.id"), nullable=True, index=True
    )
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("runs.id"), nullable=True, index=True
    )
    run_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_id: Mapped[int | None] = mapped_column(
        ForeignKey("llm_models.id"), nullable=True, index=True
    )
    flowchart_id: Mapped[int | None] = mapped_column(
        ForeignKey("flowcharts.id"), nullable=True, index=True
    )
    flowchart_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("flowchart_runs.id"), nullable=True, index=True
    )
    flowchart_node_id: Mapped[int | None] = mapped_column(
        ForeignKey("flowchart_nodes.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    kind: Mapped[str | None] = mapped_column(String(32), default="task", nullable=True)
    integration_keys_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_role_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resolved_role_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resolved_agent_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resolved_agent_version: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    resolved_skill_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_skill_versions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_skill_manifest_hash: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    skill_adapter_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resolved_instruction_manifest_hash: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    instruction_adapter_mode: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    instruction_materialized_paths_json: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    selected_provider: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=NODE_EXECUTOR_PROVIDER_KUBERNETES,
        server_default=text("'kubernetes'"),
    )
    final_provider: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=NODE_EXECUTOR_PROVIDER_KUBERNETES,
        server_default=text("'kubernetes'"),
    )
    provider_dispatch_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    workspace_identity: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default="default",
        server_default=text("'default'"),
    )
    dispatch_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=NODE_EXECUTOR_DISPATCH_PENDING,
        server_default=text("'dispatch_pending'"),
    )
    fallback_attempted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    fallback_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dispatch_uncertain: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    api_failure_category: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    cli_fallback_used: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    cli_preflight_passed: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )

    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    output: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    stage_logs: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    scripts: Mapped[list["Script"]] = relationship(
        "Script",
        secondary=agent_task_scripts,
        back_populates="tasks",
        order_by=agent_task_scripts.c.position.asc(),
    )
    model: Mapped["LLMModel | None"] = relationship(
        "LLMModel", back_populates="tasks", lazy="joined"
    )
    mcp_servers: Mapped[list["MCPServer"]] = relationship(
        "MCPServer",
        secondary=agent_task_mcp_servers,
        back_populates="tasks",
    )
    attachments: Mapped[list["Attachment"]] = relationship(
        "Attachment",
        secondary=agent_task_attachments,
        back_populates="tasks",
    )

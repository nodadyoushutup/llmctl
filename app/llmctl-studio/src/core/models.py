from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db import Base, BaseModel, utcnow

agent_mcp_servers = Table(
    "agent_mcp_servers",
    Base.metadata,
    Column("agent_id", ForeignKey("agents.id"), primary_key=True),
    Column("mcp_server_id", ForeignKey("mcp_servers.id"), primary_key=True),
)

SCRIPT_TYPE_PRE_INIT = "pre_init"
SCRIPT_TYPE_INIT = "init"
SCRIPT_TYPE_POST_INIT = "post_init"
SCRIPT_TYPE_POST_RUN = "post_run"
SCRIPT_TYPE_SKILL = "skill"

SCRIPT_TYPE_CHOICES = [
    (SCRIPT_TYPE_PRE_INIT, "Pre-Init Script"),
    (SCRIPT_TYPE_INIT, "Init Script"),
    (SCRIPT_TYPE_POST_INIT, "Post-Init Script"),
    (SCRIPT_TYPE_POST_RUN, "Post-Run Script"),
    (SCRIPT_TYPE_SKILL, "Skill Script"),
]

SCRIPT_TYPE_LABELS = dict(SCRIPT_TYPE_CHOICES)

RUN_ACTIVE_STATUSES = ("starting", "running", "stopping")

agent_scripts = Table(
    "agent_scripts",
    Base.metadata,
    Column("agent_id", ForeignKey("agents.id"), primary_key=True),
    Column("script_id", ForeignKey("scripts.id"), primary_key=True),
    Column("position", Integer, nullable=True),
)

agent_task_scripts = Table(
    "agent_task_scripts",
    Base.metadata,
    Column("agent_task_id", ForeignKey("agent_tasks.id"), primary_key=True),
    Column("script_id", ForeignKey("scripts.id"), primary_key=True),
    Column("position", Integer, nullable=True),
)

agent_task_attachments = Table(
    "agent_task_attachments",
    Base.metadata,
    Column("agent_task_id", ForeignKey("agent_tasks.id"), primary_key=True),
    Column("attachment_id", ForeignKey("attachments.id"), primary_key=True),
)

task_template_attachments = Table(
    "task_template_attachments",
    Base.metadata,
    Column("task_template_id", ForeignKey("task_templates.id"), primary_key=True),
    Column("attachment_id", ForeignKey("attachments.id"), primary_key=True),
)

pipeline_step_attachments = Table(
    "pipeline_step_attachments",
    Base.metadata,
    Column("pipeline_step_id", ForeignKey("pipeline_steps.id"), primary_key=True),
    Column("attachment_id", ForeignKey("attachments.id"), primary_key=True),
)


class MCPServer(BaseModel):
    __tablename__ = "mcp_servers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    server_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    config_json: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    agents: Mapped[list["Agent"]] = relationship(
        "Agent", secondary=agent_mcp_servers, back_populates="mcp_servers"
    )


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

    agents: Mapped[list["Agent"]] = relationship(
        "Agent", secondary=agent_scripts, back_populates="scripts"
    )
    tasks: Mapped[list["AgentTask"]] = relationship(
        "AgentTask", secondary=agent_task_scripts, back_populates="scripts"
    )


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
    templates: Mapped[list["TaskTemplate"]] = relationship(
        "TaskTemplate",
        secondary=task_template_attachments,
        back_populates="attachments",
    )
    pipeline_steps: Mapped[list["PipelineStep"]] = relationship(
        "PipelineStep",
        secondary=pipeline_step_attachments,
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
    mcp_servers: Mapped[list["MCPServer"]] = relationship(
        "MCPServer", secondary=agent_mcp_servers, back_populates="agents"
    )
    scripts: Mapped[list["Script"]] = relationship(
        "Script",
        secondary=agent_scripts,
        back_populates="agents",
        order_by=agent_scripts.c.position.asc(),
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
    pipeline_id: Mapped[int | None] = mapped_column(
        ForeignKey("pipelines.id"), nullable=True, index=True
    )
    pipeline_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("pipeline_runs.id"), nullable=True, index=True
    )
    pipeline_step_id: Mapped[int | None] = mapped_column(
        ForeignKey("pipeline_steps.id"), nullable=True, index=True
    )
    task_template_id: Mapped[int | None] = mapped_column(
        ForeignKey("task_templates.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    kind: Mapped[str | None] = mapped_column(String(32), default="task", nullable=True)

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
    attachments: Mapped[list["Attachment"]] = relationship(
        "Attachment",
        secondary=agent_task_attachments,
        back_populates="tasks",
    )


class TaskTemplate(BaseModel):
    __tablename__ = "task_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("agents.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    attachments: Mapped[list["Attachment"]] = relationship(
        "Attachment",
        secondary=task_template_attachments,
        back_populates="templates",
    )


class Pipeline(BaseModel):
    __tablename__ = "pipelines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    loop_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class PipelineStep(BaseModel):
    __tablename__ = "pipeline_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pipeline_id: Mapped[int] = mapped_column(
        ForeignKey("pipelines.id"), nullable=False, index=True
    )
    task_template_id: Mapped[int] = mapped_column(
        ForeignKey("task_templates.id"), nullable=False, index=True
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    additional_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    attachments: Mapped[list["Attachment"]] = relationship(
        "Attachment",
        secondary=pipeline_step_attachments,
        back_populates="pipeline_steps",
    )


class PipelineRun(BaseModel):
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pipeline_id: Mapped[int] = mapped_column(
        ForeignKey("pipelines.id"), nullable=False, index=True
    )
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Milestone(BaseModel):
    __tablename__ = "milestones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    due_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

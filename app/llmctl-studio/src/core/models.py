from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db import Base, BaseModel, utcnow

SCRIPT_TYPE_PRE_INIT = "pre_init"
SCRIPT_TYPE_INIT = "init"
SCRIPT_TYPE_POST_INIT = "post_init"
SCRIPT_TYPE_POST_RUN = "post_run"
_LEGACY_SKILL_SCRIPT_TYPE = "skill"
LEGACY_SKILL_SCRIPT_WRITE_ERROR = (
    "Legacy script_type=skill writes are disabled. Use first-class Skills instead."
)

SCRIPT_TYPE_CHOICES = [
    (SCRIPT_TYPE_PRE_INIT, "Pre-Init Script"),
    (SCRIPT_TYPE_INIT, "Init Script"),
    (SCRIPT_TYPE_POST_INIT, "Post-Init Script"),
    (SCRIPT_TYPE_POST_RUN, "Post-Autorun Script"),
]

SCRIPT_TYPE_LABELS = dict(SCRIPT_TYPE_CHOICES)


def is_legacy_skill_script_type(value: str | None) -> bool:
    return str(value or "").strip().lower() == _LEGACY_SKILL_SCRIPT_TYPE


def ensure_legacy_skill_script_writable(value: str | None) -> None:
    if is_legacy_skill_script_type(value):
        raise ValueError(LEGACY_SKILL_SCRIPT_WRITE_ERROR)

RUN_ACTIVE_STATUSES = ("starting", "running", "stopping")
NODE_EXECUTOR_PROVIDER_WORKSPACE = "workspace"
NODE_EXECUTOR_PROVIDER_DOCKER = "docker"
NODE_EXECUTOR_PROVIDER_KUBERNETES = "kubernetes"
NODE_EXECUTOR_PROVIDER_CHOICES = (
    NODE_EXECUTOR_PROVIDER_WORKSPACE,
    NODE_EXECUTOR_PROVIDER_DOCKER,
    NODE_EXECUTOR_PROVIDER_KUBERNETES,
)
NODE_EXECUTOR_DISPATCH_PENDING = "dispatch_pending"
NODE_EXECUTOR_DISPATCH_SUBMITTED = "dispatch_submitted"
NODE_EXECUTOR_DISPATCH_CONFIRMED = "dispatch_confirmed"
NODE_EXECUTOR_DISPATCH_FAILED = "dispatch_failed"
NODE_EXECUTOR_DISPATCH_FALLBACK_STARTED = "fallback_started"
NODE_EXECUTOR_DISPATCH_STATUS_CHOICES = (
    NODE_EXECUTOR_DISPATCH_PENDING,
    NODE_EXECUTOR_DISPATCH_SUBMITTED,
    NODE_EXECUTOR_DISPATCH_CONFIRMED,
    NODE_EXECUTOR_DISPATCH_FAILED,
    NODE_EXECUTOR_DISPATCH_FALLBACK_STARTED,
)
NODE_EXECUTOR_FALLBACK_REASON_CHOICES = (
    "provider_unavailable",
    "preflight_failed",
    "dispatch_timeout",
    "create_failed",
    "image_pull_failed",
    "config_error",
    "unknown",
)
NODE_EXECUTOR_API_FAILURE_CATEGORY_CHOICES = (
    "socket_missing",
    "socket_unreachable",
    "api_unreachable",
    "auth_error",
    "tls_error",
    "timeout",
    "preflight_failed",
    "unknown",
)

SKILL_STATUS_DRAFT = "draft"
SKILL_STATUS_ACTIVE = "active"
SKILL_STATUS_ARCHIVED = "archived"
SKILL_STATUS_CHOICES = (
    SKILL_STATUS_DRAFT,
    SKILL_STATUS_ACTIVE,
    SKILL_STATUS_ARCHIVED,
)

FLOWCHART_NODE_TYPE_START = "start"
FLOWCHART_NODE_TYPE_END = "end"
FLOWCHART_NODE_TYPE_FLOWCHART = "flowchart"
FLOWCHART_NODE_TYPE_TASK = "task"
FLOWCHART_NODE_TYPE_PLAN = "plan"
FLOWCHART_NODE_TYPE_MILESTONE = "milestone"
FLOWCHART_NODE_TYPE_MEMORY = "memory"
FLOWCHART_NODE_TYPE_DECISION = "decision"
FLOWCHART_NODE_TYPE_RAG = "rag"
FLOWCHART_NODE_TYPE_CHOICES = (
    FLOWCHART_NODE_TYPE_START,
    FLOWCHART_NODE_TYPE_END,
    FLOWCHART_NODE_TYPE_FLOWCHART,
    FLOWCHART_NODE_TYPE_TASK,
    FLOWCHART_NODE_TYPE_PLAN,
    FLOWCHART_NODE_TYPE_MILESTONE,
    FLOWCHART_NODE_TYPE_MEMORY,
    FLOWCHART_NODE_TYPE_DECISION,
    FLOWCHART_NODE_TYPE_RAG,
)
FLOWCHART_EDGE_MODE_SOLID = "solid"
FLOWCHART_EDGE_MODE_DOTTED = "dotted"
FLOWCHART_EDGE_MODE_CHOICES = (
    FLOWCHART_EDGE_MODE_SOLID,
    FLOWCHART_EDGE_MODE_DOTTED,
)

MCP_SERVER_TYPE_CUSTOM = "custom"
MCP_SERVER_TYPE_INTEGRATED = "integrated"
MCP_SERVER_TYPE_CHOICES = (
    MCP_SERVER_TYPE_CUSTOM,
    MCP_SERVER_TYPE_INTEGRATED,
)
INTEGRATED_MCP_SERVER_KEYS = frozenset(
    {
        "llmctl-mcp",
        "github",
        "atlassian",
        "chroma",
        "google-cloud",
        "google-workspace",
    }
)
LEGACY_INTEGRATED_MCP_SERVER_KEYS = frozenset({"jira"})
SYSTEM_MANAGED_MCP_SERVER_KEYS = frozenset(
    set(INTEGRATED_MCP_SERVER_KEYS) | set(LEGACY_INTEGRATED_MCP_SERVER_KEYS)
)

MILESTONE_STATUS_PLANNED = "planned"
MILESTONE_STATUS_IN_PROGRESS = "in_progress"
MILESTONE_STATUS_AT_RISK = "at_risk"
MILESTONE_STATUS_DONE = "done"
MILESTONE_STATUS_ARCHIVED = "archived"
MILESTONE_STATUS_CHOICES = (
    MILESTONE_STATUS_PLANNED,
    MILESTONE_STATUS_IN_PROGRESS,
    MILESTONE_STATUS_AT_RISK,
    MILESTONE_STATUS_DONE,
    MILESTONE_STATUS_ARCHIVED,
)

MILESTONE_PRIORITY_LOW = "low"
MILESTONE_PRIORITY_MEDIUM = "medium"
MILESTONE_PRIORITY_HIGH = "high"
MILESTONE_PRIORITY_CHOICES = (
    MILESTONE_PRIORITY_LOW,
    MILESTONE_PRIORITY_MEDIUM,
    MILESTONE_PRIORITY_HIGH,
)

MILESTONE_HEALTH_GREEN = "green"
MILESTONE_HEALTH_YELLOW = "yellow"
MILESTONE_HEALTH_RED = "red"
MILESTONE_HEALTH_CHOICES = (
    MILESTONE_HEALTH_GREEN,
    MILESTONE_HEALTH_YELLOW,
    MILESTONE_HEALTH_RED,
)

RAG_SOURCE_KIND_LOCAL = "local"
RAG_SOURCE_KIND_GITHUB = "github"
RAG_SOURCE_KIND_GOOGLE_DRIVE = "google_drive"
RAG_SOURCE_KIND_CHOICES = (
    RAG_SOURCE_KIND_LOCAL,
    RAG_SOURCE_KIND_GITHUB,
    RAG_SOURCE_KIND_GOOGLE_DRIVE,
)

RAG_SOURCE_SCHEDULE_UNIT_MINUTES = "minutes"
RAG_SOURCE_SCHEDULE_UNIT_HOURS = "hours"
RAG_SOURCE_SCHEDULE_UNIT_DAYS = "days"
RAG_SOURCE_SCHEDULE_UNIT_WEEKS = "weeks"
RAG_SOURCE_SCHEDULE_UNIT_CHOICES = (
    RAG_SOURCE_SCHEDULE_UNIT_MINUTES,
    RAG_SOURCE_SCHEDULE_UNIT_HOURS,
    RAG_SOURCE_SCHEDULE_UNIT_DAYS,
    RAG_SOURCE_SCHEDULE_UNIT_WEEKS,
)

RAG_INDEX_MODE_FRESH = "fresh"
RAG_INDEX_MODE_DELTA = "delta"
RAG_INDEX_MODE_CHOICES = (
    RAG_INDEX_MODE_FRESH,
    RAG_INDEX_MODE_DELTA,
)

RAG_INDEX_TRIGGER_MANUAL = "manual"
RAG_INDEX_TRIGGER_SCHEDULED = "scheduled"
RAG_INDEX_TRIGGER_CHOICES = (
    RAG_INDEX_TRIGGER_MANUAL,
    RAG_INDEX_TRIGGER_SCHEDULED,
)

RAG_INDEX_JOB_KIND_INDEX = "index"
RAG_INDEX_JOB_STATUS_QUEUED = "queued"
RAG_INDEX_JOB_STATUS_RUNNING = "running"
RAG_INDEX_JOB_STATUS_PAUSING = "pausing"
RAG_INDEX_JOB_STATUS_PAUSED = "paused"
RAG_INDEX_JOB_STATUS_SUCCEEDED = "succeeded"
RAG_INDEX_JOB_STATUS_FAILED = "failed"
RAG_INDEX_JOB_STATUS_CANCELLED = "cancelled"
RAG_INDEX_JOB_STATUS_CHOICES = (
    RAG_INDEX_JOB_STATUS_QUEUED,
    RAG_INDEX_JOB_STATUS_RUNNING,
    RAG_INDEX_JOB_STATUS_PAUSING,
    RAG_INDEX_JOB_STATUS_PAUSED,
    RAG_INDEX_JOB_STATUS_SUCCEEDED,
    RAG_INDEX_JOB_STATUS_FAILED,
    RAG_INDEX_JOB_STATUS_CANCELLED,
)
RAG_INDEX_JOB_ACTIVE_STATUSES = (
    RAG_INDEX_JOB_STATUS_QUEUED,
    RAG_INDEX_JOB_STATUS_RUNNING,
    RAG_INDEX_JOB_STATUS_PAUSING,
)

CHAT_THREAD_STATUS_ACTIVE = "active"
CHAT_THREAD_STATUS_ARCHIVED = "archived"
CHAT_THREAD_STATUS_CHOICES = (
    CHAT_THREAD_STATUS_ACTIVE,
    CHAT_THREAD_STATUS_ARCHIVED,
)

CHAT_TURN_STATUS_SUCCEEDED = "succeeded"
CHAT_TURN_STATUS_FAILED = "failed"
CHAT_TURN_STATUS_CHOICES = (
    CHAT_TURN_STATUS_SUCCEEDED,
    CHAT_TURN_STATUS_FAILED,
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

task_template_mcp_servers = Table(
    "task_template_mcp_servers",
    Base.metadata,
    Column("task_template_id", ForeignKey("task_templates.id"), primary_key=True),
    Column("mcp_server_id", ForeignKey("mcp_servers.id"), primary_key=True),
)

agent_task_mcp_servers = Table(
    "agent_task_mcp_servers",
    Base.metadata,
    Column("agent_task_id", ForeignKey("agent_tasks.id"), primary_key=True),
    Column("mcp_server_id", ForeignKey("mcp_servers.id"), primary_key=True),
)

task_template_scripts = Table(
    "task_template_scripts",
    Base.metadata,
    Column("task_template_id", ForeignKey("task_templates.id"), primary_key=True),
    Column("script_id", ForeignKey("scripts.id"), primary_key=True),
    Column("position", Integer, nullable=True),
)

flowchart_node_mcp_servers = Table(
    "flowchart_node_mcp_servers",
    Base.metadata,
    Column("flowchart_node_id", ForeignKey("flowchart_nodes.id"), primary_key=True),
    Column("mcp_server_id", ForeignKey("mcp_servers.id"), primary_key=True),
)

flowchart_node_scripts = Table(
    "flowchart_node_scripts",
    Base.metadata,
    Column("flowchart_node_id", ForeignKey("flowchart_nodes.id"), primary_key=True),
    Column("script_id", ForeignKey("scripts.id"), primary_key=True),
    Column("position", Integer, nullable=True),
)

flowchart_node_skills = Table(
    "flowchart_node_skills",
    Base.metadata,
    Column("flowchart_node_id", ForeignKey("flowchart_nodes.id"), primary_key=True),
    Column("skill_id", ForeignKey("skills.id"), primary_key=True),
    Column("position", Integer, nullable=True),
)

flowchart_node_attachments = Table(
    "flowchart_node_attachments",
    Base.metadata,
    Column("flowchart_node_id", ForeignKey("flowchart_nodes.id"), primary_key=True),
    Column("attachment_id", ForeignKey("attachments.id"), primary_key=True),
)

agent_skill_bindings = Table(
    "agent_skill_bindings",
    Base.metadata,
    Column("agent_id", ForeignKey("agents.id"), primary_key=True),
    Column("skill_id", ForeignKey("skills.id"), primary_key=True),
    Column("position", Integer, nullable=False, default=1),
)

chat_thread_mcp_servers = Table(
    "chat_thread_mcp_servers",
    Base.metadata,
    Column("chat_thread_id", ForeignKey("chat_threads.id"), primary_key=True),
    Column("mcp_server_id", ForeignKey("mcp_servers.id"), primary_key=True),
)


class Skill(BaseModel):
    __tablename__ = "skills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=SKILL_STATUS_DRAFT, index=True
    )
    source_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    versions: Mapped[list["SkillVersion"]] = relationship(
        "SkillVersion",
        back_populates="skill",
        cascade="all, delete-orphan",
        order_by="SkillVersion.id.asc()",
    )
    flowchart_nodes: Mapped[list["FlowchartNode"]] = relationship(
        "FlowchartNode",
        secondary=flowchart_node_skills,
        back_populates="skills",
        order_by=flowchart_node_skills.c.position.asc(),
    )
    agents: Mapped[list["Agent"]] = relationship(
        "Agent",
        secondary=agent_skill_bindings,
        back_populates="skills",
        order_by=agent_skill_bindings.c.position.asc(),
    )


class SkillVersion(BaseModel):
    __tablename__ = "skill_versions"
    __table_args__ = (
        UniqueConstraint("skill_id", "version", name="uq_skill_versions_skill_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    skill_id: Mapped[int] = mapped_column(
        ForeignKey("skills.id"), nullable=False, index=True
    )
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    manifest_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    skill: Mapped["Skill"] = relationship("Skill", back_populates="versions")
    files: Mapped[list["SkillFile"]] = relationship(
        "SkillFile",
        back_populates="skill_version",
        cascade="all, delete-orphan",
        order_by="SkillFile.path.asc()",
    )


class SkillFile(BaseModel):
    __tablename__ = "skill_files"
    __table_args__ = (
        UniqueConstraint("skill_version_id", "path", name="uq_skill_files_version_path"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    skill_version_id: Mapped[int] = mapped_column(
        ForeignKey("skill_versions.id"), nullable=False, index=True
    )
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    skill_version: Mapped["SkillVersion"] = relationship(
        "SkillVersion", back_populates="files"
    )


class MCPServer(BaseModel):
    __tablename__ = "mcp_servers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    server_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    config_json: Mapped[str] = mapped_column(Text, nullable=False)
    server_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default=MCP_SERVER_TYPE_CUSTOM
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    task_templates: Mapped[list["TaskTemplate"]] = relationship(
        "TaskTemplate",
        secondary=task_template_mcp_servers,
        back_populates="mcp_servers",
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
    task_templates: Mapped[list["TaskTemplate"]] = relationship(
        "TaskTemplate",
        secondary=task_template_scripts,
        back_populates="scripts",
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
    templates: Mapped[list["TaskTemplate"]] = relationship(
        "TaskTemplate",
        secondary=task_template_attachments,
        back_populates="attachments",
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

    task_templates: Mapped[list["TaskTemplate"]] = relationship(
        "TaskTemplate", back_populates="model"
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
    task_template_id: Mapped[int | None] = mapped_column(
        ForeignKey("task_templates.id"), nullable=True, index=True
    )
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
        default=NODE_EXECUTOR_PROVIDER_WORKSPACE,
        server_default=text("'workspace'"),
    )
    final_provider: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=NODE_EXECUTOR_PROVIDER_WORKSPACE,
        server_default=text("'workspace'"),
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
        server_default=text("0"),
    )
    fallback_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dispatch_uncertain: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("0"),
    )
    api_failure_category: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    cli_fallback_used: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("0"),
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


class TaskTemplate(BaseModel):
    __tablename__ = "task_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("agents.id"), nullable=True, index=True
    )
    model_id: Mapped[int | None] = mapped_column(
        ForeignKey("llm_models.id"), nullable=True, index=True
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
    model: Mapped["LLMModel | None"] = relationship(
        "LLMModel", back_populates="task_templates", lazy="joined"
    )
    mcp_servers: Mapped[list["MCPServer"]] = relationship(
        "MCPServer",
        secondary=task_template_mcp_servers,
        back_populates="task_templates",
    )
    scripts: Mapped[list["Script"]] = relationship(
        "Script",
        secondary=task_template_scripts,
        back_populates="task_templates",
        order_by=task_template_scripts.c.position.asc(),
    )


class Flowchart(BaseModel):
    __tablename__ = "flowcharts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    max_node_executions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_runtime_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_parallel_nodes: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    nodes: Mapped[list["FlowchartNode"]] = relationship(
        "FlowchartNode",
        back_populates="flowchart",
        cascade="all, delete-orphan",
        order_by="FlowchartNode.id.asc()",
    )
    edges: Mapped[list["FlowchartEdge"]] = relationship(
        "FlowchartEdge",
        back_populates="flowchart",
        cascade="all, delete-orphan",
        order_by="FlowchartEdge.id.asc()",
    )
    runs: Mapped[list["FlowchartRun"]] = relationship(
        "FlowchartRun",
        back_populates="flowchart",
        cascade="all, delete-orphan",
        order_by="FlowchartRun.created_at.desc()",
    )


class FlowchartNode(BaseModel):
    __tablename__ = "flowchart_nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    flowchart_id: Mapped[int] = mapped_column(
        ForeignKey("flowcharts.id"), nullable=False, index=True
    )
    node_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    ref_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    x: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    y: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    config_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_id: Mapped[int | None] = mapped_column(
        ForeignKey("llm_models.id"), nullable=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    flowchart: Mapped["Flowchart"] = relationship("Flowchart", back_populates="nodes")
    model: Mapped["LLMModel | None"] = relationship(
        "LLMModel", back_populates="flowchart_nodes", lazy="joined"
    )
    mcp_servers: Mapped[list["MCPServer"]] = relationship(
        "MCPServer",
        secondary=flowchart_node_mcp_servers,
        back_populates="flowchart_nodes",
    )
    scripts: Mapped[list["Script"]] = relationship(
        "Script",
        secondary=flowchart_node_scripts,
        back_populates="flowchart_nodes",
        order_by=flowchart_node_scripts.c.position.asc(),
    )
    skills: Mapped[list["Skill"]] = relationship(
        "Skill",
        secondary=flowchart_node_skills,
        back_populates="flowchart_nodes",
        order_by=flowchart_node_skills.c.position.asc(),
    )
    attachments: Mapped[list["Attachment"]] = relationship(
        "Attachment",
        secondary=flowchart_node_attachments,
        back_populates="flowchart_nodes",
    )
    outgoing_edges: Mapped[list["FlowchartEdge"]] = relationship(
        "FlowchartEdge",
        back_populates="source_node",
        foreign_keys="FlowchartEdge.source_node_id",
    )
    incoming_edges: Mapped[list["FlowchartEdge"]] = relationship(
        "FlowchartEdge",
        back_populates="target_node",
        foreign_keys="FlowchartEdge.target_node_id",
    )
    node_runs: Mapped[list["FlowchartRunNode"]] = relationship(
        "FlowchartRunNode",
        back_populates="flowchart_node",
        cascade="all, delete-orphan",
        order_by="FlowchartRunNode.id.asc()",
    )


class FlowchartEdge(BaseModel):
    __tablename__ = "flowchart_edges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    flowchart_id: Mapped[int] = mapped_column(
        ForeignKey("flowcharts.id"), nullable=False, index=True
    )
    source_node_id: Mapped[int] = mapped_column(
        ForeignKey("flowchart_nodes.id"), nullable=False, index=True
    )
    target_node_id: Mapped[int] = mapped_column(
        ForeignKey("flowchart_nodes.id"), nullable=False, index=True
    )
    source_handle_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_handle_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    edge_mode: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=FLOWCHART_EDGE_MODE_SOLID,
        server_default=text("'solid'"),
    )
    condition_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    flowchart: Mapped["Flowchart"] = relationship("Flowchart", back_populates="edges")
    source_node: Mapped["FlowchartNode"] = relationship(
        "FlowchartNode",
        back_populates="outgoing_edges",
        foreign_keys=[source_node_id],
    )
    target_node: Mapped["FlowchartNode"] = relationship(
        "FlowchartNode",
        back_populates="incoming_edges",
        foreign_keys=[target_node_id],
    )


class FlowchartRun(BaseModel):
    __tablename__ = "flowchart_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    flowchart_id: Mapped[int] = mapped_column(
        ForeignKey("flowcharts.id"), nullable=False, index=True
    )
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
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
    flowchart: Mapped["Flowchart"] = relationship("Flowchart", back_populates="runs")
    node_runs: Mapped[list["FlowchartRunNode"]] = relationship(
        "FlowchartRunNode",
        back_populates="flowchart_run",
        cascade="all, delete-orphan",
        order_by="FlowchartRunNode.id.asc()",
    )


class FlowchartRunNode(BaseModel):
    __tablename__ = "flowchart_run_nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    flowchart_run_id: Mapped[int] = mapped_column(
        ForeignKey("flowchart_runs.id"), nullable=False, index=True
    )
    flowchart_node_id: Mapped[int] = mapped_column(
        ForeignKey("flowchart_nodes.id"), nullable=False, index=True
    )
    execution_index: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    agent_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_tasks.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    input_context_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_state_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    routing_state_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_skill_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_skill_versions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_skill_manifest_hash: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    skill_adapter_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resolved_role_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resolved_role_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resolved_agent_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resolved_agent_version: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    resolved_instruction_manifest_hash: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    instruction_adapter_mode: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    instruction_materialized_paths_json: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
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

    flowchart_run: Mapped["FlowchartRun"] = relationship(
        "FlowchartRun", back_populates="node_runs"
    )
    flowchart_node: Mapped["FlowchartNode"] = relationship(
        "FlowchartNode", back_populates="node_runs"
    )


class Plan(BaseModel):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    stages: Mapped[list["PlanStage"]] = relationship(
        "PlanStage",
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="PlanStage.position.asc(), PlanStage.id.asc()",
    )


class PlanStage(BaseModel):
    __tablename__ = "plan_stages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("plans.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    plan: Mapped["Plan"] = relationship("Plan", back_populates="stages")
    tasks: Mapped[list["PlanTask"]] = relationship(
        "PlanTask",
        back_populates="stage",
        cascade="all, delete-orphan",
        order_by="PlanTask.position.asc(), PlanTask.id.asc()",
    )


class PlanTask(BaseModel):
    __tablename__ = "plan_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_stage_id: Mapped[int] = mapped_column(
        ForeignKey("plan_stages.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    stage: Mapped["PlanStage"] = relationship("PlanStage", back_populates="tasks")


class Milestone(BaseModel):
    __tablename__ = "milestones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), default=MILESTONE_STATUS_PLANNED, nullable=False
    )
    priority: Mapped[str] = mapped_column(
        String(16), default=MILESTONE_PRIORITY_MEDIUM, nullable=False
    )
    owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    start_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    due_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    progress_percent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    health: Mapped[str] = mapped_column(
        String(16), default=MILESTONE_HEALTH_GREEN, nullable=False
    )
    success_criteria: Mapped[str | None] = mapped_column(Text, nullable=True)
    dependencies: Mapped[str | None] = mapped_column(Text, nullable=True)
    links: Mapped[str | None] = mapped_column(Text, nullable=True)
    latest_update: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


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
        Boolean, nullable=False, default=False, server_default=text("0")
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


# Canonical workflow naming going forward.
# Keep legacy class aliases for compatibility while remaining codepaths migrate.
Task = TaskTemplate
NodeRun = AgentTask

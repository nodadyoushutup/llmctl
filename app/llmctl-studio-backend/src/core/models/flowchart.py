from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db import BaseModel, utcnow

from .associations import (
    flowchart_node_attachments,
    flowchart_node_mcp_servers,
    flowchart_node_scripts,
    flowchart_node_skills,
)
from .constants import FLOWCHART_EDGE_MODE_SOLID, NODE_ARTIFACT_RETENTION_TTL

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
    artifacts: Mapped[list["NodeArtifact"]] = relationship(
        "NodeArtifact",
        back_populates="flowchart",
        cascade="all, delete-orphan",
        order_by="NodeArtifact.id.asc()",
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
    artifacts: Mapped[list["NodeArtifact"]] = relationship(
        "NodeArtifact",
        back_populates="flowchart_node",
        cascade="all, delete-orphan",
        order_by="NodeArtifact.id.asc()",
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
    control_points_json: Mapped[str | None] = mapped_column(Text, nullable=True)

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
    artifacts: Mapped[list["NodeArtifact"]] = relationship(
        "NodeArtifact",
        back_populates="flowchart_run",
        cascade="all, delete-orphan",
        order_by="NodeArtifact.id.asc()",
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
    output_contract_version: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="v1",
        server_default=text("'v1'"),
    )
    routing_contract_version: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="v1",
        server_default=text("'v1'"),
    )
    degraded_status: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    degraded_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        unique=True,
        index=True,
    )
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
    artifacts: Mapped[list["NodeArtifact"]] = relationship(
        "NodeArtifact",
        back_populates="flowchart_run_node",
        cascade="all, delete-orphan",
        order_by="NodeArtifact.id.asc()",
    )


class NodeArtifact(BaseModel):
    __tablename__ = "node_artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    flowchart_id: Mapped[int] = mapped_column(
        ForeignKey("flowcharts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    flowchart_node_id: Mapped[int] = mapped_column(
        ForeignKey("flowchart_nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    flowchart_run_id: Mapped[int] = mapped_column(
        ForeignKey("flowchart_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    flowchart_run_node_id: Mapped[int | None] = mapped_column(
        ForeignKey("flowchart_run_nodes.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    node_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    ref_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    execution_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    variant_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    retention_mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=NODE_ARTIFACT_RETENTION_TTL,
        server_default=text("'ttl'"),
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    correlation_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    contract_version: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="v1",
        server_default=text("'v1'"),
    )
    payload_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    idempotency_key: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        unique=True,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    flowchart: Mapped["Flowchart"] = relationship("Flowchart", back_populates="artifacts")
    flowchart_node: Mapped["FlowchartNode"] = relationship(
        "FlowchartNode", back_populates="artifacts"
    )
    flowchart_run: Mapped["FlowchartRun"] = relationship(
        "FlowchartRun", back_populates="artifacts"
    )
    flowchart_run_node: Mapped["FlowchartRunNode | None"] = relationship(
        "FlowchartRunNode", back_populates="artifacts"
    )


class RuntimeIdempotencyKey(BaseModel):
    __tablename__ = "runtime_idempotency_keys"
    __table_args__ = (
        UniqueConstraint("scope", "idempotency_key", name="uq_runtime_idempotency_scope_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    hit_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )



from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db import BaseModel, utcnow

from .associations import agent_skill_bindings, flowchart_node_skills
from .constants import SKILL_STATUS_DRAFT

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



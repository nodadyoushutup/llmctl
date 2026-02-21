from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db import BaseModel, utcnow

from .constants import (
    MILESTONE_HEALTH_GREEN,
    MILESTONE_PRIORITY_MEDIUM,
    MILESTONE_STATUS_PLANNED,
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



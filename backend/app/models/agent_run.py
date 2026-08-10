from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin


class AgentRun(TimestampMixin, Base):
    """一次可追踪、可确认和可重试的智能任务。"""

    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    agent_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), default="queued", nullable=False, index=True)
    course_id: Mapped[int | None] = mapped_column(
        ForeignKey("courses.id", ondelete="SET NULL"), index=True
    )
    chapter_id: Mapped[int | None] = mapped_column(
        ForeignKey("chapters.id", ondelete="SET NULL"), index=True
    )
    teaching_class_id: Mapped[int | None] = mapped_column(
        ForeignKey("teaching_classes.id", ondelete="SET NULL"), index=True
    )
    current_step: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    input_data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    evidence_snapshot: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    # 备课任务会保存完整章节上下文，MySQL 普通 TEXT 容量不足。
    context_snapshot: Mapped[str | None] = mapped_column(
        Text().with_variant(LONGTEXT(), "mysql")
    )
    output_data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(120))
    prompt_version: Mapped[str] = mapped_column(String(40), default="lesson-prep-v1", nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    retry_of_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), index=True
    )
    started_time: Mapped[datetime | None] = mapped_column(DateTime)
    finished_time: Mapped[datetime | None] = mapped_column(DateTime)


class AgentStep(TimestampMixin, Base):
    """AgentRun 中一个可观察的执行步骤。"""

    __tablename__ = "agent_steps"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True
    )
    step_key: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False, index=True)
    input_data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    output_data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_time: Mapped[datetime | None] = mapped_column(DateTime)
    finished_time: Mapped[datetime | None] = mapped_column(DateTime)

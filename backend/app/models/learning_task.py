from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LearningTaskPoint(Base):
    __tablename__ = "learning_task_points"
    __table_args__ = (UniqueConstraint("chapter_id", "learning_stage", "task_type", name="uq_chapter_stage_task"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), index=True)
    learning_stage: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    task_type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    weight: Mapped[int] = mapped_column(Integer, default=25, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_rule: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class UserTaskProgress(Base):
    __tablename__ = "user_task_progress"
    __table_args__ = (UniqueConstraint("user_id", "task_point_id", name="uq_user_task_point"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    task_point_id: Mapped[int] = mapped_column(ForeignKey("learning_task_points.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="not_started", nullable=False)
    progress_value: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    evidence_summary: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    completed_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class LearningEvent(Base):
    __tablename__ = "learning_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), index=True)
    learning_stage: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    event_data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

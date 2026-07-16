from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TeacherAssignment(Base):
    __tablename__ = "teacher_assignments"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), index=True)
    learning_stage: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    task_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    due_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="published", nullable=False, index=True)
    target_scope: Mapped[str] = mapped_column(String(30), default="all_students", nullable=False)
    required_task_types: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class AssignmentRecipient(Base):
    __tablename__ = "assignment_recipients"
    __table_args__ = (UniqueConstraint("assignment_id", "user_id", name="uq_assignment_recipient"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("teacher_assignments.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="not_started", nullable=False, index=True)
    progress_value: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_time: Mapped[datetime | None] = mapped_column(DateTime)
    updated_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

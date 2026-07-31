from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LessonPublication(Base):
    __tablename__ = "lesson_publications"
    __table_args__ = (
        UniqueConstraint(
            "agent_run_id",
            "teaching_class_id",
            name="uq_lesson_publication_run_class",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_run_id: Mapped[int] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        index=True,
    )
    teaching_class_id: Mapped[int] = mapped_column(
        ForeignKey("teaching_classes.id", ondelete="CASCADE"),
        index=True,
    )
    course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"),
        index=True,
    )
    chapter_id: Mapped[int] = mapped_column(
        ForeignKey("chapters.id", ondelete="CASCADE"),
        index=True,
    )
    created_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    ppt_storage_path: Mapped[str | None] = mapped_column(String(500))
    ppt_file_name: Mapped[str | None] = mapped_column(String(255))
    discussion_activity_ids: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="published", nullable=False, index=True)
    created_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_time: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

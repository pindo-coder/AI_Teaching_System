from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.chapter import Chapter
    from app.models.course import Course
    from app.models.user import User


class LearningProgress(Base):
    __tablename__ = "learning_progress"
    __table_args__ = (
        UniqueConstraint("user_id", "chapter_id", "learning_stage", name="uq_user_chapter_stage"),
        CheckConstraint("learning_stage IN ('preview', 'review', 'exam')", name="ck_learning_stage"),
        CheckConstraint("progress >= 0 AND progress <= 100", name="ck_learning_progress_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), index=True)
    learning_stage: Mapped[str] = mapped_column(String(20), nullable=False)
    progress: Mapped[int] = mapped_column(default=0, nullable=False)
    last_study_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="learning_progress")
    course: Mapped["Course"] = relationship(back_populates="learning_progress")
    chapter: Mapped["Chapter"] = relationship(back_populates="learning_progress")

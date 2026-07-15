from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ReviewPractice(Base):
    """一次章节复习中的单道题目及学生作答记录。"""

    __tablename__ = "review_practices"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    choices: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    answer_index: Mapped[int] = mapped_column(Integer, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source_position: Mapped[str] = mapped_column(Text, default="当前专题正文", nullable=False)
    selected_index: Mapped[int | None] = mapped_column(Integer)
    is_correct: Mapped[bool | None] = mapped_column(Boolean)
    created_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime)

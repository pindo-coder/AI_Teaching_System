from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NewsStudyNote(Base):
    """记录时政材料与个人章节笔记之间的可追溯关联。"""

    __tablename__ = "news_study_notes"
    __table_args__ = (
        UniqueConstraint("user_id", "news_id", "chapter_id", name="uq_news_study_note_user_news_chapter"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    note_id: Mapped[int] = mapped_column(ForeignKey("study_notes.id", ondelete="CASCADE"), index=True)
    news_id: Mapped[int] = mapped_column(ForeignKey("news_items.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), index=True)
    ai_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    textbook_relation: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source_title: Mapped[str] = mapped_column(String(500), nullable=False)
    source_url: Mapped[str] = mapped_column(String(700), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TextbookAnnotation(Base):
    __tablename__ = "textbook_annotations"
    __table_args__ = (
        CheckConstraint(
            "annotation_type IN ('key_point', 'concept', 'question')",
            name="ck_textbook_annotation_type",
        ),
        CheckConstraint("start_offset >= 0", name="ck_textbook_annotation_start_offset"),
        CheckConstraint("end_offset > start_offset", name="ck_textbook_annotation_offset_order"),
        Index("ix_textbook_annotations_user_chapter", "user_id", "chapter_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), index=True)
    block_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    selected_text: Mapped[str] = mapped_column(Text, nullable=False)
    prefix_text: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    suffix_text: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    annotation_type: Mapped[str] = mapped_column(String(20), default="key_point", nullable=False)
    comment: Mapped[str] = mapped_column(Text, default="", nullable=False)
    chapter_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ClassroomActivity(Base):
    __tablename__ = "classroom_activities"

    id: Mapped[int] = mapped_column(primary_key=True)
    teaching_class_id: Mapped[int | None] = mapped_column(
        ForeignKey("teaching_classes.id", ondelete="SET NULL"), index=True
    )
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    minutes: Mapped[int] = mapped_column(Integer, default=8, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="published", nullable=False)
    created_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class ClassroomResponse(Base):
    __tablename__ = "classroom_responses"

    id: Mapped[int] = mapped_column(primary_key=True)
    activity_id: Mapped[int] = mapped_column(ForeignKey("classroom_activities.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    created_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class DiscussionThread(Base):
    __tablename__ = "discussion_threads"

    id: Mapped[int] = mapped_column(primary_key=True)
    teaching_class_id: Mapped[int | None] = mapped_column(ForeignKey("teaching_classes.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[int | None] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), index=True)
    activity_id: Mapped[int | None] = mapped_column(ForeignKey("classroom_activities.id", ondelete="SET NULL"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="published", nullable=False, index=True)
    is_pinned: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)
    reply_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_replied_time: Mapped[datetime | None] = mapped_column(DateTime)
    created_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False, index=True)
    updated_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class DiscussionReply(Base):
    __tablename__ = "discussion_replies"

    id: Mapped[int] = mapped_column(primary_key=True)
    thread_id: Mapped[int] = mapped_column(ForeignKey("discussion_threads.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    parent_reply_id: Mapped[int | None] = mapped_column(ForeignKey("discussion_replies.id", ondelete="CASCADE"), index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="published", nullable=False, index=True)
    created_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

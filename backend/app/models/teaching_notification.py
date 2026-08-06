from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin


class TeachingNotification(TimestampMixin, Base):
    """面向教师/学生的站内教学提醒。正式提醒必须由管理员确认后创建。"""

    __tablename__ = "teaching_notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    recipient_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    policy_change_id: Mapped[int | None] = mapped_column(
        ForeignKey("policy_changes.id", ondelete="SET NULL"), index=True
    )
    notification_type: Mapped[str] = mapped_column(String(30), default="policy_update", nullable=False, index=True)
    level: Mapped[str] = mapped_column(String(20), default="normal", nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    course_ids: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    chapter_ids: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1000))
    action_url: Mapped[str | None] = mapped_column(String(500))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    read_time: Mapped[datetime | None] = mapped_column(DateTime)

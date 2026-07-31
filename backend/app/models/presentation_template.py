from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin


class PresentationTemplate(TimestampMixin, Base):
    """教师上传的 PPTX 风格模板及其可安全继承的设计元数据。"""

    __tablename__ = "presentation_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="ready", nullable=False, index=True)
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    slide_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    aspect_ratio: Mapped[str] = mapped_column(String(30), default="16:9", nullable=False)
    theme_data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin


class MaterialImportBatch(TimestampMixin, Base):
    """管理员确认后的中央材料批量导入任务。"""

    __tablename__ = "material_import_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    original_filename: Mapped[str | None] = mapped_column(String(255))
    sheet_name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(30), default="queued", nullable=False, index=True)
    total_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    course_ids: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    chapter_ids: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    access_policy: Mapped[str] = mapped_column(String(30), default="full_preview", nullable=False)


class MaterialImportItem(TimestampMixin, Base):
    """批次中一条网址的原始字段、处理状态与知识库结果。"""

    __tablename__ = "material_import_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("material_import_batches.id", ondelete="CASCADE"), index=True
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    source_title: Mapped[str | None] = mapped_column(String(255))
    publisher: Mapped[str | None] = mapped_column(String(255))
    published_date: Mapped[date | None] = mapped_column(Date)
    applicable_scope: Mapped[str | None] = mapped_column(String(500))
    version_label: Mapped[str | None] = mapped_column(String(100))
    knowledge_tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="queued", nullable=False, index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="SET NULL"), index=True
    )
    raw_data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

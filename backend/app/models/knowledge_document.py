from typing import TYPE_CHECKING

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.chapter import Chapter
    from app.models.course import Course


class KnowledgeDocument(TimestampMixin, Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    textbook_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("textbook_versions.id", ondelete="SET NULL"), index=True
    )
    source_title: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(500), nullable=False)
    # 教材继续使用单一 course_id；中央和地方材料可通过作用域关联到多本教材，
    # 因而允许这里为空并保留该字段用于兼容既有接口。
    course_id: Mapped[int | None] = mapped_column(
        ForeignKey("courses.id", ondelete="SET NULL"), index=True
    )
    chapter_id: Mapped[int | None] = mapped_column(
        ForeignKey("chapters.id", ondelete="SET NULL"), index=True
    )
    knowledge_point: Mapped[str | None] = mapped_column(String(255))
    vector_collection: Mapped[str] = mapped_column(String(100), nullable=False)
    source_role: Mapped[str] = mapped_column(String(20), default="primary", nullable=False)
    material_type: Mapped[str] = mapped_column(String(20), default="textbook", nullable=False, index=True)
    publisher: Mapped[str | None] = mapped_column(String(255))
    published_date: Mapped[date | None] = mapped_column(Date)
    source_url: Mapped[str | None] = mapped_column(String(1000))
    applicable_scope: Mapped[str | None] = mapped_column(String(500))
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    review_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    verified_time: Mapped[datetime | None] = mapped_column(DateTime)
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    snapshot_time: Mapped[datetime | None] = mapped_column(DateTime)
    version_label: Mapped[str | None] = mapped_column(String(100))
    supersedes_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="SET NULL"), index=True
    )
    access_policy: Mapped[str] = mapped_column(String(30), default="full_preview", nullable=False)
    calibration_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="processing", nullable=False)
    chunk_count: Mapped[int] = mapped_column(default=0, nullable=False)

    course: Mapped["Course | None"] = relationship(back_populates="documents")
    chapter: Mapped["Chapter | None"] = relationship(back_populates="documents")

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
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
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[int | None] = mapped_column(
        ForeignKey("chapters.id", ondelete="SET NULL"), index=True
    )
    knowledge_point: Mapped[str | None] = mapped_column(String(255))
    vector_collection: Mapped[str] = mapped_column(String(100), nullable=False)
    source_role: Mapped[str] = mapped_column(String(20), default="primary", nullable=False)
    access_policy: Mapped[str] = mapped_column(String(30), default="full_preview", nullable=False)
    calibration_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="processing", nullable=False)
    chunk_count: Mapped[int] = mapped_column(default=0, nullable=False)

    course: Mapped["Course"] = relationship(back_populates="documents")
    chapter: Mapped["Chapter | None"] = relationship(back_populates="documents")

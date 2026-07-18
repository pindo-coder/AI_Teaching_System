from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DocumentCourseScope(Base):
    __tablename__ = "document_course_scopes"
    __table_args__ = (UniqueConstraint("document_id", "course_id", name="uq_document_course_scope"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    confirmed_time: Mapped[datetime | None] = mapped_column(DateTime)


class DocumentChapterScope(Base):
    __tablename__ = "document_chapter_scopes"
    __table_args__ = (UniqueConstraint("document_id", "chapter_id", name="uq_document_chapter_scope"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), index=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    confirmed_time: Mapped[datetime | None] = mapped_column(DateTime)


class DocumentClassScope(Base):
    __tablename__ = "document_class_scopes"
    __table_args__ = (UniqueConstraint("document_id", "teaching_class_id", name="uq_document_class_scope"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True)
    teaching_class_id: Mapped[int] = mapped_column(ForeignKey("teaching_classes.id", ondelete="CASCADE"), index=True)


class DocumentKnowledgeTag(Base):
    __tablename__ = "document_knowledge_tags"
    __table_args__ = (UniqueConstraint("document_id", "tag", name="uq_document_knowledge_tag"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True)
    tag: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    created_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

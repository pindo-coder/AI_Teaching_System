from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TextbookVersion(Base):
    __tablename__ = "textbook_versions"
    __table_args__ = (UniqueConstraint("course_id", "version_label", name="uq_textbook_version_label"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    version_label: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False, index=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    created_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class DocumentPage(Base):
    __tablename__ = "document_pages"
    __table_args__ = (UniqueConstraint("document_id", "pdf_page", name="uq_document_pdf_page"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True)
    pdf_page: Mapped[int] = mapped_column(Integer, nullable=False)
    printed_page_label: Mapped[str | None] = mapped_column(String(30))
    # 网页材料通常只有一个逻辑“页”，长篇中文正文很容易超过 MySQL TEXT 的 65KB 上限。
    text: Mapped[str] = mapped_column(Text().with_variant(LONGTEXT(), "mysql"), default="", nullable=False)
    width: Mapped[float | None] = mapped_column(Float)
    height: Mapped[float | None] = mapped_column(Float)
    text_blocks: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)


class PageNumberRange(Base):
    __tablename__ = "page_number_ranges"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True)
    pdf_page_start: Mapped[int] = mapped_column(Integer, nullable=False)
    pdf_page_end: Mapped[int] = mapped_column(Integer, nullable=False)
    numbering_style: Mapped[str] = mapped_column(String(20), default="arabic", nullable=False)
    printed_start: Mapped[str | None] = mapped_column(String(30))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class DocumentOutlineNode(Base):
    __tablename__ = "document_outline_nodes"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("document_outline_nodes.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[int | None] = mapped_column(ForeignKey("chapters.id", ondelete="SET NULL"), index=True)
    node_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pdf_page_start: Mapped[int] = mapped_column(Integer, nullable=False)
    pdf_page_end: Mapped[int] = mapped_column(Integer, nullable=False)
    start_anchor: Mapped[str | None] = mapped_column(String(500))
    end_anchor: Mapped[str | None] = mapped_column(String(500))
    retrieval_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    calibration_status: Mapped[str] = mapped_column(String(20), default="auto", nullable=False)


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (UniqueConstraint("document_id", "chunk_index", "index_version", name="uq_document_chunk_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True)
    vector_id: Mapped[str] = mapped_column(String(160), unique=True, nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    chapter_id: Mapped[int | None] = mapped_column(ForeignKey("chapters.id", ondelete="SET NULL"), index=True)
    outline_node_id: Mapped[int | None] = mapped_column(ForeignKey("document_outline_nodes.id", ondelete="SET NULL"), index=True)
    pdf_page_start: Mapped[int] = mapped_column(Integer, nullable=False)
    pdf_page_end: Mapped[int] = mapped_column(Integer, nullable=False)
    paragraph_index: Mapped[int | None] = mapped_column(Integer)
    printed_page_start: Mapped[str | None] = mapped_column(String(30))
    printed_page_end: Mapped[str | None] = mapped_column(String(30))
    section_path: Mapped[str | None] = mapped_column(String(1000))
    start_anchor: Mapped[str | None] = mapped_column(String(500))
    end_anchor: Mapped[str | None] = mapped_column(String(500))
    index_version: Mapped[str] = mapped_column(String(100), nullable=False)


class IndexVersion(Base):
    __tablename__ = "index_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    collection_name: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    embedding_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_size: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_overlap: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="building", nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    created_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    activated_time: Mapped[datetime | None] = mapped_column(DateTime)


class CitationFeedback(Base):
    __tablename__ = "citation_feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="SET NULL"), index=True)
    vector_id: Mapped[str | None] = mapped_column(String(160), index=True)
    feedback_type: Mapped[str] = mapped_column(String(30), default="inaccurate", nullable=False)
    note: Mapped[str | None] = mapped_column(String(1000))
    question: Mapped[str | None] = mapped_column(Text)
    created_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

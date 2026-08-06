from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin


class AuthoritySourceRegistry(TimestampMixin, Base):
    """管理员维护的权威来源白名单。"""

    __tablename__ = "source_registries"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source_level: Mapped[str] = mapped_column(String(4), default="A", nullable=False, index=True)
    adapter_type: Mapped[str] = mapped_column(String(30), default="html_list", nullable=False)
    entry_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    fetch_interval_minutes: Mapped[int] = mapped_column(Integer, default=1440, nullable=False)
    request_interval_seconds: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    allow_full_text: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    allow_alert: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    last_success_time: Mapped[datetime | None] = mapped_column(DateTime)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)


class DiscoveryJob(TimestampMixin, Base):
    """一次权威资料发现任务，任务执行与页面生命周期解耦。"""

    __tablename__ = "discovery_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    trigger_type: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)
    query_text: Mapped[str | None] = mapped_column(String(500))
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    source_ids: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False, index=True)
    progress_stage: Mapped[str] = mapped_column(String(40), default="等待执行", nullable=False)
    total_sources: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed_sources: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    discovered_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fetched_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    deduped_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pending_review_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    filtered_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    extraction_failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_time: Mapped[datetime | None] = mapped_column(DateTime)
    finished_time: Mapped[datetime | None] = mapped_column(DateTime)


class MaterialCandidate(TimestampMixin, Base):
    """抓取后等待管理员确认的候选材料；未发布前不参与正式 RAG。"""

    __tablename__ = "material_candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    discovery_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("discovery_jobs.id", ondelete="SET NULL"), index=True
    )
    source_registry_id: Mapped[int] = mapped_column(
        ForeignKey("source_registries.id", ondelete="RESTRICT"), index=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    source_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    canonical_url: Mapped[str] = mapped_column(String(1000), nullable=False, index=True)
    publisher: Mapped[str | None] = mapped_column(String(255))
    published_date: Mapped[date | None] = mapped_column(Date)
    source_level: Mapped[str] = mapped_column(String(4), nullable=False, index=True)
    recommended_material_type: Mapped[str] = mapped_column(String(20), default="central", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="discovered", nullable=False, index=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    content_preview: Mapped[str | None] = mapped_column(Text)
    extraction_quality_score: Mapped[float] = mapped_column(default=0, nullable=False)
    relevance_score: Mapped[float] = mapped_column(default=0, nullable=False)
    importance_score: Mapped[float] = mapped_column(default=0, nullable=False, index=True)
    importance_level: Mapped[str] = mapped_column(String(20), default="observe", nullable=False, index=True)
    importance_reason: Mapped[str | None] = mapped_column(Text)
    freshness_score: Mapped[float] = mapped_column(default=0, nullable=False)
    novelty_score: Mapped[float] = mapped_column(default=0, nullable=False)
    analysis_reason: Mapped[str | None] = mapped_column(Text)
    review_notes: Mapped[str | None] = mapped_column(Text)
    course_ids: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    chapter_ids: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    knowledge_tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    # AI/规则建议与管理员最终确认范围分开保存，避免自动分析直接改变正式 RAG 范围。
    suggested_course_ids: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    suggested_chapter_ids: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    suggested_knowledge_tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    association_confidence: Mapped[float] = mapped_column(default=0, nullable=False)
    association_reason: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    reviewed_time: Mapped[datetime | None] = mapped_column(DateTime)
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="SET NULL"), index=True
    )


class MaterialSnapshot(TimestampMixin, Base):
    """每次成功抓取的独立正文快照，用于后续版本与政策差异比较。"""

    __tablename__ = "material_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("material_candidates.id", ondelete="CASCADE"), index=True
    )
    fetched_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    response_etag: Mapped[str | None] = mapped_column(String(255))
    last_modified: Mapped[str | None] = mapped_column(String(255))
    parser_version: Mapped[str] = mapped_column(String(40), default="authority-v2", nullable=False)
    fetched_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class PolicyChange(TimestampMixin, Base):
    """候选材料与既有权威资料/教材的可追溯差异证据。"""

    __tablename__ = "policy_changes"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("material_candidates.id", ondelete="CASCADE"), index=True
    )
    old_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="SET NULL"), index=True
    )
    old_chapter_id: Mapped[int | None] = mapped_column(
        ForeignKey("chapters.id", ondelete="SET NULL"), index=True
    )
    change_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    old_source_title: Mapped[str | None] = mapped_column(String(500))
    old_source_url: Mapped[str | None] = mapped_column(String(1000))
    new_source_title: Mapped[str | None] = mapped_column(String(500))
    new_source_url: Mapped[str | None] = mapped_column(String(1000))
    old_excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    new_excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    similarity_score: Mapped[float] = mapped_column(default=0, nullable=False)
    importance: Mapped[str] = mapped_column(String(20), default="medium", nullable=False, index=True)
    alert_recommended: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    review_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, index=True)
    affected_course_ids: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    affected_chapter_ids: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    ai_explanation: Mapped[str | None] = mapped_column(Text)
    # confirmed 后的知识库同步状态，避免“已确认”被误解为已经进入正式 RAG。
    kb_sync_status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False, index=True)
    kb_synced_time: Mapped[datetime | None] = mapped_column(DateTime)
    kb_error: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    reviewed_time: Mapped[datetime | None] = mapped_column(DateTime)

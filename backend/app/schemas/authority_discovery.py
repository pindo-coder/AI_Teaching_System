from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AuthoritySourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    domain: str = Field(min_length=3, max_length=255)
    source_level: Literal["A", "B", "C", "D"] = "A"
    adapter_type: Literal["html_list", "rss", "sitemap", "single_article"] = "html_list"
    entry_url: str = Field(min_length=8, max_length=1000)
    fetch_interval_minutes: int = Field(default=1440, ge=5, le=10080)
    request_interval_seconds: int = Field(default=3, ge=1, le=60)
    allow_full_text: bool = True
    allow_alert: bool = True
    is_enabled: bool = True


class AuthoritySourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    source_level: Literal["A", "B", "C", "D"] | None = None
    adapter_type: Literal["html_list", "rss", "sitemap", "single_article"] | None = None
    entry_url: str | None = Field(default=None, min_length=8, max_length=1000)
    fetch_interval_minutes: int | None = Field(default=None, ge=5, le=10080)
    request_interval_seconds: int | None = Field(default=None, ge=1, le=60)
    allow_full_text: bool | None = None
    allow_alert: bool | None = None
    is_enabled: bool | None = None


class AuthoritySourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    domain: str
    source_level: str
    adapter_type: str
    entry_url: str
    fetch_interval_minutes: int
    request_interval_seconds: int
    allow_full_text: bool
    allow_alert: bool
    is_enabled: bool
    last_success_time: datetime | None
    consecutive_failures: int
    last_error: str | None
    created_time: datetime
    updated_time: datetime


class DiscoveryJobCreate(BaseModel):
    query_text: str | None = Field(default=None, max_length=500)
    keywords: list[str] = Field(default_factory=list, max_length=30)
    start_date: date | None = None
    end_date: date | None = None
    source_ids: list[int] = Field(default_factory=list, max_length=20)


class DiscoveryJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_by: int
    trigger_type: str
    query_text: str | None
    keywords: list[str]
    start_date: date | None
    end_date: date | None
    source_ids: list[int]
    status: str
    progress_stage: str
    total_sources: int
    processed_sources: int
    discovered_count: int
    fetched_count: int
    deduped_count: int
    pending_review_count: int
    filtered_count: int
    extraction_failed_count: int
    failed_count: int
    retry_count: int
    error_message: str | None
    started_time: datetime | None
    finished_time: datetime | None
    created_time: datetime
    updated_time: datetime


class CandidateReview(BaseModel):
    action: Literal["publish", "reject", "duplicate"]
    source_title: str | None = Field(default=None, max_length=500)
    publisher: str | None = Field(default=None, max_length=255)
    published_date: date | None = None
    applicable_scope: str | None = Field(default=None, max_length=500)
    course_ids: list[int] = Field(default_factory=list, max_length=30)
    chapter_ids: list[int] = Field(default_factory=list, max_length=100)
    knowledge_tags: list[str] = Field(default_factory=list, max_length=30)
    review_notes: str | None = Field(default=None, max_length=2000)


class CandidateBatchAction(BaseModel):
    candidate_ids: list[int] = Field(min_length=1, max_length=200)
    action: Literal["reject", "observe", "duplicate", "delete"]
    note: str | None = Field(default=None, max_length=2000)


class CandidateDecisionSummary(BaseModel):
    pending_review: int
    high_priority: int
    observed: int
    filtered: int


class CandidateTopicMember(BaseModel):
    id: int
    title: str
    publisher: str | None
    source_level: str
    published_date: date | None
    importance_score: float
    association_confidence: float


class CandidateTopicGroup(BaseModel):
    group_key: str
    title: str
    primary_candidate_id: int
    candidate_ids: list[int]
    member_count: int
    suggested_course_ids: list[int]
    suggested_chapter_ids: list[int]
    reason: str
    members: list[CandidateTopicMember]


class MaterialCandidateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    discovery_job_id: int | None
    source_registry_id: int
    title: str
    source_url: str
    canonical_url: str
    publisher: str | None
    published_date: date | None
    source_level: str
    recommended_material_type: str
    status: str
    content_hash: str | None
    content_preview: str | None
    extraction_quality_score: float
    relevance_score: float
    importance_score: float
    importance_level: str
    importance_reason: str | None
    freshness_score: float
    novelty_score: float
    analysis_reason: str | None
    review_notes: str | None
    course_ids: list[int]
    chapter_ids: list[int]
    knowledge_tags: list[str]
    suggested_course_ids: list[int] | None = None
    suggested_chapter_ids: list[int] | None = None
    suggested_knowledge_tags: list[str] | None = None
    association_confidence: float = 0
    association_reason: str | None = None
    reviewed_by: int | None
    reviewed_time: datetime | None
    document_id: int | None
    created_time: datetime
    updated_time: datetime


class MaterialSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    candidate_id: int
    fetched_url: str
    content_hash: str
    response_etag: str | None
    last_modified: str | None
    parser_version: str
    fetched_time: datetime


class PolicyChangeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    candidate_id: int
    old_document_id: int | None
    old_chapter_id: int | None
    change_type: str
    old_source_title: str | None
    old_source_url: str | None
    new_source_title: str | None
    new_source_url: str | None
    old_excerpt: str
    new_excerpt: str
    similarity_score: float
    evidence_confidence: float
    importance: str
    alert_recommended: bool
    review_status: str
    affected_course_ids: list[int]
    affected_chapter_ids: list[int]
    ai_explanation: str | None
    kb_sync_status: str
    kb_synced_time: datetime | None
    kb_error: str | None
    reviewed_by: int | None
    reviewed_time: datetime | None
    created_time: datetime
    updated_time: datetime


class PolicyChangeReview(BaseModel):
    action: Literal["confirm", "dismiss", "observe"]
    note: str | None = Field(default=None, max_length=2000)

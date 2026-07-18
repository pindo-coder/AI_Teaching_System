from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_title: str
    source_type: str
    original_filename: str
    course_id: int | None
    chapter_id: int | None
    textbook_version_id: int | None
    knowledge_point: str | None
    status: str
    source_role: str
    material_type: str = "textbook"
    publisher: str | None = None
    published_date: date | None = None
    source_url: str | None = None
    applicable_scope: str | None = None
    owner_user_id: int | None = None
    review_status: str = "pending"
    is_active: bool = True
    verified_by: int | None = None
    verified_time: datetime | None = None
    content_hash: str | None = None
    snapshot_time: datetime | None = None
    version_label: str | None = None
    supersedes_document_id: int | None = None
    course_ids: list[int] = Field(default_factory=list)
    chapter_ids: list[int] = Field(default_factory=list)
    teaching_class_ids: list[int] = Field(default_factory=list)
    knowledge_tags: list[str] = Field(default_factory=list)
    access_policy: str
    calibration_status: str
    chunk_count: int
    created_time: datetime
    updated_time: datetime


class TextbookVersionRead(BaseModel):
    id: int
    course_id: int
    version_label: str
    status: str
    is_current: bool
    created_time: datetime
    documents: list[KnowledgeDocumentRead] = Field(default_factory=list)


class KnowledgeSearchRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    course_id: int
    chapter_id: int | None = None
    top_k: int = Field(default=4, ge=1, le=20)


class KnowledgeSearchItem(BaseModel):
    content: str
    score: float
    metadata: dict[str, object]


class MaterialUrlCreate(BaseModel):
    source_url: str = Field(min_length=8, max_length=1000)
    source_title: str = Field(min_length=1, max_length=255)
    publisher: str = Field(min_length=1, max_length=255)
    published_date: date
    applicable_scope: str | None = Field(default=None, max_length=500)
    version_label: str | None = Field(default=None, max_length=100)
    supersedes_document_id: int | None = None
    access_policy: Literal["citation_only", "full_preview", "download"] = "full_preview"
    course_ids: list[int] = Field(default_factory=list)
    chapter_ids: list[int] = Field(default_factory=list)
    knowledge_tags: list[str] = Field(default_factory=list, max_length=30)


class MaterialScopeUpdate(BaseModel):
    course_ids: list[int] = Field(default_factory=list)
    chapter_ids: list[int] = Field(default_factory=list)
    teaching_class_ids: list[int] = Field(default_factory=list)
    knowledge_tags: list[str] = Field(default_factory=list, max_length=30)


class MaterialClassificationUpdate(BaseModel):
    material_type: Literal["central", "textbook", "local"]
    publisher: str | None = Field(default=None, max_length=255)
    published_date: date | None = None
    applicable_scope: str | None = Field(default=None, max_length=500)


class MaterialSuggestion(BaseModel):
    course_id: int
    course_name: str
    chapter_id: int | None = None
    chapter_title: str | None = None
    score: float = 0


class PageNumberRangeInput(BaseModel):
    pdf_page_start: int = Field(ge=1)
    pdf_page_end: int = Field(ge=1)
    numbering_style: str = Field(default="arabic", pattern="^(arabic|roman_upper|roman_lower|none)$")
    printed_start: str | None = Field(default=None, max_length=30)


class OutlineNodeInput(BaseModel):
    client_id: str = Field(min_length=1, max_length=80)
    parent_client_id: str | None = Field(default=None, max_length=80)
    chapter_id: int | None = None
    node_type: str = Field(pattern="^(chapter|section|knowledge_point|preface|reference)$")
    title: str = Field(min_length=1, max_length=255)
    sort_order: int = 0
    pdf_page_start: int = Field(ge=1)
    pdf_page_end: int = Field(ge=1)
    start_anchor: str | None = Field(default=None, max_length=500)
    end_anchor: str | None = Field(default=None, max_length=500)
    retrieval_enabled: bool = True


class DocumentCalibrationUpdate(BaseModel):
    version_label: str = Field(default="当前版", min_length=1, max_length=100)
    access_policy: str = Field(default="full_preview", pattern="^(citation_only|full_preview|download)$")
    page_number_ranges: list[PageNumberRangeInput] = Field(default_factory=list)
    outline: list[OutlineNodeInput] = Field(min_length=1)


class CitationFeedbackCreate(BaseModel):
    document_id: int | None = None
    vector_id: str | None = Field(default=None, max_length=160)
    feedback_type: str = Field(default="inaccurate", pattern="^(inaccurate|wrong_page|unsupported|other)$")
    note: str | None = Field(default=None, max_length=1000)
    question: str | None = Field(default=None, max_length=2000)

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings


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


class MaterialPreviewColumn(BaseModel):
    field: str
    column: str
    confidence: float


class MaterialPreviewRow(BaseModel):
    row_number: int
    selected: bool = True
    source_url: str = ""
    source_title: str = ""
    publisher: str = ""
    published_date: str = ""
    applicable_scope: str = ""
    version_label: str = ""
    knowledge_tags: list[str] = Field(default_factory=list)
    raw_data: dict[str, str] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class MaterialPreviewSheet(BaseModel):
    name: str
    header_row: int
    columns: list[str]
    mapping: list[MaterialPreviewColumn]
    rows: list[MaterialPreviewRow]


class MaterialBatchPreview(BaseModel):
    filename: str
    sheets: list[MaterialPreviewSheet]


class MaterialBatchItemCreate(BaseModel):
    row_number: int = Field(ge=1)
    source_url: str = Field(min_length=8, max_length=1000)
    source_title: str | None = Field(default=None, max_length=255)
    publisher: str | None = Field(default=None, max_length=255)
    published_date: date | None = None
    applicable_scope: str | None = Field(default=None, max_length=500)
    version_label: str | None = Field(default=None, max_length=100)
    knowledge_tags: list[str] = Field(default_factory=list, max_length=30)
    raw_data: dict[str, str] = Field(default_factory=dict)


class MaterialBatchCreate(BaseModel):
    original_filename: str | None = Field(default=None, max_length=255)
    sheet_name: str | None = Field(default=None, max_length=255)
    access_policy: Literal["citation_only", "full_preview", "download"] = "full_preview"
    course_ids: list[int] = Field(default_factory=list)
    chapter_ids: list[int] = Field(default_factory=list)
    items: list[MaterialBatchItemCreate] = Field(
        min_length=1, max_length=settings.material_batch_max_items
    )


class MaterialBatchItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    row_number: int
    source_url: str
    source_title: str | None
    publisher: str | None
    published_date: date | None
    applicable_scope: str | None
    version_label: str | None
    knowledge_tags: list[str]
    status: str
    error_message: str | None
    document_id: int | None
    raw_data: dict[str, str]


class MaterialBatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    original_filename: str | None
    sheet_name: str | None
    status: str
    total_count: int
    completed_count: int
    success_count: int
    failed_count: int
    duplicate_count: int
    course_ids: list[int]
    chapter_ids: list[int]
    access_policy: str
    created_time: datetime
    updated_time: datetime
    items: list[MaterialBatchItemRead] = Field(default_factory=list)


class MaterialBatchSummaryRead(BaseModel):
    """任务中心使用的轻量批次数据，不携带可能很大的逐条明细。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    original_filename: str | None
    sheet_name: str | None
    status: str
    total_count: int
    completed_count: int
    success_count: int
    failed_count: int
    duplicate_count: int
    created_time: datetime
    updated_time: datetime


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

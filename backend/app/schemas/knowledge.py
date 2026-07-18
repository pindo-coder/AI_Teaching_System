from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_title: str
    source_type: str
    original_filename: str
    course_id: int
    chapter_id: int | None
    textbook_version_id: int | None
    knowledge_point: str | None
    status: str
    source_role: str
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

from datetime import datetime

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StudyNoteUpdate(BaseModel):
    content: str = Field(max_length=30000)


class StudyNoteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    course_id: int
    chapter_id: int
    content: str
    created_time: datetime
    updated_time: datetime


class StudyNoteListItem(StudyNoteRead):
    course_name: str
    chapter_title: str


AnnotationType = Literal["key_point", "concept", "question"]


class TextbookAnnotationCreate(BaseModel):
    block_index: int = Field(ge=0)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    selected_text: str = Field(min_length=1, max_length=2000)
    prefix_text: str = Field(default="", max_length=300)
    suffix_text: str = Field(default="", max_length=300)
    annotation_type: AnnotationType = "key_point"
    comment: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def validate_offsets(self) -> "TextbookAnnotationCreate":
        if self.end_offset <= self.start_offset:
            raise ValueError("标注结束位置必须晚于开始位置")
        return self


class TextbookAnnotationUpdate(BaseModel):
    annotation_type: AnnotationType | None = None
    comment: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_changes(self) -> "TextbookAnnotationUpdate":
        if self.annotation_type is None and self.comment is None:
            raise ValueError("请至少修改一项标注内容")
        return self


class TextbookAnnotationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    course_id: int
    chapter_id: int
    block_index: int
    start_offset: int
    end_offset: int
    selected_text: str
    prefix_text: str
    suffix_text: str
    annotation_type: AnnotationType
    comment: str
    chapter_content_hash: str
    created_time: datetime
    updated_time: datetime


class ReviewRead(BaseModel):
    id: int
    course_id: int
    chapter_id: int
    course_name: str
    chapter_title: str
    review_count: int
    interval_days: int
    next_review_at: datetime
    last_reviewed_at: datetime | None


class StudyChatMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    course_id: int
    chapter_id: int
    role: str
    content: str
    model: str | None
    sources: list[dict] = Field(default_factory=list)
    created_time: datetime


class StudyChatHistorySave(BaseModel):
    course_id: int
    chapter_id: int
    question: str = Field(min_length=1, max_length=2000)
    answer: str = Field(min_length=1, max_length=30000)
    model: str | None = Field(default=None, max_length=80)
    sources: list[dict] = Field(default_factory=list)


class NoteSearchItem(BaseModel):
    id: int
    course_id: int
    chapter_id: int
    course_name: str
    chapter_title: str
    excerpt: str
    score: float


class RelatedTextbookItem(BaseModel):
    source_title: str
    excerpt: str
    position: str
    score: float


class NoteRelatedData(BaseModel):
    related_notes: list[NoteSearchItem] = Field(default_factory=list)
    textbook_chunks: list[RelatedTextbookItem] = Field(default_factory=list)
    status: str = "ready"
    message: str = ""


class ReviewQuestionRead(BaseModel):
    id: int
    question: str
    source_position: str


class ReviewAnswerSubmit(BaseModel):
    answer: str = Field(min_length=1, max_length=3000)


class ReviewAnswerResult(BaseModel):
    id: int
    is_correct: bool
    feedback: str
    reference_answer: str
    source_position: str
    ai_reference_answer: str = ""
    reference_knowledge_points: list[str] = Field(default_factory=list)
    completed: bool
    next_interval_days: int | None = None


class ReviewReferenceItem(BaseModel):
    practice_id: int
    ai_reference_answer: str
    reference_knowledge_points: list[str] = Field(default_factory=list)


class ReviewReferencesRequest(BaseModel):
    practice_ids: list[int] = Field(min_length=1, max_length=10)
    force: bool = False


class ReviewSaveToNotesRequest(BaseModel):
    practice_ids: list[int] = Field(min_length=1, max_length=10)


class ReviewResultItem(BaseModel):
    practice_id: int
    question: str
    source_position: str
    student_answer: str
    is_correct: bool
    feedback: str
    ai_reference_answer: str
    reference_knowledge_points: list[str] = Field(default_factory=list)
    reference_generated: bool = False

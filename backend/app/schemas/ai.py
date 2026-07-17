from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.learning import LearningStage


AiTaskType = Literal[
    "question_answer",
    "chapter_summary",
    "preview_questions",
    "review_outline",
    "mock_questions",
    "note_polish",
    "note_expand",
    "note_outline",
    "note_knowledge_structure",
    "note_real_significance",
    "note_concept_compare",
    "news_study_note",
]


class AiAssistRequest(BaseModel):
    course_id: int
    chapter_id: int
    learning_stage: LearningStage
    task_type: AiTaskType = "question_answer"
    question: str = Field(min_length=1, max_length=2000)


class AiSource(BaseModel):
    source_type: str
    source_title: str
    course_id: int
    chapter_id: int
    excerpt: str
    position: str = "当前专题正文"
    document_id: int | None = None
    vector_id: str | None = None
    section_path: str | None = None
    pdf_page_start: int | None = None
    pdf_page_end: int | None = None
    paragraph_index: int | None = None
    printed_page_start: str | None = None
    printed_page_end: str | None = None
    evidence_type: str = "教材直接依据"


class AiAssistData(BaseModel):
    answer: str
    grounded: bool
    model: str
    sources: list[AiSource] = Field(default_factory=list)

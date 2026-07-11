from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.learning import LearningStage


AiTaskType = Literal[
    "question_answer",
    "chapter_summary",
    "preview_questions",
    "review_outline",
    "mock_questions",
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


class AiAssistData(BaseModel):
    answer: str
    grounded: bool
    model: str
    sources: list[AiSource] = Field(default_factory=list)

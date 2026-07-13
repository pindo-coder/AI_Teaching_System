from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


TaskStatus = Literal["not_started", "in_progress", "completed"]


class LearningEventCreate(BaseModel):
    course_id: int
    chapter_id: int
    learning_stage: Literal["preview", "review", "exam"]
    event_type: Literal[
        "chapter_opened", "reading_progress", "ai_assist_used", "question_submitted",
        "note_saved", "activity_submitted", "quiz_completed"
    ]
    event_data: dict[str, Any] = Field(default_factory=dict)


class TaskPointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    course_id: int
    chapter_id: int
    learning_stage: str
    task_type: str
    title: str
    description: str
    weight: int
    sort_order: int
    status: TaskStatus = "not_started"
    progress_value: int = 0
    evidence_summary: str = ""
    completed_time: datetime | None = None


class TaskProgressSummary(BaseModel):
    course_id: int
    chapter_id: int
    learning_stage: str
    completed_count: int
    total_count: int
    progress: int
    tasks: list[TaskPointRead]

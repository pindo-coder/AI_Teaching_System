from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class StudyNoteUpdate(BaseModel):
    content: str = Field(max_length=10000)


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

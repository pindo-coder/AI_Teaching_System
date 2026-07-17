from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ActivityCreate(BaseModel):
    teaching_class_id: int | None = None
    course_id: int
    chapter_id: int
    question: str = Field(min_length=5, max_length=2000)
    minutes: int = Field(default=8, ge=3, le=60)


class ActivityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    teaching_class_id: int | None
    course_id: int
    chapter_id: int
    created_by: int
    question: str
    minutes: int
    status: str
    created_time: datetime


class ResponseCreate(BaseModel):
    answer: str = Field(min_length=1, max_length=5000)


class ResponseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    activity_id: int
    user_id: int
    answer: str
    created_time: datetime

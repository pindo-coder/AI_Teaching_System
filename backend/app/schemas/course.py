from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CourseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None


class CourseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None


class CourseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    created_time: datetime
    updated_time: datetime


class ChapterCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str | None = None
    sort_order: int = Field(default=0, ge=0)


class ChapterUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = None
    sort_order: int | None = Field(default=None, ge=0)


class ChapterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    course_id: int
    title: str
    content: str | None
    sort_order: int
    created_time: datetime
    updated_time: datetime


class CourseDetail(CourseRead):
    chapters: list[ChapterRead]

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.core.time import utc_iso


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


class DiscussionCreate(BaseModel):
    teaching_class_id: int | None = None
    course_id: int | None = None
    chapter_id: int | None = None
    activity_id: int | None = None
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=10000)


class DiscussionUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = Field(default=None, min_length=1, max_length=10000)


class DiscussionReplyCreate(BaseModel):
    content: str = Field(min_length=1, max_length=5000)
    parent_reply_id: int | None = None


class DiscussionReplyUpdate(BaseModel):
    content: str = Field(min_length=1, max_length=5000)


class DiscussionAuthor(BaseModel):
    id: int
    name: str
    role: str


class DiscussionThreadRead(BaseModel):
    id: int
    teaching_class_id: int | None
    course_id: int | None
    chapter_id: int | None
    activity_id: int | None
    title: str
    content: str
    status: str
    is_pinned: bool
    reply_count: int
    last_replied_time: datetime | None
    created_time: datetime
    updated_time: datetime
    author: DiscussionAuthor

    @field_serializer("last_replied_time", when_used="json")
    def serialize_last_replied_time(self, value: datetime | None) -> str | None:
        return utc_iso(value) if value is not None else None

    @field_serializer("created_time", "updated_time", when_used="json")
    def serialize_times(self, value: datetime) -> str:
        return utc_iso(value)


class DiscussionReplyRead(BaseModel):
    id: int
    thread_id: int
    parent_reply_id: int | None
    content: str
    status: str
    created_time: datetime
    updated_time: datetime
    author: DiscussionAuthor

    @field_serializer("created_time", "updated_time", when_used="json")
    def serialize_times(self, value: datetime) -> str:
        return utc_iso(value)

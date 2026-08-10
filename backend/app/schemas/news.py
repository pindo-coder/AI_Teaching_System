from datetime import UTC, datetime

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from app.core.time import BUSINESS_TIMEZONE, utc_iso


class NewsItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    summary: str | None
    source_name: str
    source_url: str
    article_url: str
    published_time: datetime | None
    published_time_is_utc: bool = Field(default=True, exclude=True)
    fetched_time: datetime

    @model_validator(mode="after")
    def attach_published_timezone(self):
        if self.published_time is not None and (
            self.published_time.tzinfo is None or self.published_time.utcoffset() is None
        ):
            source_timezone = UTC if self.published_time_is_utc else BUSINESS_TIMEZONE
            self.published_time = self.published_time.replace(tzinfo=source_timezone)
        return self

    @field_serializer("published_time", when_used="json")
    def serialize_published_time(self, value: datetime | None) -> str | None:
        return utc_iso(value) if value is not None else None

    @field_serializer("fetched_time", when_used="json")
    def serialize_fetched_time(self, value: datetime) -> str:
        # fetched_time has always been written with datetime.utcnow/utc_now.
        return utc_iso(value)


class NewsSearchData(BaseModel):
    items: list[NewsItemRead] = Field(default_factory=list)
    total: int
    page: int
    page_size: int
    pages: int
    sources: list[str] = Field(default_factory=list)


class TextbookRelationItem(BaseModel):
    course_id: int
    chapter_id: int
    chapter_title: str
    score: float
    reason: str
    excerpt: str
    position: str


class NewsStudyNoteSave(BaseModel):
    chapter_id: int
    content: str = Field(min_length=1, max_length=16000)
    textbook_relation: str = Field(default="", max_length=2000)
    mode: Literal["append", "create"] = "append"


class NewsStudyNoteSaveResult(BaseModel):
    note_id: int
    course_id: int
    chapter_id: int
    created: bool
    appended: bool

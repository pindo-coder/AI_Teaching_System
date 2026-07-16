from datetime import datetime

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class NewsItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    summary: str | None
    source_name: str
    source_url: str
    article_url: str
    published_time: datetime | None
    fetched_time: datetime


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

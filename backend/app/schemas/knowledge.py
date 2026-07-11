from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_title: str
    source_type: str
    original_filename: str
    course_id: int
    chapter_id: int | None
    knowledge_point: str | None
    status: str
    chunk_count: int
    created_time: datetime
    updated_time: datetime


class KnowledgeSearchRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    course_id: int
    chapter_id: int | None = None
    top_k: int = Field(default=4, ge=1, le=20)


class KnowledgeSearchItem(BaseModel):
    content: str
    score: float
    metadata: dict[str, object]

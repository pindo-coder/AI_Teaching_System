from datetime import datetime

from pydantic import BaseModel, ConfigDict


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

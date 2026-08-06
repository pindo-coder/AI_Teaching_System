from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TeachingNotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    policy_change_id: int | None
    notification_type: str
    level: str
    title: str
    content: str
    course_ids: list[int]
    chapter_ids: list[int]
    source_url: str | None
    action_url: str | None
    is_read: bool
    read_time: datetime | None
    created_time: datetime
    updated_time: datetime


class NotificationReadUpdate(BaseModel):
    is_read: bool = True

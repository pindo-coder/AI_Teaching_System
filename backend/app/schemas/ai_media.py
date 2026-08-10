from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


MediaKind = Literal["image", "audio"]


class AiMediaAssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_user_id: int
    course_id: int | None
    chapter_id: int | None
    media_kind: MediaKind
    original_filename: str
    mime_type: str
    byte_size: int
    sha256: str
    duration_seconds: float | None
    status: str
    error_message: str | None
    created_time: datetime
    updated_time: datetime


class AiMediaCapabilities(BaseModel):
    image_enabled: bool
    audio_enabled: bool
    max_images: int
    max_image_mb: int
    max_audio_mb: int
    max_audio_seconds: int
    retention_hours: int
    user_quota_mb: int


class AiMediaTranscription(BaseModel):
    text: str

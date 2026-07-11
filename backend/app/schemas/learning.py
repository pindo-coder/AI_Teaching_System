from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.course import ChapterRead, CourseRead
from app.schemas.user import UserRead


LearningStage = Literal["preview", "review", "exam"]


class ProgressUpdate(BaseModel):
    course_id: int
    chapter_id: int
    learning_stage: LearningStage
    progress: int = Field(ge=0, le=100)


class ProgressRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    course_id: int
    chapter_id: int
    learning_stage: LearningStage
    progress: int
    last_study_time: datetime


class DashboardData(BaseModel):
    user: UserRead
    current_course: CourseRead | None = None
    current_chapter: ChapterRead | None = None
    recent_progress: list[ProgressRead] = Field(default_factory=list)
    overall_progress: int = 0

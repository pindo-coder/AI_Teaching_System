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


class LearningFootprintActivity(BaseModel):
    event_type: str
    label: str
    created_time: datetime
    learning_stage: LearningStage | None = None


class LearningFootprint(BaseModel):
    course_id: int
    chapter_id: int
    learning_stage: LearningStage
    status: Literal["not_started", "in_progress", "has_output"]
    status_label: str
    last_activity_time: datetime | None = None
    activities: list[LearningFootprintActivity] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    next_action: str


class DashboardData(BaseModel):
    user: UserRead
    current_course: CourseRead | None = None
    current_chapter: ChapterRead | None = None
    recent_progress: list[ProgressRead] = Field(default_factory=list)
    # Kept temporarily for clients that have not migrated to learning footprints.
    overall_progress: int = 0
    learning_status: Literal["not_started", "in_progress", "has_output"] = "not_started"
    learning_status_label: str = "未开始"
    stage_footprints: list[LearningFootprint] = Field(default_factory=list)
    recent_activities: list[LearningFootprintActivity] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    next_action: str = "先选择一个教材专题开始学习"

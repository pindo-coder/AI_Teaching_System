from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.learning import LearningStage
from app.schemas.ai import AiSource


AgentType = Literal["teacher_lesson_prep"]
AgentStatus = Literal[
    "queued",
    "running",
    "waiting_confirmation",
    "completed",
    "failed",
    "cancelled",
]


class LessonPrepInput(BaseModel):
    lesson_hours: int = Field(default=2, ge=1, le=8)
    learning_stage: LearningStage = "preview"
    student_level: str = Field(default="本科生", min_length=1, max_length=100)
    completion_condition: str | None = Field(default="教材阅读", max_length=200)
    teaching_goal: str | None = Field(default=None, max_length=1000)
    output_types: list[Literal["outline", "lesson_plan", "ppt"]] = Field(
        default_factory=lambda: ["outline"]
    )


class AgentRunCreate(BaseModel):
    agent_type: AgentType
    course_id: int
    chapter_id: int
    teaching_class_id: int | None = None
    input: LessonPrepInput = Field(default_factory=LessonPrepInput)


class AgentConfirmRequest(BaseModel):
    action: Literal["approve_evidence"]


class PptPreferences(BaseModel):
    scenario: Literal["classroom", "open_lesson", "presentation"] = "classroom"
    visual_style: Literal["serious", "modern", "youthful"] = "modern"
    content_density: Literal["concise", "standard", "detailed"] = "standard"
    min_slides: int = Field(default=9, ge=6, le=30)
    max_slides: int = Field(default=12, ge=6, le=30)
    slide_count: int | None = Field(default=None, ge=6, le=30)
    include_interaction: bool = True
    include_visuals: bool = False
    template_id: int | None = None

    @model_validator(mode="after")
    def normalize_slide_count(self):
        if self.slide_count is not None:
            self.min_slides = self.slide_count
            self.max_slides = self.slide_count
        if self.min_slides > self.max_slides:
            raise ValueError("PPT 最少页数不能大于最多页数")
        return self


class AgentArtifactRequest(BaseModel):
    output_types: list[Literal["lesson_plan", "ppt", "classroom_activities"]] = Field(
        min_length=1,
        max_length=3,
    )
    ppt_preferences: PptPreferences | None = None


class PptSlideRevisionRequest(BaseModel):
    instruction: str = Field(min_length=2, max_length=500)
    mode: Literal["content", "design", "both"] = "both"


class PptVersionRestoreRequest(BaseModel):
    version_id: str = Field(min_length=1, max_length=80)


class PresentationTemplateData(BaseModel):
    id: int
    owner_id: int
    name: str
    description: str | None = None
    original_filename: str
    status: str
    is_shared: bool
    slide_count: int
    aspect_ratio: str
    theme_data: dict = Field(default_factory=dict)
    created_time: datetime
    updated_time: datetime


class AgentCapabilities(BaseModel):
    ppt_multimodal_available: bool
    ppt_multimodal_model: str | None = None
    ppt_multimodal_max_images: int = 0


class LessonPublishRequest(BaseModel):
    teaching_class_id: int
    title: str = Field(min_length=2, max_length=200)
    description: str = Field(default="", max_length=2000)
    publish_ppt: bool = True
    publish_discussions: bool = True
    discussion_indices: list[int] = Field(default_factory=list, max_length=20)
    confirmed: bool = False

    @model_validator(mode="after")
    def validate_publication(self):
        if not self.publish_ppt and not self.publish_discussions:
            raise ValueError("至少选择发布 PPT 或课堂讨论")
        if not self.confirmed:
            raise ValueError("发布前必须由教师完成最终确认")
        return self


class LessonPublicationData(BaseModel):
    id: int
    agent_run_id: int
    teaching_class_id: int
    teaching_class_name: str
    course_id: int
    chapter_id: int
    chapter_title: str
    created_by: int
    teacher_name: str
    title: str
    description: str
    ppt_available: bool
    ppt_file_name: str | None = None
    discussion_activity_ids: list[int] = Field(default_factory=list)
    status: str
    created_time: datetime


class AgentStepData(BaseModel):
    id: int
    step_key: str
    title: str
    step_order: int
    status: str
    output_data: dict = Field(default_factory=dict)
    error_message: str | None = None
    started_time: datetime | None = None
    finished_time: datetime | None = None


class AgentRunData(BaseModel):
    id: int
    created_by: int
    agent_type: str
    status: AgentStatus
    course_id: int | None
    chapter_id: int | None
    teaching_class_id: int | None
    current_step: int
    input_data: dict = Field(default_factory=dict)
    evidence_snapshot: list[AiSource] = Field(default_factory=list)
    output_data: dict = Field(default_factory=dict)
    model_name: str | None = None
    prompt_version: str
    error_message: str | None = None
    cancel_requested: bool
    retry_of_run_id: int | None = None
    started_time: datetime | None = None
    finished_time: datetime | None = None
    created_time: datetime
    updated_time: datetime
    steps: list[AgentStepData] = Field(default_factory=list)

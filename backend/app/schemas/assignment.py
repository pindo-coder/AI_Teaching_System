from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_serializer, field_validator, model_validator

from app.core.time import to_utc_naive, utc_iso


LearningStage = Literal["preview", "review", "exam"]
TaskKind = Literal["reading", "ai_assist", "note", "composite"]
RequirementEvent = Literal[
    "reading_progress",
    "ai_assist_used",
    "note_saved",
    "quiz_completed",
    "question_submitted",
    "activity_submitted",
    "discussion_created",
    "discussion_reply_created",
]


class AssignmentCompletionRequirement(BaseModel):
    key: str = Field(min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=2, max_length=80)
    event: RequirementEvent
    metric: Literal["percent", "count", "length"] = "count"
    target: int = Field(default=1, ge=1, le=30_000)
    weight: int = Field(default=100, ge=1, le=100)
    required: bool = True
    stage: Literal["assignment", "any", "preview", "review", "exam"] = "assignment"
    task_types: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: str) -> str:
        return value.strip()

    @field_validator("task_types")
    @classmethod
    def validate_task_types(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value if item.strip()]
        if any(len(item) > 50 for item in normalized):
            raise ValueError("AI 任务类型不能超过 50 个字符")
        return list(dict.fromkeys(normalized))


class AssignmentCompletionPolicy(BaseModel):
    mode: Literal["all_required"] = "all_required"
    items: list[AssignmentCompletionRequirement] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_items(self):
        keys = [item.key for item in self.items]
        if len(keys) != len(set(keys)):
            raise ValueError("完成条件标识不能重复")
        if sum(item.weight for item in self.items) != 100:
            raise ValueError("完成条件权重总和必须为 100%")
        if not any(item.required for item in self.items):
            raise ValueError("至少需要一个必选完成条件")
        return self


class AssignmentRequirementProgressRead(BaseModel):
    key: str
    label: str
    event: RequirementEvent
    current_value: int
    target_value: int
    progress_value: int
    status: Literal["not_started", "in_progress", "completed"]
    evidence_summary: str
    next_path: str


class AssignmentCreate(BaseModel):
    agent_execution_id: int | None = Field(default=None, ge=1)
    teaching_class_id: int | None = None
    course_id: int
    chapter_id: int
    learning_stage: LearningStage
    task_kind: TaskKind
    title: str = Field(min_length=2, max_length=160)
    description: str = Field(default="", max_length=3000)
    rubric: dict = Field(default_factory=dict)
    due_time: datetime
    target_scope: Literal["all_students", "selected_students", "selected_groups"] = "all_students"
    student_ids: list[int] = Field(default_factory=list)
    group_ids: list[int] = Field(default_factory=list)
    completion_policy: AssignmentCompletionPolicy | None = None

    @field_validator("due_time")
    @classmethod
    def normalize_due_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("截止时间必须包含 Z 或 UTC 偏移")
        return to_utc_naive(value)

    @model_validator(mode="after")
    def selected_students_required(self):
        if self.target_scope == "selected_students" and not self.student_ids:
            raise ValueError("指定学生发布时至少选择一名学生")
        if self.target_scope == "selected_groups" and not self.group_ids:
            raise ValueError("按小组发布时至少选择一个学习小组")
        return self


class AssignmentRubricConfirm(BaseModel):
    rubric: dict = Field(default_factory=dict)


class AssignmentCompletionPolicyUpdate(BaseModel):
    completion_policy: AssignmentCompletionPolicy


class AssignmentStudentItem(BaseModel):
    id: int
    username: str
    identity_no: str | None


class StudentAssignmentRead(BaseModel):
    id: int
    teaching_class_id: int | None
    course_id: int
    chapter_id: int
    course_name: str
    chapter_title: str
    learning_stage: LearningStage
    task_kind: TaskKind
    title: str
    description: str
    rubric: dict = Field(default_factory=dict)
    due_time: datetime
    status: str
    progress_value: int
    completed_time: datetime | None
    created_time: datetime
    teacher_name: str
    completion_policy: AssignmentCompletionPolicy | None = None
    requirements: list[AssignmentRequirementProgressRead] = Field(default_factory=list)
    next_path: str
    completion_status: Literal["not_started", "in_progress", "completed"]
    is_overdue: bool

    @field_serializer("due_time", when_used="json")
    def serialize_due_time(self, value: datetime) -> str:
        return utc_iso(value)

    @field_serializer("completed_time", when_used="json")
    def serialize_completed_time(self, value: datetime | None) -> str | None:
        return utc_iso(value) if value is not None else None


class TeacherAssignmentRead(BaseModel):
    id: int
    teaching_class_id: int | None
    course_id: int
    chapter_id: int
    course_name: str
    chapter_title: str
    learning_stage: LearningStage
    task_kind: TaskKind
    title: str
    description: str
    rubric: dict = Field(default_factory=dict)
    due_time: datetime
    status: str
    target_scope: str
    created_time: datetime
    total_count: int
    completed_count: int
    in_progress_count: int
    overdue_count: int
    completion_policy: AssignmentCompletionPolicy | None = None

    @field_serializer("due_time", when_used="json")
    def serialize_due_time(self, value: datetime) -> str:
        return utc_iso(value)


class AssignmentRecipientRead(BaseModel):
    user_id: int
    username: str
    identity_no: str | None
    group_name: str | None
    status: str
    progress_value: int
    completed_time: datetime | None
    last_activity_time: datetime | None
    completion_status: Literal["not_started", "in_progress", "completed"]
    is_overdue: bool
    requirements: list[AssignmentRequirementProgressRead] = Field(default_factory=list)

    @field_serializer("completed_time", when_used="json")
    def serialize_completed_time(self, value: datetime | None) -> str | None:
        return utc_iso(value) if value is not None else None

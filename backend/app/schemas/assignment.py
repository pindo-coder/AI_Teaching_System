from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_serializer, field_validator, model_validator

from app.core.time import to_utc_naive, utc_iso


LearningStage = Literal["preview", "review", "exam"]
TaskKind = Literal["reading", "ai_assist", "note"]


class AssignmentCreate(BaseModel):
    teaching_class_id: int | None = None
    course_id: int
    chapter_id: int
    learning_stage: LearningStage
    task_kind: TaskKind
    title: str = Field(min_length=2, max_length=160)
    description: str = Field(default="", max_length=3000)
    due_time: datetime
    target_scope: Literal["all_students", "selected_students", "selected_groups"] = "all_students"
    student_ids: list[int] = Field(default_factory=list)
    group_ids: list[int] = Field(default_factory=list)

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
    due_time: datetime
    status: str
    progress_value: int
    completed_time: datetime | None
    created_time: datetime
    teacher_name: str

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
    due_time: datetime
    status: str
    target_scope: str
    created_time: datetime
    total_count: int
    completed_count: int
    in_progress_count: int
    overdue_count: int

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

    @field_serializer("completed_time", when_used="json")
    def serialize_completed_time(self, value: datetime | None) -> str | None:
        return utc_iso(value) if value is not None else None

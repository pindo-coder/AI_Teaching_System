from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


LearningStage = Literal["preview", "review", "exam"]
TaskKind = Literal["reading", "ai_assist", "note"]


class AssignmentCreate(BaseModel):
    course_id: int
    chapter_id: int
    learning_stage: LearningStage
    task_kind: TaskKind
    title: str = Field(min_length=2, max_length=160)
    description: str = Field(default="", max_length=3000)
    due_time: datetime
    target_scope: Literal["all_students", "selected_students"] = "all_students"
    student_ids: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def selected_students_required(self):
        if self.target_scope == "selected_students" and not self.student_ids:
            raise ValueError("指定学生发布时至少选择一名学生")
        return self


class AssignmentStudentItem(BaseModel):
    id: int
    username: str
    identity_no: str | None


class StudentAssignmentRead(BaseModel):
    id: int
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


class TeacherAssignmentRead(BaseModel):
    id: int
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

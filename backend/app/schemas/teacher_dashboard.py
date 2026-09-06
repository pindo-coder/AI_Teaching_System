from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class TeacherDashboardMetrics(BaseModel):
    ongoing_tasks: int = 0
    average_completion_rate: float = 0
    active_students_today: int = 0
    active_rate_today: float = 0
    pending_materials: int = 0
    available_evidence: int = 0


class TeacherActivityPoint(BaseModel):
    date: date
    active_students: int = 0
    total_students: int = 0
    active_rate: float = 0


class TeacherTodo(BaseModel):
    kind: Literal["assignment", "material", "calibration", "join_request"]
    title: str
    description: str
    count: int = 1
    priority: Literal["urgent", "normal"] = "normal"
    href: str | None = None


class TeacherCourseRow(BaseModel):
    teaching_class_id: int
    class_name: str
    class_code: str
    course_id: int | None = None
    course_name: str = "未绑定教材"
    student_count: int = 0
    completion_rate: float = 0
    start_date: date | None = None
    end_date: date | None = None
    status: str


class TeacherDashboardData(BaseModel):
    period_start: date
    period_end: date
    metrics: TeacherDashboardMetrics
    activity_series: list[TeacherActivityPoint] = Field(default_factory=list)
    todos: list[TeacherTodo] = Field(default_factory=list)
    courses: list[TeacherCourseRow] = Field(default_factory=list)

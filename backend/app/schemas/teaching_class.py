from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class SubjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    code: str | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, max_length=2000)


class TermCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    start_date: date
    end_date: date
    is_current: bool = False

    @model_validator(mode="after")
    def valid_dates(self):
        if self.end_date < self.start_date:
            raise ValueError("学期结束日期不能早于开始日期")
        return self


class TeachingClassCreate(BaseModel):
    subject_id: int
    term_id: int
    name: str = Field(min_length=2, max_length=160)
    code: str = Field(min_length=2, max_length=32)
    description: str | None = Field(default=None, max_length=2000)
    primary_course_id: int
    supplementary_course_ids: list[int] = Field(default_factory=list)


class TeachingClassRead(BaseModel):
    id: int
    subject_id: int
    subject_name: str
    term_id: int
    term_name: str
    name: str
    code: str
    status: str
    join_code: str
    join_code_enabled: bool
    description: str | None
    is_default: bool
    teacher_role: str | None = None
    membership_status: str | None = None
    primary_course_id: int | None = None
    material_ids: list[int] = Field(default_factory=list)
    student_count: int = 0


class JoinClassRequest(BaseModel):
    join_code: str = Field(min_length=4, max_length=16)


class JoinClassResult(BaseModel):
    status: Literal["joined", "pending", "transferred", "already_joined"]
    teaching_class_id: int
    message: str


class ClassStatusUpdate(BaseModel):
    status: Literal["not_started", "active", "completed", "archived"]


class ClassTeacherAdd(BaseModel):
    user_id: int


class ClassMaterialAdd(BaseModel):
    course_id: int
    material_role: Literal["primary", "supplementary"] = "supplementary"


class ClassGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    user_ids: list[int] = Field(default_factory=list)


class RandomGroupCreate(BaseModel):
    group_count: int = Field(ge=2, le=30)
    name_prefix: str = Field(default="第", max_length=30)


class JoinCodeUpdate(BaseModel):
    enabled: bool | None = None
    regenerate: bool = False


class ClassGroupRead(BaseModel):
    id: int
    name: str
    sort_order: int
    user_ids: list[int]


class JoinRequestReview(BaseModel):
    approved: bool
    note: str = Field(default="", max_length=500)


class RosterImportResult(BaseModel):
    total: int
    created: int
    updated: int
    bound: int
    conflicted: int

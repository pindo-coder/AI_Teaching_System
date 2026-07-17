from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_\-\u4e00-\u9fff]+$")
    password: str = Field(min_length=8, max_length=128)
    role: Literal["student", "teacher"] = "student"
    identity_no: str = Field(min_length=4, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")

    @field_validator("username")
    @classmethod
    def username_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("用户名不能为空")
        return value.strip()

    @field_validator("identity_no")
    @classmethod
    def identity_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("学号或工号不能为空")
        return value.strip().upper()


class UserLogin(BaseModel):
    username: str
    password: str


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: str
    approval_status: str
    approval_note: str | None
    identity_no: str | None
    created_time: datetime


class TeacherApprovalUpdate(BaseModel):
    status: Literal["approved", "rejected", "disabled"]
    note: str = Field(default="", max_length=500)


class TokenData(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead

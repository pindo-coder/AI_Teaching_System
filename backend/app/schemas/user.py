from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_\-\u4e00-\u9fff]+$")
    password: str = Field(min_length=8, max_length=128)
    role: Literal["student", "teacher"] = "student"
    identity_no: str = Field(min_length=4, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    email: str | None = Field(default=None, max_length=254)

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

    @field_validator("email")
    @classmethod
    def email_must_be_valid(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized or "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("请输入有效邮箱")
        return normalized


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
    email: str | None
    email_verified_at: datetime | None
    must_change_password: bool
    created_time: datetime


class PasswordResetRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=254)


class PasswordResetConfirm(BaseModel):
    token: str | None = Field(default=None, min_length=20, max_length=256)
    identifier: str | None = Field(default=None, min_length=1, max_length=254)
    code: str | None = Field(default=None, min_length=6, max_length=6, pattern=r"^\d{6}$")
    new_password: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def reset_method_must_be_provided(self) -> "PasswordResetConfirm":
        if self.token or (self.identifier and self.code):
            return self
        raise ValueError("请提供重置验证码和用户名/邮箱")


class PasswordChange(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)


class EmailVerificationRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class EmailVerificationConfirm(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class AdminTemporaryPasswordRead(BaseModel):
    user_id: int
    temporary_password: str
    must_change_password: bool = True


class PasswordResetRequestRead(BaseModel):
    id: int
    user_id: int
    username: str
    email: str | None
    requested_at: datetime
    request_ip: str | None


class PasswordResetRequestResult(BaseModel):
    next_step: Literal["email", "verify_email", "admin"]


class TeacherApprovalUpdate(BaseModel):
    status: Literal["approved", "rejected", "disabled"]
    note: str = Field(default="", max_length=500)


class TokenData(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.learning_progress import LearningProgress


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('student', 'teacher', 'admin')", name="ck_user_role"),
        CheckConstraint(
            "approval_status IN ('pending', 'approved', 'rejected', 'disabled')",
            name="ck_user_approval_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    identity_no: Mapped[str | None] = mapped_column(String(32), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    email_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime)
    auth_version: Mapped[int] = mapped_column(default=0, nullable=False)
    must_change_password: Mapped[bool] = mapped_column(default=False, nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="student", nullable=False)
    approval_status: Mapped[str] = mapped_column(String(20), default="approved", nullable=False, index=True)
    approval_note: Mapped[str | None] = mapped_column(String(500))
    approved_time: Mapped[datetime | None] = mapped_column(DateTime)
    approved_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    learning_progress: Mapped[list["LearningProgress"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

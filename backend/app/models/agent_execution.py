"""持久化工作台 Agent 的规划、执行与恢复状态。

`AgentRun` 继续只承载耗时的备课成果工作流；本表记录所有工作台 Agent
任务，使资料检索、学习规划、任务草案等轻量任务也能在刷新页面后追踪、复盘
或重试，而不是只存在于一次 SSE 连接中。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin


class AgentExecution(TimestampMixin, Base):
    __tablename__ = "agent_executions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="planning", index=True)
    intent: Mapped[str] = mapped_column(String(80), nullable=False, default="guided_question", index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id", ondelete="SET NULL"), index=True)
    chapter_id: Mapped[int | None] = mapped_column(ForeignKey("chapters.id", ondelete="SET NULL"), index=True)
    teaching_class_id: Mapped[int | None] = mapped_column(
        ForeignKey("teaching_classes.id", ondelete="SET NULL"), index=True
    )
    context_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    plan: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    tool_results: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    result: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    retry_of_execution_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_executions.id", ondelete="SET NULL"), index=True
    )
    started_time: Mapped[datetime | None] = mapped_column(DateTime)
    finished_time: Mapped[datetime | None] = mapped_column(DateTime)

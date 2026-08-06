"""工作台规划型 Agent 的持久化执行记录服务。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.models.agent_execution import AgentExecution
from app.models.user import User
from app.schemas.ai import AiWorkspaceContextData


FINAL_STATUSES = {"completed", "failed", "cancelled"}


class AgentExecutionService:
    def __init__(self, db: Session, user: User) -> None:
        self.db = db
        self.user = user

    def create(
        self,
        *,
        role: str,
        intent: str,
        question: str,
        context: AiWorkspaceContextData,
        retry_of_execution_id: int | None = None,
        retry_count: int = 0,
    ) -> AgentExecution:
        execution = AgentExecution(
            user_id=self.user.id,
            role=role,
            intent=intent,
            question=question,
            course_id=context.course_id,
            chapter_id=context.chapter_id,
            teaching_class_id=context.teaching_class_id,
            context_snapshot=context.model_dump(mode="json"),
            status="planning",
            retry_of_execution_id=retry_of_execution_id,
            retry_count=retry_count,
            started_time=datetime.now(UTC),
        )
        self.db.add(execution)
        self.db.commit()
        self.db.refresh(execution)
        return execution

    def update(self, execution: AgentExecution, **fields: Any) -> AgentExecution:
        for key, value in fields.items():
            setattr(execution, key, value)
        self.db.add(execution)
        self.db.commit()
        self.db.refresh(execution)
        return execution

    def set_plan(self, execution: AgentExecution, plan: dict[str, Any]) -> AgentExecution:
        return self.update(execution, plan=plan, status="running", error_message=None)

    def append_tool_result(self, execution: AgentExecution, result: dict[str, Any]) -> AgentExecution:
        history = [*list(execution.tool_results or []), result]
        return self.update(execution, tool_results=history)

    def complete(self, execution: AgentExecution, result: dict[str, Any]) -> AgentExecution:
        return self.update(execution, status="completed", result=result, finished_time=datetime.now(UTC))

    def wait_for_confirmation(self, execution: AgentExecution, result: dict[str, Any]) -> AgentExecution:
        return self.update(
            execution,
            status="waiting_confirmation",
            result=result,
            error_message=None,
            finished_time=None,
        )

    def resolve(self, execution: AgentExecution, *, resolution: str, note: str | None = None) -> AgentExecution:
        result = dict(execution.result or {})
        result["confirmation"] = {
            "resolution": resolution,
            "note": note or "",
            "resolved_time": datetime.now(UTC).isoformat(),
        }
        if resolution == "cancelled":
            return self.update(
                execution,
                status="cancelled",
                result=result,
                finished_time=datetime.now(UTC),
            )
        return self.complete(execution, result)

    def fail(self, execution: AgentExecution, message: str, result: dict[str, Any] | None = None) -> AgentExecution:
        return self.update(
            execution,
            status="failed",
            error_message=message[:4000],
            result=result or execution.result or {},
            finished_time=datetime.now(UTC),
        )

    def get(self, execution_id: int) -> AgentExecution | None:
        return self.db.scalar(
            select(AgentExecution).where(
                AgentExecution.id == execution_id,
                AgentExecution.user_id == self.user.id,
            )
        )

    def list_recent(self, limit: int = 12) -> list[AgentExecution]:
        return list(self.db.scalars(
            select(AgentExecution)
            .where(AgentExecution.user_id == self.user.id)
            .order_by(AgentExecution.updated_time.desc(), AgentExecution.id.desc())
            .limit(limit)
        ).all())

    def retry(self, source: AgentExecution) -> AgentExecution:
        context = AiWorkspaceContextData.model_validate(source.context_snapshot or {})
        return self.create(
            role=source.role,
            intent=source.intent,
            question=source.question,
            context=context,
            retry_of_execution_id=source.id,
            retry_count=source.retry_count + 1,
        )


def execution_data(execution: AgentExecution) -> dict[str, Any]:
    """统一输出契约，前端无需理解数据库字段。"""
    return {
        "id": execution.id,
        "role": execution.role,
        "status": execution.status,
        "intent": execution.intent,
        "question": execution.question,
        "course_id": execution.course_id,
        "chapter_id": execution.chapter_id,
        "teaching_class_id": execution.teaching_class_id,
        "context": execution.context_snapshot or {},
        "plan": execution.plan or {},
        "tool_results": execution.tool_results or [],
        "result": execution.result or {},
        "error_message": execution.error_message,
        "retry_count": execution.retry_count,
        "retry_of_execution_id": execution.retry_of_execution_id,
        "created_time": execution.created_time.isoformat() if execution.created_time else None,
        "updated_time": execution.updated_time.isoformat() if execution.updated_time else None,
        "finished_time": execution.finished_time.isoformat() if execution.finished_time else None,
    }


def recover_agent_executions(bind: Engine) -> int:
    """服务重启后将中断中的工作台任务标为可重试，避免任务中心永久转圈。"""
    with Session(bind=bind, autoflush=False, expire_on_commit=False) as db:
        pending = db.scalars(
            select(AgentExecution).where(AgentExecution.status.in_(["planning", "running"]))
        ).all()
        if not pending:
            return 0
        now = datetime.now(UTC)
        for execution in pending:
            execution.status = "failed"
            execution.error_message = "服务重启导致任务中断，请在任务中心基于此任务重试"
            execution.finished_time = now
        db.commit()
        return len(pending)

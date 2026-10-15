"""工作台规划型 Agent 的持久化执行记录服务。"""

from __future__ import annotations

from typing import Any
import hashlib

from fastapi import HTTPException

from sqlalchemy import Engine, delete, select, update
from sqlalchemy.orm import Session

from app.core.time import utc_iso, utc_now
from app.models.agent_execution import AgentExecution
from app.models.user import User
from app.schemas.ai import AiWorkspaceContextData
from app.services.llm_compat import clean_model_text


FINAL_STATUSES = {"completed", "advice_ready", "waiting_user_action", "failed", "cancelled"}


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
            started_time=utc_now(),
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

    def validate_handoff(self, execution_id: int | None, *, kind: str, course_id: int,
                         chapter_id: int, content: str = "", rubric: dict | None = None,
                         teaching_class_id: int | None = None) -> AgentExecution | None:
        if execution_id is None:
            return None
        # Claim with a conditional write, not a check followed by a write. MySQL
        # row locks and SQLite's writer lock serialize competing submissions.
        # "saving" is transaction-local: callers must commit the business record
        # and finish_handoff together, or roll both back on any failure.
        claimed = self.db.execute(
            update(AgentExecution).where(
                AgentExecution.id == execution_id,
                AgentExecution.user_id == self.user.id,
                AgentExecution.status == "waiting_user_action",
            ).values(status="saving").execution_options(synchronize_session=False)
        )
        if claimed.rowcount != 1:
            self.db.rollback()
            if self.get(execution_id) is None:
                raise HTTPException(404, "关联 Agent 任务不存在")
            raise HTTPException(409, "该草案已保存或正在处理，请核对任务结果，勿重复提交")
        execution = self.db.scalar(select(AgentExecution).where(
            AgentExecution.id == execution_id,
        ).execution_options(populate_existing=True))
        assert execution is not None
        return self._validate_claimed_handoff(execution, kind=kind, course_id=course_id,
                                             chapter_id=chapter_id, content=content, rubric=rubric,
                                             teaching_class_id=teaching_class_id)

    def _validate_claimed_handoff(self, execution: AgentExecution, *, kind: str, course_id: int,
                                  chapter_id: int, content: str, rubric: dict | None,
                                  teaching_class_id: int | None) -> AgentExecution:
        if execution.course_id != course_id or execution.chapter_id != chapter_id:
            raise HTTPException(400, "保存范围与 Agent 草案不一致")
        expected = "draft_note_improvement" if kind == "note" else "draft_assignment"
        tool = next((item for item in reversed(execution.tool_results or [])
                     if item.get("tool") == expected and item.get("status") in {"advice_ready", "waiting_user_action"}), None)
        if tool is None:
            raise HTTPException(400, "Agent 未生成对应业务草案")
        if kind == "note":
            from app.services.study_service import StudyService
            plain = StudyService.plain_note_content(content)
            baseline = (tool.get("data") or {}).get("baseline_hash")
            if not plain.strip() or hashlib.sha256(plain.encode()).hexdigest() == baseline:
                raise HTTPException(400, "请审阅并修改笔记后再保存 Agent 草案")
        else:
            if execution.teaching_class_id is not None and execution.teaching_class_id != teaching_class_id:
                raise HTTPException(400, "发布教学班与 Agent 草案不一致")
            goals = (execution.result or {}).get("goals", [])
            if any(item.get("key") == "goal_rubric" for item in goals):
                items = (rubric or {}).get("items", [])
                if not items or sum(float(item.get("weight", 0)) for item in items) != 100:
                    raise HTTPException(400, "任务要求评分量规，请确认各项权重合计为 100%")
        return execution

    def finish_handoff(self, execution: AgentExecution | None, *, kind: str, resource_id: int) -> None:
        """Stage completion in the caller's transaction; never commit independently."""
        if execution is None:
            return
        result = dict(execution.result or {})
        saved_keys = {"goal_note"} if kind == "note" else {"goal_assignment", "goal_rubric"}
        goals = [dict(item) for item in result.get("goals", [])]
        for goal in goals:
            if goal.get("key") in saved_keys:
                goal.update(status="completed", resource_id=resource_id)
        result["goals"] = goals
        result["saved_resources"] = [*result.get("saved_resources", []), {"kind": kind, "id": resource_id}]
        summary = result.get("summary", "")
        if kind == "note":
            summary = summary.replace("草稿尚未保存，请在笔记空间审阅后追加。",
                                      "草稿已审阅处理，实际保存内容以笔记空间为准。")
        result["summary"] = summary + ("\n\n笔记修改已保存。" if kind == "note" else "\n\n任务与量规已确认并发布。")
        if all(item.get("status") == "completed" for item in goals):
            result["actions"] = []
            result["next_actions"] = []
            execution.status = "completed"
            execution.finished_time = utc_now()
        else:
            execution.status = "waiting_user_action"
            execution.finished_time = None
        execution.result = result
        execution.error_message = None
        self.db.add(execution)
        self.db.flush()

    def complete(self, execution: AgentExecution, result: dict[str, Any]) -> AgentExecution:
        return self.update(execution, status="completed", result=result, finished_time=utc_now())

    def wait_for_confirmation(self, execution: AgentExecution, result: dict[str, Any]) -> AgentExecution:
        return self.update(
            execution,
            status="waiting_confirmation",
            result=result,
            error_message=None,
            finished_time=None,
        )

    def wait_for_input(self, execution: AgentExecution, result: dict[str, Any]) -> AgentExecution:
        """暂停在需要用户补充上下文/参数的位置，可由同一 execution 继续。"""
        return self.update(
            execution,
            status="waiting_input",
            result=result,
            error_message=None,
            finished_time=None,
        )

    def advice_ready(self, execution: AgentExecution, result: dict[str, Any]) -> AgentExecution:
        """已生成建议/草案，但仍需用户在业务页面编辑或保存。"""
        return self.update(
            execution,
            status="waiting_user_action",
            result=result,
            error_message=None,
            finished_time=None,
        )

    def request_cancel(self, execution: AgentExecution) -> AgentExecution:
        if execution.status in FINAL_STATUSES:
            return execution
        return self.update(execution, cancel_requested=True, status="cancelled", finished_time=utc_now())

    def resolve(self, execution: AgentExecution, *, resolution: str, note: str | None = None) -> AgentExecution:
        result = dict(execution.result or {})
        result["confirmation"] = {
            "resolution": resolution,
            "note": note or "",
            "resolved_time": utc_iso(utc_now()),
        }
        if resolution == "cancelled":
            return self.update(
                execution,
                status="cancelled",
                result=result,
                finished_time=utc_now(),
            )
        return self.complete(execution, result)

    def fail(self, execution: AgentExecution, message: str, result: dict[str, Any] | None = None) -> AgentExecution:
        return self.update(
            execution,
            status="failed",
            error_message=message[:4000],
            result=result or execution.result or {},
            finished_time=utc_now(),
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

    def delete(self, execution: AgentExecution) -> None:
        """删除当前用户的一条 Agent 执行记录。"""
        self.db.delete(execution)
        self.db.commit()

    def clear(self) -> int:
        """删除当前用户的全部 Agent 执行记录并返回删除数量。"""
        result = self.db.execute(
            delete(AgentExecution).where(AgentExecution.user_id == self.user.id)
        )
        self.db.commit()
        return max(int(result.rowcount or 0), 0)

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
    result = dict(execution.result or {})
    if result.get("summary"):
        result["summary"] = clean_model_text(result["summary"])
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
        "result": result,
        "error_message": execution.error_message,
        "retry_count": execution.retry_count,
        "cancel_requested": bool(execution.cancel_requested),
        "retry_of_execution_id": execution.retry_of_execution_id,
        # TimestampMixin uses database func.now(); historical deployments did
        # not record that session timezone, so do not invent a UTC basis here.
        "created_time": execution.created_time.isoformat() if execution.created_time else None,
        "updated_time": execution.updated_time.isoformat() if execution.updated_time else None,
        "finished_time": utc_iso(execution.finished_time) if execution.finished_time else None,
    }


def recover_agent_executions(bind: Engine) -> int:
    """服务重启后将中断中的工作台任务标为可重试，避免任务中心永久转圈。"""
    with Session(bind=bind, autoflush=False, expire_on_commit=False) as db:
        pending = db.scalars(
            select(AgentExecution).where(AgentExecution.status.in_(["planning", "running"]))
        ).all()
        if not pending:
            return 0
        now = utc_now()
        for execution in pending:
            execution.status = "failed"
            execution.error_message = "服务重启导致任务中断，请在任务中心基于此任务重试"
            execution.finished_time = now
        db.commit()
        return len(pending)

"""V2 工作台 Agent Runtime：单步决策、执行、校验并按结果重规划。"""

from __future__ import annotations

from typing import Any, Iterator
import signal
import threading
import time

from pydantic import BaseModel, Field

from app.core.config import settings
from app.schemas.ai import AiWorkspaceContextData
from app.services.agent_execution_service import AgentExecutionService, execution_data
from app.services.agent_tool_registry import TOOL_REGISTRY, allowed_tools, invoke_registered_tool
from app.services.agent_verifier import AgentVerifier
from app.services.planning_agent import PlanningAgent, ToolCall, ToolResult


RuntimeEvent = tuple[str, Any]


class AgentDecision(BaseModel):
    """单轮 Planner 决策的内部结构，避免执行层依赖自然语言或裸字典。"""

    kind: str = "tool"
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    reason: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


def decision_from_call(call: ToolCall) -> AgentDecision:
    return AgentDecision(
        tool_name=call.name,
        reason=call.reason,
        arguments=call.arguments,
        confidence=1.0,
    )


class AgentRuntime:
    """不直接访问业务数据库，只负责编排已注册工具。"""

    def __init__(self, db: Any, user: Any) -> None:
        self.db = db
        self.user = user

    def _invoke_with_reliability(
        self,
        planner: PlanningAgent,
        *,
        call: ToolCall,
        question: str,
        role: str,
        context: AiWorkspaceContextData,
    ) -> ToolResult:
        """在 SSE 主线程内提供可中断超时，避免线程共享 SQLAlchemy Session。"""
        def timeout_handler(_signum: int, _frame: Any) -> None:
            raise TimeoutError(f"工具执行超过 {settings.agent_tool_timeout_seconds:g} 秒")

        if threading.current_thread() is not threading.main_thread():
            return invoke_registered_tool(
                planner,
                name=call.name,
                reason=call.reason,
                arguments=call.arguments,
                question=question,
                role=role,
                context=context,
            )
        previous = signal.getsignal(signal.SIGALRM)
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.setitimer(signal.ITIMER_REAL, settings.agent_tool_timeout_seconds)
        try:
            return invoke_registered_tool(
                planner,
                name=call.name,
                reason=call.reason,
                arguments=call.arguments,
                question=question,
                role=role,
                context=context,
            )
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)

    @staticmethod
    def _next_candidate(
        candidates: list[ToolCall],
        completed: set[str],
        role: str,
    ) -> ToolCall | None:
        for call in candidates:
            if call.name in completed:
                continue
            spec = TOOL_REGISTRY.get(call.name)
            if spec is not None and role in spec.allowed_roles:
                return call
        return None

    @staticmethod
    def _merge_replanned_candidates(
        previous: list[ToolCall],
        replanned: list[ToolCall],
        completed: set[str],
        permitted: set[str],
    ) -> list[ToolCall]:
        """保留原计划未执行步骤，同时允许模型调整或追加后续工具。"""
        selected: list[ToolCall] = []
        selected_names: set[str] = set()
        for call in replanned:
            if call.name not in permitted or call.name in completed or call.name in selected_names:
                continue
            selected.append(call)
            selected_names.add(call.name)
        for call in previous:
            if call.name not in permitted or call.name in completed or call.name in selected_names:
                continue
            selected.append(call)
            selected_names.add(call.name)
        return selected

    def _replan(
        self,
        planner: PlanningAgent,
        *,
        question: str,
        role: str,
        context: AiWorkspaceContextData,
        results: list[tuple[ToolCall, ToolResult]],
        fallback: list[ToolCall],
    ) -> list[ToolCall]:
        """每轮优先让模型观察已完成结果；不可用时回退剩余安全计划。"""
        if settings.agent_planner_use_llm and not settings.ai_mock_mode:
            history = "\n".join(
                f"{call.name}: {result.status} - {result.text[:500]}"
                for call, result in results[-6:]
            )
            calls = planner._llm_plan(
                f"{question}\n已执行结果（只能据此选择下一步，不要重复已完成工具）：\n{history}",
                role,
                context,
            )
            if calls:
                return calls
        return fallback

    def stream(
        self,
        *,
        question: str,
        role: str,
        context: AiWorkspaceContextData,
        execution: Any,
        execution_service: AgentExecutionService,
    ) -> Iterator[RuntimeEvent]:
        planner = PlanningAgent(self.db, self.user)
        try:
            candidates = planner.plan(question, role, context)
        except Exception as exc:
            candidates = planner._deterministic_plan(question, role)
            fallback_title = "规则化治理检查" if role == "admin" else "规则化任务计划"
            yield "progress", {"title": f"智能规划暂不可用，已切换为{fallback_title}：{exc}", "status": "blocked"}

        permitted = allowed_tools(role)
        candidates = [call for call in candidates if call.name in permitted]
        plan_tools = list(dict.fromkeys(call.name for call in candidates))
        decisions = [decision_from_call(call) for call in candidates]
        plan_title = "平台治理检查计划" if role == "admin" else "动态任务执行计划（自主任务执行计划）"
        steps = [
            {"key": f"{index}-{decision.tool_name}", "title": decision.reason, "status": "pending"}
            for index, decision in enumerate(decisions)
        ]
        persisted_results = list(execution.tool_results or [])
        persisted_success = {
            str(item.get("tool")) for item in persisted_results
            if item.get("status") in {"completed", "advice_ready", "waiting_user_action"}
        }
        for step in steps:
            if step["key"].rsplit("-", 1)[-1] in persisted_success:
                step["status"] = "completed"
        plan = {"intent": "planner_v2", "title": plan_title, "steps": steps, "tools": plan_tools, "iteration": 0}
        execution_service.set_plan(execution, plan)
        yield "plan", plan

        results: list[tuple[ToolCall, ToolResult]] = []
        # execution_id 续跑时沿用已持久化的成功步骤，避免重复副作用。
        completed: set[str] = {
            str(item.get("tool")) for item in persisted_results
            if item.get("status") in {"completed", "advice_ready", "waiting_user_action"}
        }
        started_at = time.monotonic()
        deadline_exceeded = False
        for iteration in range(settings.agent_runtime_max_iterations):
            try:
                self.db.refresh(execution)
            except Exception:
                pass
            if execution.cancel_requested:
                yield "progress", {"title": "任务已停止", "status": "cancelled"}
                break
            if time.monotonic() - started_at > settings.agent_execution_deadline_seconds:
                deadline_exceeded = True
                yield "progress", {"title": "执行超过整体时限", "status": "failed"}
                break
            call = self._next_candidate(candidates, completed, role)
            if call is None:
                break
            index = next(i for i, item in enumerate(steps) if item["key"].endswith(f"-{call.name}") and item["status"] == "pending")
            steps[index]["status"] = "running"
            execution_service.update(execution, plan=plan)
            yield "plan", plan
            yield "tool", {"name": call.name, "title": call.reason, "status": "running", "requires_confirmation": call.requires_confirmation}
            result: ToolResult | None = None
            attempts = 0
            while attempts <= settings.agent_tool_max_retries:
                attempts += 1
                try:
                    result = self._invoke_with_reliability(
                        planner, call=call, question=question, role=role, context=context,
                    )
                except TimeoutError as exc:
                    result = ToolResult(str(exc), status="failed", warnings=[str(exc)], retryable=True)
                except Exception as exc:
                    result = ToolResult(f"工具“{call.reason}”执行失败：{exc}", status="failed", warnings=[str(exc)], retryable=True)
                if result.status != "failed" or not result.retryable or attempts > settings.agent_tool_max_retries:
                    break
            assert result is not None
            results.append((call, result))
            tool_contract = result.contract(call)
            tool_contract["tool_call_id"] = f"{execution.id}:{call.name}"
            tool_contract["attempt"] = attempts
            execution_service.append_tool_result(execution, tool_contract)
            steps[index]["status"] = result.status if result.status in {"failed", "needs_input", "waiting_confirmation", "advice_ready", "waiting_user_action"} else "completed"
            if result.status not in {"failed", "needs_input", "waiting_confirmation"}:
                completed.add(call.name)
            yield "tool", {
                "name": call.name,
                "title": call.reason,
                "status": result.status,
                "data": result.data or {},
                "warnings": result.warnings or [],
                "retryable": result.retryable,
            }
            if result.action:
                yield "action", result.action
            plan = {
                "intent": "planner_v2",
                "title": plan_title,
                "steps": steps,
                "tools": plan_tools,
                "iteration": iteration + 1,
            }
            execution_service.update(execution, plan=plan)
            yield "plan", plan
            if result.status in {"failed", "needs_input", "waiting_confirmation"}:
                break
            yield "progress", {
                "title": f"已完成“{call.reason}”，正在根据结果调整下一步",
                "status": "replanning",
                "iteration": iteration + 1,
            }
            previous_candidates = candidates
            replanned = self._replan(
                planner,
                question=question,
                role=role,
                context=context,
                results=results,
                fallback=previous_candidates,
            )
            candidates = self._merge_replanned_candidates(
                previous_candidates,
                replanned,
                completed,
                permitted,
            )
            decisions = [decision_from_call(call) for call in candidates]
            # LLM 可以根据中间结果追加新工具；计划卡片同步扩展，而不是把新步骤藏在执行记录之外。
            known_keys = {item["key"] for item in steps}
            known_names = {item["key"].split("-", 1)[-1] for item in steps}
            for call in candidates:
                key = f"{len(steps)}-{call.name}"
                if call.name not in plan_tools:
                    plan_tools.append(call.name)
                if key not in known_keys and call.name not in completed and call.name not in known_names:
                    steps.append({"key": key, "title": call.reason, "status": "pending"})
                    known_keys.add(key)
                    known_names.add(call.name)
            plan = {
                "intent": "planner_v2",
                "title": plan_title,
                "steps": steps,
                "tools": plan_tools,
                "iteration": iteration + 1,
            }
            execution_service.update(execution, plan=plan)
            yield "plan", plan
            if iteration + 1 >= settings.agent_runtime_max_iterations:
                break

        yield "progress", {"title": "正在整理执行结果和下一步操作", "status": "running"}
        summary_parts = list(planner.synthesize_stream(question=question, role=role, context=context, results=results))
        summary = "".join(summary_parts)
        verification = AgentVerifier().verify(context=context, results=results, summary=summary, role=role)
        actions = [result.action for _, result in results if result.action]
        final_result = {
            "summary": summary,
            "actions": actions,
            "next_actions": actions,
            "warnings": verification.warnings,
            "verified": verification.verified,
            "verification": {"checks": verification.checks},
            "blocking_actions": verification.blocking_actions,
        }
        pending_steps = [
            step for step in steps
            if step["status"] in {"pending", "running"}
        ]
        if pending_steps:
            pending_titles = "、".join(step["title"] for step in pending_steps[:4])
            pending_warning = f"仍有 {len(pending_steps)} 个计划步骤未执行：{pending_titles}。"
            final_result["warnings"] = [*final_result["warnings"], pending_warning]
            final_result["verified"] = False
        if execution.cancel_requested:
            execution_service.request_cancel(execution)
        elif deadline_exceeded:
            execution_service.fail(execution, "Agent 执行超过整体时限，请稍后重试", final_result)
        elif verification.status == "waiting_confirmation":
            execution_service.wait_for_confirmation(execution, final_result)
        elif verification.status == "waiting_input":
            execution_service.wait_for_input(execution, final_result)
        elif verification.status == "waiting_user_action":
            execution_service.advice_ready(execution, final_result)
        elif any(result.status == "failed" for _, result in results):
            execution_service.fail(execution, "一个或多个 Agent 工具执行失败", final_result)
        elif pending_steps:
            execution_service.fail(execution, "Agent 计划未完整执行", final_result)
        else:
            execution_service.complete(execution, final_result)
        yield "chunk", {"text": summary}
        yield "execution", execution_data(execution)
        yield "progress", {
            "title": (
                "计划已执行，等待你补充信息" if execution.status == "waiting_input"
                else "计划已执行，等待你确认下一步" if execution.status == "waiting_confirmation"
                else "计划执行出现异常，请查看未完成步骤" if execution.status == "failed"
                else "计划执行完成，可按提示继续"
            ),
            "status": "failed" if execution.status == "failed" else "needs_input" if execution.status in {"waiting_input", "waiting_confirmation"} else "completed",
        }
        yield "sources", []
        yield "done", {}

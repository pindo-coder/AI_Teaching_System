"""规划型 Agent 的确定性结果校验。

校验器不让大模型自行判断“是否完成”，而是根据工具契约、教学范围和待确认
动作给出可审计结论。这样模型即使输出自然语言“已完成”，系统状态仍以真实
工具结果为准。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.schemas.ai import AiWorkspaceContextData
from app.services.planning_agent import ToolCall, ToolResult


@dataclass(frozen=True)
class VerificationResult:
    verified: bool
    status: str
    checks: list[dict[str, Any]]
    warnings: list[str]
    blocking_actions: list[dict[str, Any]]


class AgentVerifier:
    """对工具执行结果做规则校验，不产生新的业务写操作。"""

    CONTEXT_REQUIRED_TOOLS = {
        "search_materials", "create_lesson_draft", "draft_assignment",
        "draft_study_plan", "prepare_grading_rubric", "check_lesson_readiness",
        "generate_lesson_outline", "generate_ppt", "generate_lesson_plan",
        "generate_classroom_activity", "generate_all_artifacts",
    }
    BLOCKING_ACTION_KINDS = {"approve_evidence"}

    def verify(
        self,
        *,
        context: AiWorkspaceContextData,
        results: list[tuple[ToolCall, ToolResult]],
        summary: str,
        role: str = "student",
    ) -> VerificationResult:
        checks: list[dict[str, Any]] = []
        warnings: list[str] = []

        checks.append({
            "key": "has_result",
            "label": "已产生可读执行结果",
            "passed": bool(summary.strip()),
        })
        failed = [(call, result) for call, result in results if result.status == "failed"]
        checks.append({
            "key": "tools_succeeded",
            "label": "所有计划工具执行成功",
            "passed": not failed,
            "detail": f"{len(failed)} 个工具存在异常" if failed else "工具结果完整",
        })
        for _, result in failed:
            warnings.extend(result.warnings or [result.text])

        needs_context = any(call.name in self.CONTEXT_REQUIRED_TOOLS for call, _ in results)
        context_ok = not needs_context or bool(context.course_id and context.chapter_id)
        checks.append({
            "key": "context_grounded",
            "label": "平台治理范围可验证" if role == "admin" else "教材与专题范围可验证",
            "passed": context_ok,
        })
        if not context_ok:
            warnings.append("当前任务需要教材专题，但尚未锁定可验证范围")

        actions = [result.action for _, result in results if result.action]
        blocking_actions = [
            action for action in actions
            if action and action.get("kind") in self.BLOCKING_ACTION_KINDS
        ]
        checks.append({
            "key": "side_effect_guard",
            "label": "发布、确认等操作保留人工决策",
            "passed": True,
            "detail": f"{len(blocking_actions)} 项等待用户确认" if blocking_actions else "没有待确认写操作",
        })

        verified = bool(summary.strip()) and not failed and context_ok
        status = "waiting_confirmation" if blocking_actions else "completed"
        return VerificationResult(verified, status, checks, list(dict.fromkeys(warnings)), blocking_actions)

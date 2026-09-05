"""声明式 Agent 工具注册表。

工具的权限、副作用和上下文要求集中在这里声明；具体业务逻辑仍复用
PlanningAgent.invoke，避免在迁移期间复制一套数据库操作。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from app.services.planning_agent import PlanningAgent, ToolCall, ToolResult


SideEffect = Literal["read", "draft", "write"]


class EmptyToolArgs(BaseModel):
    """工具主要由已授权上下文驱动；允许 Planner 附带上下文元数据。"""

    course_id: int | None = None
    chapter_id: int | None = None
    chapter_ids: list[int] | None = None
    teaching_class_id: int | None = None
    learning_stage: str | None = None

    model_config = {"extra": "forbid"}


def _normalize_tool_arguments(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Keep model-added metadata from breaking context-driven tools.

    ``draft_study_plan`` gets all of its facts from the authenticated user and
    the resolved workspace context. Some compatible models still emit fields
    such as ``goal`` or ``context`` in the tool call even though the tool has no
    user-supplied parameters. Discard only those fields here; direct calls to
    every other registered tool remain protected by ``extra='forbid'``.
    """
    if name != "draft_study_plan":
        return arguments
    allowed = set(EmptyToolArgs.model_fields)
    return {key: value for key, value in arguments.items() if key in allowed}


class SearchMaterialsArgs(EmptyToolArgs):
    """资料检索允许 Planner 提供检索词及返回数量。"""

    query: str | None = Field(default=None, min_length=1, max_length=500)
    keyword: str | None = Field(default=None, min_length=1, max_length=500)
    max_results: int | None = Field(default=None, ge=1, le=10)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    allowed_roles: frozenset[str]
    args_model: type[BaseModel] = EmptyToolArgs
    side_effect: SideEffect = "read"
    requires_context: bool = False
    requires_confirmation: bool = False


def _spec(
    name: str,
    description: str,
    roles: set[str],
    *,
    side_effect: SideEffect = "read",
    requires_context: bool = False,
    requires_confirmation: bool = False,
) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=description,
        allowed_roles=frozenset(roles),
        side_effect=side_effect,
        requires_context=requires_context,
        requires_confirmation=requires_confirmation,
    )


TOOL_REGISTRY: dict[str, ToolSpec] = {
    "inspect_context": _spec("inspect_context", "确认课程、专题、教学班和学习阶段", {"student", "teacher", "admin"}),
    "inspect_tasks": _spec("inspect_tasks", "读取用户可见任务状态", {"student", "teacher"}),
    "inspect_learning_state": _spec("inspect_learning_state", "读取专题任务点、进度和笔记", {"student", "teacher"}, requires_context=True),
    "draft_note_improvement": _spec("draft_note_improvement", "生成当前专题的具体笔记完善步骤", {"student"}, side_effect="draft", requires_context=True),
    "summarize_recent_learning": _spec("summarize_recent_learning", "汇总学生近 7 天学习情况", {"student"}),
    "search_materials": ToolSpec(
        name="search_materials",
        description="检索当前专题可引用资料",
        allowed_roles=frozenset({"student", "teacher"}),
        args_model=SearchMaterialsArgs,
        requires_context=True,
    ),
    "check_lesson_readiness": _spec("check_lesson_readiness", "检查备课证据、课纲和成果状态", {"teacher"}, requires_context=True),
    "create_lesson_draft": _spec("create_lesson_draft", "创建待确认备课证据草稿", {"teacher"}, side_effect="draft", requires_context=True, requires_confirmation=True),
    "draft_assignment": _spec("draft_assignment", "生成不自动发布的任务草案", {"teacher"}, side_effect="draft", requires_context=True),
    "draft_study_plan": _spec("draft_study_plan", "结合学习状态生成计划", {"student"}, side_effect="draft", requires_context=True),
    "prepare_grading_rubric": _spec("prepare_grading_rubric", "准备批改量规和反馈模板", {"teacher"}, side_effect="draft", requires_context=True),
    "prepare_follow_up": _spec("prepare_follow_up", "生成不自动发送的跟进建议", {"teacher"}, side_effect="draft", requires_context=True),
    "check_material_health": _spec("check_material_health", "检查资料和索引健康状态", {"teacher"}, requires_context=True),
    "generate_lesson_outline": _spec("generate_lesson_outline", "检查或生成课纲入口", {"teacher"}, side_effect="draft", requires_context=True),
    "generate_ppt": _spec("generate_ppt", "生成 PPT 入口", {"teacher"}, side_effect="draft", requires_context=True),
    "generate_lesson_plan": _spec("generate_lesson_plan", "生成教案入口", {"teacher"}, side_effect="draft", requires_context=True),
    "generate_classroom_activity": _spec("generate_classroom_activity", "生成课堂互动入口", {"teacher"}, side_effect="draft", requires_context=True),
    "generate_all_artifacts": _spec("generate_all_artifacts", "生成全部教学成果入口", {"teacher"}, side_effect="draft", requires_context=True),
    "inspect_admin_overview": _spec("inspect_admin_overview", "汇总平台治理风险", {"admin"}),
    "inspect_discovery_status": _spec("inspect_discovery_status", "检查资料发现和审核队列", {"admin"}),
    "inspect_knowledge_governance": _spec("inspect_knowledge_governance", "检查知识库治理状态", {"admin"}),
    "inspect_ai_operations": _spec("inspect_ai_operations", "检查 AI 运行状态", {"admin"}),
    "inspect_teaching_governance": _spec("inspect_teaching_governance", "检查教学组织状态", {"admin"}),
}


def allowed_tools(role: str) -> dict[str, ToolSpec]:
    return {name: spec for name, spec in TOOL_REGISTRY.items() if role in spec.allowed_roles}


def invoke_registered_tool(
    planner: PlanningAgent,
    *,
    name: str,
    reason: str,
    arguments: dict[str, Any] | None = None,
    question: str,
    role: str,
    context: Any,
) -> ToolResult:
    spec = TOOL_REGISTRY.get(name)
    if spec is None:
        return ToolResult(
            f"工具“{name}”未注册，已拒绝执行。",
            status="failed",
            warnings=[f"未注册工具：{name}"],
        )
    if role not in spec.allowed_roles:
        return ToolResult(
            f"当前角色无权调用“{name}”。",
            status="failed",
            warnings=[f"角色“{role}”无权调用工具“{name}”"],
        )
    raw_arguments = _normalize_tool_arguments(name, arguments or {})
    try:
        validated_arguments = spec.args_model.model_validate(raw_arguments)
    except ValidationError as exc:
        return ToolResult(
            f"工具“{name}”的参数不符合要求，已拒绝执行。",
            status="failed",
            warnings=[f"工具“{name}”的参数格式不正确，请重试。"],
            data={"tool": name, "arguments": raw_arguments},
        )
    if spec.requires_context and (not context.course_id or not context.chapter_id):
        return ToolResult(
            "该工具需要先锁定课程和具体专题。",
            status="needs_input",
            action={"kind": "select_context", "label": "选择教材专题", "href": "/courses", "requires_confirmation": False},
        )
    call = ToolCall(
        name,
        reason,
        spec.requires_confirmation,
        validated_arguments.model_dump(),
    )
    result = planner.invoke(call, question=question, role=role, context=context)
    # 注册表是最终副作用边界；工具自身即使返回了不一致的确认标记，也不能放宽策略。
    if spec.requires_confirmation and result.action:
        result.action.setdefault("requires_confirmation", True)
    return result

"""面向教学场景的受控规划型 Agent。

规划器只允许调用本文件注册的工具。工具返回结构化结果，路由层再将结果
转成流式事件，因此后续可以把进程内执行器替换成任务队列，而不改变产品协议。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from typing import Any, Iterator

from pydantic import BaseModel, Field

from langchain_core.prompts import ChatPromptTemplate
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.agent_run import AgentRun
from app.models.authority_discovery import AuthoritySourceRegistry, DiscoveryJob, MaterialCandidate
from app.models.course import Course
from app.models.knowledge_document import KnowledgeDocument
from app.models.teacher_assignment import TeacherAssignment
from app.models.teaching_class import TeachingClass
from app.models.user import User
from app.schemas.agent import AgentRunCreate, LessonPrepInput
from app.schemas.ai import AiWorkspaceContextData
from app.rag.retriever import retrieve
from app.services.agent_service import AgentService
from app.services.ai_operation_service import AiOperationQueryService, AiProviderConfigService, build_chat_model
from app.services.assignment_service import AssignmentService
from app.services.study_service import StudyService
from app.services.student_learning_summary_service import StudentLearningSummaryService
from app.services.task_service import TaskService
from app.services.llm_compat import clean_model_text


logger = logging.getLogger(__name__)


class PlannedTool(BaseModel):
    """模型规划输出的单个工具选择，服务端仍会做角色白名单过滤。"""

    name: str
    reason: str = Field(default="完成当前目标")
    requires_confirmation: bool = False
    arguments: dict[str, Any] = Field(default_factory=dict)


class PlannedToolSet(BaseModel):
    tools: list[PlannedTool] = Field(default_factory=list, max_length=5)


@dataclass(frozen=True)
class ToolCall:
    name: str
    reason: str
    requires_confirmation: bool = False
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    text: str
    action: dict[str, Any] | None = None
    data: dict[str, Any] | None = None
    status: str = "completed"
    warnings: list[str] | None = None
    retryable: bool = False

    def contract(self, call: ToolCall) -> dict[str, Any]:
        """统一工具结果协议，供持久化执行记录和前端任务中心共享。"""
        return {
            "tool": call.name,
            "title": call.reason,
            "status": self.status,
            "summary": self.text,
            "data": self.data or {},
            "action": self.action or {},
            "warnings": self.warnings or [],
            "retryable": self.retryable,
            "requires_confirmation": call.requires_confirmation,
            "arguments": call.arguments,
        }


class PlanningAgent:
    """规划、校验并执行教学工具，不允许模型直接访问数据库或写操作。"""

    TOOL_DESCRIPTIONS = {
        "inspect_context": "读取当前课程、教材专题、教学班和学习阶段",
        "inspect_tasks": "读取当前用户可见的待完成或已发布任务状态",
        "inspect_learning_state": "读取学生任务点、学习进度和个人笔记状态",
        "draft_note_improvement": "根据当前专题和已有笔记生成具体完善步骤",
        "summarize_recent_learning": "汇总当前学生近 7 天的网站学习行为、任务、练习和薄弱点",
        "search_materials": "在当前教材专题范围内检索可引用的教材与权威资料；arguments 可选 query/keyword（检索词）和 max_results（1-10）",
        "check_lesson_readiness": "检查当前专题是否已有证据、课纲和可继续生成的成果",
        "create_lesson_draft": "根据当前专题创建待确认的备课草稿和教材证据快照",
        "draft_assignment": "根据当前专题生成不自动发布的课后任务草案",
        "draft_study_plan": "结合教材专题和学生待办生成学习计划",
        "prepare_grading_rubric": "依据当前专题生成可由教师确认的批改量规与反馈模板",
        "prepare_follow_up": "根据未完成任务生成不自动发送的提醒与跟进建议",
        "check_material_health": "检查当前教材、中央材料和索引是否具备可用依据",
        "generate_lesson_outline": "沿用备课工作流生成课纲",
        "generate_ppt": "沿用备课工作流生成 PPT",
        "generate_lesson_plan": "沿用备课工作流生成教案",
        "generate_classroom_activity": "沿用备课工作流生成课堂互动",
        "generate_all_artifacts": "沿用备课工作流生成 PPT、教案和课堂互动",
        "inspect_admin_overview": "汇总管理员平台概览中的待处理事项与运行风险",
        "inspect_discovery_status": "检查权威来源、发现任务和候选资料审核队列",
        "inspect_knowledge_governance": "检查知识库资料发布、校准、索引与失败状态",
        "inspect_ai_operations": "检查近 24 小时模型调用、失败率和当前服务配置",
        "inspect_teaching_governance": "检查教师审核、教学班和教学任务的运行状态",
    }

    ROLE_TOOL_ALLOWLIST = {
        "student": {
            "inspect_context", "inspect_tasks", "inspect_learning_state",
            "search_materials", "draft_study_plan", "draft_note_improvement", "summarize_recent_learning",
        },
        "teacher": {
            "inspect_context", "inspect_tasks", "inspect_learning_state", "search_materials",
            "check_lesson_readiness", "create_lesson_draft", "draft_assignment",
            "prepare_grading_rubric", "prepare_follow_up", "check_material_health",
            "generate_lesson_outline", "generate_ppt", "generate_lesson_plan",
            "generate_classroom_activity", "generate_all_artifacts",
        },
        "admin": {
            "inspect_admin_overview", "inspect_discovery_status", "inspect_knowledge_governance",
            "inspect_ai_operations", "inspect_teaching_governance",
        },
    }

    def __init__(self, db: Session, user: User) -> None:
        self.db = db
        self.user = user

    @staticmethod
    def _extract_json(value: Any) -> dict[str, Any] | None:
        content = getattr(value, "content", value)
        if isinstance(content, list):
            content = "".join(
                str(item.get("text", "")) if isinstance(item, dict) else str(item)
                for item in content
            )
        if not isinstance(content, str):
            return None
        content = clean_model_text(content)
        decoder = json.JSONDecoder()
        for index, char in enumerate(content):
            if char != "{":
                continue
            try:
                parsed, _ = decoder.raw_decode(content[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
        return None

    def _deterministic_plan(self, question: str, role: str) -> list[ToolCall]:
        text = question.lower().replace(" ", "")
        if role == "admin":
            if any(term in text for term in ("发现", "候选", "审核队列", "权威来源", "抓取", "爬取", "资料动态")):
                return [ToolCall("inspect_discovery_status", "检查权威来源、发现任务和候选审核队列")]
            if any(term in text for term in ("ai调用", "模型调用", "接口", "apikey", "服务配置", "失败率", "运行中心", "模型状态")):
                return [ToolCall("inspect_ai_operations", "检查 AI 调用与服务运行状态")]
            if any(term in text for term in ("知识库", "索引", "校准", "教材版本", "中央材料", "资料健康", "材料健康")):
                return [ToolCall("inspect_knowledge_governance", "检查知识库、教材版本和索引状态")]
            if any(term in text for term in ("教师审核", "教师", "教学班", "教学任务", "任务发布", "教学组织", "学情")):
                return [ToolCall("inspect_teaching_governance", "检查教师、教学班和教学任务运行状态")]
            return [ToolCall("inspect_admin_overview", "汇总平台待处理事项与运行风险")]
        if any(term in text for term in ("引用", "原文", "教材依据", "查资料", "找资料", "关联教材", "知识点")):
            return [
                ToolCall("inspect_context", "确认教材专题和学习范围"),
                ToolCall("search_materials", "检索可引用的教材与权威资料"),
            ]
        if role == "student" and any(term in text for term in (
            "近7天", "最近7天", "七天总结", "近期总结", "学习周报", "最近学了什么", "本周学习",
            "最近完成", "近期完成", "最近做完", "近期做完", "完成了哪些任务", "完成过哪些任务",
        )):
            return [ToolCall("summarize_recent_learning", "汇总近 7 天个人学习情况")]
        if role == "student" and any(term in text for term in ("完善笔记", "补充笔记", "修改笔记", "笔记情况", "笔记内容")):
            return [
                ToolCall("inspect_context", "确认当前学习专题"),
                ToolCall("inspect_learning_state", "读取任务点、进度和个人笔记状态"),
                ToolCall("draft_note_improvement", "生成当前专题的具体笔记完善步骤"),
            ]
        if role == "student" and any(term in text for term in ("我的进度", "学习状态", "笔记情况", "完成了什么", "还要做什么")):
            return [
                ToolCall("inspect_context", "确认当前学习专题"),
                ToolCall("inspect_learning_state", "读取任务点、进度和个人笔记状态"),
            ]
        if role == "teacher" and any(term in text for term in ("备课状态", "准备好了吗", "课纲状态", "生成到哪", "成果状态")):
            return [
                ToolCall("inspect_context", "确认当前备课专题"),
                ToolCall("check_lesson_readiness", "检查证据、课纲和教学成果状态"),
            ]
        if role == "teacher" and any(term in text for term in ("批改", "批阅", "评分", "量规", "反馈模板")):
            return [
                ToolCall("inspect_context", "确认批改所对应的教材专题"),
                ToolCall("prepare_grading_rubric", "生成可审阅的批改量规与反馈模板"),
            ]
        if role == "teacher" and any(term in text for term in ("提醒", "催办", "谁没完成", "未完成学生", "跟进学生")):
            return [
                ToolCall("inspect_context", "确认教学范围"),
                ToolCall("inspect_tasks", "读取任务完成状态"),
                ToolCall("prepare_follow_up", "形成不自动发送的跟进建议"),
            ]
        if role == "teacher" and any(term in text for term in ("索引状态", "资料状态", "资料健康", "材料健康", "检查资料")):
            return [
                ToolCall("inspect_context", "确认资料对应教材"),
                ToolCall("check_material_health", "检查教材、中央材料与索引状态"),
            ]
        if role == "teacher" and any(term in text for term in ("一键生成全部", "生成全部成果", "全部教学成果")):
            return [ToolCall("inspect_context", "确认当前备课专题"), ToolCall("generate_all_artifacts", "生成 PPT、教案和课堂互动")]
        if role == "teacher" and any(term in text for term in ("生成ppt", "生成课件", "制作ppt")):
            return [ToolCall("inspect_context", "确认当前备课专题"), ToolCall("generate_ppt", "生成 PPT")]
        if role == "teacher" and any(term in text for term in ("生成教案", "制作教案")):
            return [ToolCall("inspect_context", "确认当前备课专题"), ToolCall("generate_lesson_plan", "生成教案")]
        if role == "teacher" and any(term in text for term in ("生成课堂互动", "生成讨论题", "生成活动")):
            return [ToolCall("inspect_context", "确认当前备课专题"), ToolCall("generate_classroom_activity", "生成课堂互动")]
        if role == "teacher" and any(
            term in text
            for term in ("课纲", "备课", "教案", "ppt", "课件", "课堂互动", "讨论题", "活动设计")
        ):
            return [
                ToolCall("inspect_context", "确认教材专题和教学班"),
                ToolCall("create_lesson_draft", "构建教材证据并创建待确认备课草稿", True),
            ]
        if role == "teacher" and any(
            term in text
            for term in ("学习任务", "课后任务", "任务单", "研讨任务", "实践任务", "布置任务", "作业任务")
        ):
            return [
                ToolCall("inspect_context", "确认任务适用的教材专题和教学班"),
                ToolCall("draft_assignment", "生成任务目标、提交要求和完成标准"),
            ]
        if role == "student" and any(term in text for term in ("任务", "计划", "复习", "预习", "冲刺", "怎么学")):
            return [
                ToolCall("inspect_context", "确认当前学习专题"),
                ToolCall("inspect_tasks", "读取个人待完成任务"),
                ToolCall("inspect_learning_state", "读取当前专题任务点和笔记状态"),
                ToolCall("draft_study_plan", "生成可执行的学习顺序"),
            ]
        if any(term in text for term in ("任务进度", "未完成", "学情", "完成情况")):
            return [
                ToolCall("inspect_context", "确认教学范围"),
                ToolCall("inspect_tasks", "读取任务完成状态"),
                ToolCall("inspect_learning_state", "补充学习进度与待跟进信息"),
            ]
        return [ToolCall("inspect_context", "确认当前教学上下文")]

    def _allowed_tools(self, role: str) -> set[str]:
        return set(self.ROLE_TOOL_ALLOWLIST.get(role, self.ROLE_TOOL_ALLOWLIST["student"]))

    @staticmethod
    def _planning_prompt() -> ChatPromptTemplate:
        """Build the optional LLM planner prompt.

        The JSON example must escape braces for LangChain's f-string template
        parser.  Keeping construction in one helper also makes this production
        failure mode testable without calling an external model.
        """
        return ChatPromptTemplate.from_messages([
            (
                "system",
                "你是高校思政课工作流规划器。只能从给定工具中选择，不能编造工具。"
                "返回 JSON：{{\"tools\":[{{\"name\":\"工具名\",\"reason\":\"原因\","
                "\"requires_confirmation\":false,\"arguments\":{{}}}}]}}。最多选择 5 个工具；"
                "发布、删除、通知永远不能自主调用。",
            ),
            ("human", "角色：{role}\n问题：{question}\n当前范围：{context}\n可用工具：{tools}"),
        ])

    def _llm_plan(self, question: str, role: str, context: AiWorkspaceContextData) -> list[ToolCall] | None:
        runtime = AiProviderConfigService.resolve(self.db)
        if not settings.agent_planner_use_llm or settings.ai_mock_mode or not runtime.api_key:
            return None
        prompt = self._planning_prompt()
        model, _ = build_chat_model(
            feature="agent_planning",
            user_id=self.user.id,
            db=self.db,
            temperature=0,
            # 工具规划不承担内容创作，短超时后立即退回确定性规划，避免 SSE
            # 长时间只有“已读取上下文”而没有后续反馈。
            timeout=min(runtime.timeout_seconds, 8),
            streaming=False,
        )
        try:
            allowed = self._allowed_tools(role)
            variables = {
                "role": role,
                "question": question,
                "context": context.model_dump_json(ensure_ascii=False),
                "tools": json.dumps(
                    {name: self.TOOL_DESCRIPTIONS[name] for name in allowed},
                    ensure_ascii=False,
                ),
            }
            structured = getattr(model, "with_structured_output", None)
            response: Any
            if callable(structured):
                try:
                    response = (prompt | structured(PlannedToolSet)).invoke(variables)
                except Exception:
                    # 兼容不支持 structured output 的 OpenAI-compatible 模型。
                    response = (prompt | model).invoke(variables)
            else:
                response = (prompt | model).invoke(variables)
            if isinstance(response, PlannedToolSet):
                parsed_tools = [item.model_dump() for item in response.tools]
            else:
                parsed = self._extract_json(response)
                if not parsed or not isinstance(parsed.get("tools"), list):
                    return None
                parsed_tools = parsed["tools"]
            result: list[ToolCall] = []
            for item in parsed_tools[: settings.agent_planner_max_steps]:
                if not isinstance(item, dict) or item.get("name") not in allowed:
                    continue
                name = str(item["name"])
                needs_confirmation = bool(item.get("requires_confirmation")) or name == "create_lesson_draft"
                raw_arguments = item.get("arguments") or {}
                if not isinstance(raw_arguments, dict):
                    raw_arguments = {}
                result.append(ToolCall(
                    name,
                    str(item.get("reason") or "完成当前目标"),
                    needs_confirmation,
                    raw_arguments,
                ))
            return result or None
        except Exception as exc:
            logger.warning("agent_planner_llm_fallback reason=%s", str(exc) or type(exc).__name__)
            return None

    def plan(self, question: str, role: str, context: AiWorkspaceContextData) -> list[ToolCall]:
        deterministic = self._deterministic_plan(question, role)
        # Admin 工具是平台状态查询，意图边界清晰且结果必须可审计，不需要先请求
        # 外部模型做二次规划。这样 AI 服务配置异常时，管理员仍能读取平台进度。
        if role == "admin":
            return deterministic[: settings.agent_planner_max_steps]
        # 所有已被规则识别的明确目标都直接采用可审计路径，包括只有一个工具的
        # “近 7 天学习总结”。仅默认的上下文检查代表意图仍然模糊，此时才请求
        # 外部模型补充计划。这样模型、网络或 Prompt 异常不会阻断已知业务工具。
        is_ambiguous = (
            len(deterministic) == 1
            and deterministic[0].name == "inspect_context"
            and deterministic[0].reason == "确认当前教学上下文"
        )
        calls = (self._llm_plan(question, role, context) or deterministic) if is_ambiguous else deterministic
        # LLM 计划即使格式正确，也可能漏掉完成目标所必需的工具；补齐由规则
        # 推导出的最小安全计划，避免“只读了上下文却没有生成结果”。
        if calls is not deterministic:
            existing_names = {call.name for call in calls}
            calls = [*calls, *(call for call in deterministic if call.name not in existing_names)]
        # 防止模型重复工具、绕过安全边界或输出过长计划。
        allowed = self._allowed_tools(role)
        seen: set[str] = set()
        clean: list[ToolCall] = []
        for call in calls:
            if call.name in seen or call.name not in allowed:
                continue
            seen.add(call.name)
            clean.append(call)
        return clean[: settings.agent_planner_max_steps]

    @staticmethod
    def _chunk_text(value: Any) -> str:
        content = getattr(value, "content", value)
        if isinstance(content, list):
            content = "".join(
                str(item.get("text", "")) if isinstance(item, dict) else str(item)
                for item in content
            )
        return content.strip() if isinstance(content, str) else str(content or "").strip()

    def synthesize_stream(
        self,
        *,
        question: str,
        role: str,
        context: AiWorkspaceContextData,
        results: list[tuple[ToolCall, ToolResult]],
    ) -> Iterator[str]:
        """把工具结果整理为面向用户的下一步答复。

        工具负责事实和动作，模型只负责归纳，不允许在这里新增工具或声称已完成
        未执行的写操作。模型不可用时回退为结构化文本，保证 Agent 不会“执行完就
        没有下文”。
        """
        useful = [
            {
                "tool": call.name,
                "reason": call.reason,
                "text": result.text[:1800],
                "data": result.data or {},
                "action": result.action or {},
            }
            for call, result in results
            if result.text or result.data or result.action
        ]
        fallback_parts = [item["text"] for item in useful if item["text"]]
        if not fallback_parts:
            fallback_parts = ["已完成范围检查，但当前没有需要你继续处理的结果。"]
        fallback = "\n\n".join(fallback_parts)
        # 多步骤工具流程本身已经产生可用、可审计的结果。立即返回这些结果，
        # 不再额外等待一次模型“润色”，保证任务草案、资料检索和备课入口能
        # 快速呈现。单步模糊问答仍可调用模型做说明性总结。
        if role == "admin" or any(call.name == "summarize_recent_learning" for call, _result in results):
            yield fallback
            return
        runtime = AiProviderConfigService.resolve(self.db)
        if len(results) > 1 or not settings.agent_planner_use_llm or settings.ai_mock_mode or not runtime.api_key:
            yield fallback
            return
        prompt = ChatPromptTemplate.from_messages([
            (
                "system",
                "你是高校思政课效率型 Agent 的总结器。根据工具结果给出简洁、可执行的中文答复。"
                "先说结论，再列出已经完成、待用户确认和下一步操作。不得编造工具结果，"
                "不得把草案说成已发布，不得新增工具调用；如果资料不足，要明确说不足。"
                "保留教材资料的标题和位置，不要输出双重星号或夸张的 AI 话术。",
            ),
            (
                "human",
                "角色：{role}\n问题：{question}\n当前范围：{context}\n工具结果：{results}",
            ),
        ])
        model, _ = build_chat_model(
            feature="agent_response",
            user_id=self.user.id,
            db=self.db,
            temperature=0.2,
            timeout=min(runtime.timeout_seconds, 12),
            streaming=True,
        )
        raw_parts: list[str] = []
        try:
            stream = (prompt | model).stream({
                "role": role,
                "question": question,
                "context": context.model_dump_json(ensure_ascii=False),
                "results": json.dumps(useful, ensure_ascii=False),
            })
            for value in stream:
                text = self._chunk_text(value)
                if text:
                    raw_parts.append(text)
        except Exception as exc:
            logger.warning("agent_summary_llm_failed reason=%s", str(exc) or type(exc).__name__)
        cleaned = clean_model_text("".join(raw_parts))
        if cleaned:
            yield cleaned
        else:
            yield fallback

    def invoke(
        self,
        call: ToolCall,
        *,
        question: str,
        role: str,
        context: AiWorkspaceContextData,
    ) -> ToolResult:
        if call.name not in self._allowed_tools(role):
            return ToolResult(
                f"当前{role}角色无权调用“{call.reason}”。请使用该角色对应的 Agent 任务。",
                status="failed",
                warnings=[f"角色 {role} 不允许调用工具 {call.name}"],
                data={"denied_tool": call.name, "role": role},
            )
        if call.name == "inspect_admin_overview":
            pending_candidates = int(self.db.scalar(select(func.count(MaterialCandidate.id)).where(
                MaterialCandidate.status == "pending_review",
            )) or 0)
            failed_materials = int(self.db.scalar(select(func.count(KnowledgeDocument.id)).where(
                KnowledgeDocument.status == "failed",
            )) or 0)
            active_classes = int(self.db.scalar(select(func.count(TeachingClass.id)).where(
                TeachingClass.status == "active",
            )) or 0)
            ai_summary = AiOperationQueryService.summary(self.db)
            risk_count = pending_candidates + failed_materials + int(ai_summary["failed_24h"])
            return ToolResult(
                f"平台当前有 {pending_candidates} 条候选资料待审核、{failed_materials} 份资料处理失败、"
                f"近 24 小时 AI 调用失败 {ai_summary['failed_24h']} 次；现有 {active_classes} 个活跃教学班。"
                + ("建议先处理资料审核和运行异常。" if risk_count else "当前没有需要立即处理的运行异常。"),
                action={
                    "kind": "open_admin_overview", "label": "返回平台概览", "href": "/",
                    "requires_confirmation": False,
                },
                data={
                    "pending_candidates": pending_candidates,
                    "failed_materials": failed_materials,
                    "failed_ai_calls_24h": int(ai_summary["failed_24h"]),
                    "active_classes": active_classes,
                },
            )
        if call.name == "inspect_discovery_status":
            pending = int(self.db.scalar(select(func.count(MaterialCandidate.id)).where(
                MaterialCandidate.status == "pending_review",
            )) or 0)
            high_priority = int(self.db.scalar(select(func.count(MaterialCandidate.id)).where(
                MaterialCandidate.status == "pending_review",
                MaterialCandidate.importance_level == "high",
            )) or 0)
            running_jobs = int(self.db.scalar(select(func.count(DiscoveryJob.id)).where(
                DiscoveryJob.status.in_(["queued", "running"]),
            )) or 0)
            failed_jobs = int(self.db.scalar(select(func.count(DiscoveryJob.id)).where(
                DiscoveryJob.status == "failed",
            )) or 0)
            enabled_sources = int(self.db.scalar(select(func.count(AuthoritySourceRegistry.id)).where(
                AuthoritySourceRegistry.is_enabled.is_(True),
            )) or 0)
            unhealthy_sources = int(self.db.scalar(select(func.count(AuthoritySourceRegistry.id)).where(
                AuthoritySourceRegistry.is_enabled.is_(True),
                AuthoritySourceRegistry.consecutive_failures > 0,
            )) or 0)
            current_job = self.db.scalars(
                select(DiscoveryJob)
                .where(DiscoveryJob.status.in_(["queued", "running"]))
                .order_by(DiscoveryJob.id.desc())
            ).first()
            latest_job = current_job or self.db.scalars(
                select(DiscoveryJob).order_by(DiscoveryJob.id.desc())
            ).first()
            if current_job:
                job_progress = (
                    f"当前任务 #{current_job.id} 处于{current_job.progress_stage}阶段，"
                    f"已处理来源 {current_job.processed_sources}/{current_job.total_sources}，"
                    f"发现 {current_job.discovered_count} 条、提取正文 {current_job.fetched_count} 条、"
                    f"进入待审核 {current_job.pending_review_count} 条、自动过滤 {current_job.filtered_count} 条、"
                    f"失败 {current_job.failed_count + current_job.extraction_failed_count} 条。"
                )
            elif latest_job:
                job_progress = (
                    f"当前没有运行中的发现任务；最近任务 #{latest_job.id} 状态为 {latest_job.status}，"
                    f"最终阶段为{latest_job.progress_stage}，发现 {latest_job.discovered_count} 条、"
                    f"进入待审核 {latest_job.pending_review_count} 条。"
                )
            else:
                job_progress = "当前还没有资料发现任务。"
            return ToolResult(
                f"资料发现当前启用 {enabled_sources} 个权威来源，其中 {unhealthy_sources} 个存在连续抓取失败；"
                f"有 {running_jobs} 个发现任务正在排队或运行、{failed_jobs} 个任务失败；"
                f"候选池有 {pending} 条待审核，其中 {high_priority} 条为高优先级。"
                f"{job_progress}"
                + ("建议优先处理高优先级候选和失败来源。" if high_priority or unhealthy_sources or failed_jobs else "审核队列暂无高风险异常。"),
                action={
                    "kind": "open_material_discovery", "label": "进入资料动态",
                    "href": "/material-discovery?filter=pending_review#candidate-pool",
                    "requires_confirmation": False,
                },
                data={
                    "enabled_sources": enabled_sources, "unhealthy_sources": unhealthy_sources,
                    "running_jobs": running_jobs, "failed_jobs": failed_jobs,
                    "pending_candidates": pending, "high_priority_candidates": high_priority,
                    "current_job": ({
                        "id": current_job.id,
                        "status": current_job.status,
                        "progress_stage": current_job.progress_stage,
                        "processed_sources": current_job.processed_sources,
                        "total_sources": current_job.total_sources,
                        "discovered_count": current_job.discovered_count,
                        "fetched_count": current_job.fetched_count,
                        "pending_review_count": current_job.pending_review_count,
                        "filtered_count": current_job.filtered_count,
                        "failed_count": current_job.failed_count + current_job.extraction_failed_count,
                    } if current_job else None),
                },
            )
        if call.name == "inspect_knowledge_governance":
            active = int(self.db.scalar(select(func.count(KnowledgeDocument.id)).where(
                KnowledgeDocument.is_active.is_(True),
            )) or 0)
            ready = int(self.db.scalar(select(func.count(KnowledgeDocument.id)).where(
                KnowledgeDocument.is_active.is_(True), KnowledgeDocument.status == "ready",
            )) or 0)
            failed = int(self.db.scalar(select(func.count(KnowledgeDocument.id)).where(
                KnowledgeDocument.status == "failed",
            )) or 0)
            pending_review = int(self.db.scalar(select(func.count(KnowledgeDocument.id)).where(
                KnowledgeDocument.review_status == "pending",
            )) or 0)
            pending_calibration = int(self.db.scalar(select(func.count(KnowledgeDocument.id)).where(
                KnowledgeDocument.material_type == "textbook",
                KnowledgeDocument.calibration_status != "published",
            )) or 0)
            published_central = int(self.db.scalar(select(func.count(KnowledgeDocument.id)).where(
                KnowledgeDocument.material_type == "central",
                KnowledgeDocument.review_status == "published",
                KnowledgeDocument.status == "ready",
            )) or 0)
            return ToolResult(
                f"知识库共有 {active} 份启用资料，其中 {ready} 份索引就绪、{failed} 份处理失败；"
                f"{pending_review} 份等待审核，{pending_calibration} 份教材尚未完成校准发布，"
                f"当前有 {published_central} 份已发布中央材料。"
                + ("建议先处理失败资料和待校准教材。" if failed or pending_calibration else "当前索引与发布状态正常。"),
                action={
                    "kind": "open_knowledge_governance", "label": "进入知识库治理", "href": "/knowledge",
                    "requires_confirmation": False,
                },
                data={
                    "active_documents": active, "ready_documents": ready, "failed_documents": failed,
                    "pending_review": pending_review, "pending_calibration": pending_calibration,
                    "published_central": published_central,
                },
            )
        if call.name == "inspect_ai_operations":
            summary = AiOperationQueryService.summary(self.db)
            success_percent = round(float(summary["success_rate"]) * 100)
            latency = "暂无完成请求" if summary["average_latency_ms"] is None else f"平均耗时 {summary['average_latency_ms']} 毫秒"
            return ToolResult(
                f"近 24 小时共有 {summary['total_24h']} 次 AI 调用，成功率 {success_percent}%，"
                f"失败 {summary['failed_24h']} 次，当前运行中 {summary['running']} 次，{latency}。"
                f"当前模型为 {summary['active_model']}，配置来源为"
                f"{'管理员配置' if summary['config_source'] == 'database' else '服务器环境变量'}。"
                + ("建议进入运行中心查看失败调用详情。" if summary["failed_24h"] else "当前未发现调用失败。"),
                action={
                    "kind": "open_ai_operations", "label": "进入 AI 运行中心", "href": "/ai-operations",
                    "requires_confirmation": False,
                },
                data=summary,
            )
        if call.name == "inspect_teaching_governance":
            approved_teachers = int(self.db.scalar(select(func.count(User.id)).where(
                User.role == "teacher", User.approval_status == "approved",
            )) or 0)
            pending_teachers = int(self.db.scalar(select(func.count(User.id)).where(
                User.role == "teacher", User.approval_status == "pending",
            )) or 0)
            total_classes = int(self.db.scalar(select(func.count(TeachingClass.id))) or 0)
            active_classes = int(self.db.scalar(select(func.count(TeachingClass.id)).where(
                TeachingClass.status == "active",
            )) or 0)
            total_courses = int(self.db.scalar(select(func.count(Course.id))) or 0)
            published_assignments = int(self.db.scalar(select(func.count(TeacherAssignment.id)).where(
                TeacherAssignment.status == "published",
            )) or 0)
            text = question.lower().replace(" ", "")
            assignment_focus = any(term in text for term in ("任务", "发布", "学情", "完成"))
            return ToolResult(
                f"平台现有 {approved_teachers} 名已审核教师、{pending_teachers} 名教师等待审核；"
                f"共 {total_classes} 个教学班，其中 {active_classes} 个处于活跃状态；"
                f"维护 {total_courses} 门教材课程，当前有 {published_assignments} 项已发布教学任务。"
                + ("建议先处理待审核教师。" if pending_teachers else "教师准入当前没有待处理项。"),
                action={
                    "kind": "open_teaching_governance",
                    "label": "查看任务监督" if assignment_focus else "进入教学管理",
                    "href": "/assignments" if assignment_focus else "/classes",
                    "requires_confirmation": False,
                },
                data={
                    "approved_teachers": approved_teachers, "pending_teachers": pending_teachers,
                    "total_classes": total_classes, "active_classes": active_classes,
                    "total_courses": total_courses, "published_assignments": published_assignments,
                },
            )
        if call.name == "inspect_context":
            if not context.course_id or not context.chapter_id:
                return ToolResult(
                    "当前尚未锁定具体教材专题，请先选择课程专题；选择后我才能继续调用教材工具。",
                    action={
                        "kind": "select_context",
                        "label": "选择教材专题",
                        "href": "/courses",
                        "requires_confirmation": False,
                    },
                    data={"grounded": False},
                )
            selected_titles = context.chapter_titles or ([context.chapter_title] if context.chapter_title else [])
            scope_label = "、".join(selected_titles)
            primary_hint = f"；写入操作以“{context.chapter_title}”为主专题" if len(selected_titles) > 1 else ""
            return ToolResult(
                f"已锁定《{context.course_name}》·{scope_label}"
                + (f"·教学班：{context.teaching_class_name}" if context.teaching_class_name else "")
                + primary_hint,
                data={"grounded": True, "chapter_ids": context.chapter_ids},
            )
        if call.name == "summarize_recent_learning":
            summary = StudentLearningSummaryService(self.db).summarize(self.user.id)
            active = summary["active"]
            tasks = summary["task_points"]
            assignments = summary["assignments"]
            actions = summary["learning_actions"]
            completion_parts: list[str] = []
            if tasks["completed_items"]:
                task_labels = "；".join(
                    f"《{item['course_name']}》·{item['chapter_title']}：{item['title']}"
                    for item in tasks["completed_items"][:5]
                )
                remaining = tasks["completed"] - min(5, len(tasks["completed_items"]))
                completion_parts.append(f"任务点：{task_labels}" + (f"；另有 {remaining} 项" if remaining > 0 else ""))
            if assignments["completed_items"]:
                assignment_labels = "；".join(
                    f"《{item['title']}》（{item['chapter_title']}）"
                    for item in assignments["completed_items"][:5]
                )
                remaining = assignments["completed_in_period"] - min(5, len(assignments["completed_items"]))
                completion_parts.append(
                    f"教师任务：{assignment_labels}" + (f"；另有 {remaining} 项" if remaining > 0 else "")
                )
            completion_text = (
                "\n具体完成：" + "\n".join(completion_parts) + "。"
                if completion_parts
                else "\n具体完成：近 7 天未记录到已完成的任务点或教师任务。"
            )
            weak_text = "；".join(summary["weak_points"]) if summary["weak_points"] else "暂未形成足够证据判断薄弱点"
            suggestion_text = "；".join(summary["suggestions"])
            return ToolResult(
                f"近 7 天你学习了 {active['course_count']} 门课程、{active['chapter_count']} 个专题；"
                f"完成 {tasks['completed']} 个任务点，另有 {tasks['in_progress']} 个进行中。"
                f"教师任务本期完成 {assignments['completed_in_period']} 项、当前待完成 {assignments['pending']} 项、"
                f"逾期 {assignments['overdue']} 项。更新笔记 {actions['notes_updated']} 篇，"
                f"完成复习练习 {actions['practice_answered']} 题（答对 {actions['practice_correct']} 题）。"
                f"记录到 AI 任务辅助 {actions['ai_assist_events']} 次、笔记空间 AI 提问 {actions['ai_chat_questions']} 次；"
                f"这些仅作为学习投入参考，不计为知识掌握。{completion_text}"
                f"\n薄弱点：{weak_text}。\n下一步：{suggestion_text}。",
                action={
                    "kind": "open_student_assignments", "label": "查看我的任务", "href": "/assignments",
                    "requires_confirmation": False,
                },
                data=summary,
            )
        if call.name == "inspect_tasks":
            if role == "student":
                tasks = AssignmentService(self.db).student_assignments(self.user.id, include_completed=False)
                if not tasks:
                    return ToolResult("当前没有待完成的教师任务。", data={"task_count": 0})
                summary = "；".join(
                    f"《{item['title']}》（{item['chapter_title']}，进度 {item['progress_value']}%）"
                    for item in tasks[:5]
                )
                return ToolResult(f"当前有 {len(tasks)} 项待完成任务：{summary}", data={"task_count": len(tasks)})
            tasks = AssignmentService(self.db).teacher_assignments(self.user.id, is_admin=role == "admin")
            active = [item for item in tasks if item["status"] == "published"]
            return ToolResult(f"已读取 {len(active)} 项已发布教学任务及其完成状态。", data={"task_count": len(active)})
        if call.name == "inspect_learning_state":
            if not context.course_id or not context.chapter_id:
                return ToolResult(
                    "还没有锁定具体专题，暂时无法读取本专题学习状态。",
                    action={
                        "kind": "select_context",
                        "label": "先选择教材专题",
                        "href": "/courses",
                        "requires_confirmation": False,
                    },
                    data={"grounded": False},
                )
            stage = context.learning_stage
            if role == "student":
                summary = TaskService(self.db).summary(
                    self.user.id, context.course_id, context.chapter_id, stage
                )
                note = StudyService(self.db).get_note(self.user.id, context.chapter_id)
                pending = [item.title for item in summary.tasks if item.status != "completed"]
                note_state = "已有个人笔记" if note and StudyService.plain_note_content(note.content) else "尚未保存个人笔记"
                pending_text = "、".join(pending[:4]) if pending else "任务点已全部完成"
                return ToolResult(
                    f"当前专题{stage}阶段进度为 {summary.progress}%，已完成 {summary.completed_count}/{summary.total_count} 个任务点；"
                    f"待处理：{pending_text}；{note_state}。",
                    data={
                        "progress": summary.progress,
                        "completed_count": summary.completed_count,
                        "total_count": summary.total_count,
                        "pending_tasks": pending,
                        "has_note": bool(note and StudyService.plain_note_content(note.content)),
                    },
                )
            assignments = AssignmentService(self.db).teacher_assignments(
                self.user.id, is_admin=role == "admin"
            )
            scoped = [item for item in assignments if item["course_id"] == context.course_id]
            active = [item for item in scoped if item["status"] == "published"]
            completed = sum(int(item["completed_count"]) for item in active)
            total = sum(int(item["total_count"]) for item in active)
            return ToolResult(
                f"当前教材下有 {len(active)} 项已发布任务，累计完成 {completed}/{total} 人次；"
                "可进入任务页查看具体学生并决定是否提醒。",
                data={"assignment_count": len(active), "completed_count": completed, "total_count": total},
            )
        if call.name == "draft_note_improvement":
            if not context.course_id or not context.chapter_id:
                return ToolResult(
                    "还没有锁定具体专题，暂时不能生成有针对性的笔记完善步骤。",
                    action={"kind": "select_context", "label": "选择教材专题", "href": "/courses", "requires_confirmation": False},
                    data={"grounded": False},
                )
            title = context.chapter_title or "当前教材专题"
            note = StudyService(self.db).get_note(self.user.id, context.chapter_id)
            note_text = StudyService.plain_note_content(note.content) if note else ""
            has_note = bool(note_text)
            note_length = len(note_text)
            first_step = (
                "逐段检查现有笔记：给每个观点补上‘概念定义—自己的理解—教材依据’三部分。"
                if has_note else
                "先创建本专题笔记，写下你对主题的初步理解，不要直接复制教材原文。"
            )
            state_line = (
                f"当前已有笔记（约 {note_length} 字），下面的步骤以补强和校对为主。"
                if has_note else
                "当前还没有可用的个人笔记，下面的步骤从建立笔记骨架开始。"
            )
            steps = [
                first_step,
                "从教材中挑出 2—3 个核心概念，分别记录定义、概念之间的关系和一个关键词。",
                "为每个核心概念补充至少 1 处教材依据，写明章节/页码或原文位置，便于之后核对。",
                "增加一段‘我的理解’，用自己的话说明本专题解决了什么问题，并联系一个课堂或现实例子。",
                "写下 1 个仍然困惑的问题，回到 Chat 追问概念边界或容易混淆的观点。",
                "保存后对照本专题任务点复查：删除无依据表述，确认每个任务点都能在笔记中找到对应内容。",
            ]
            plan_text = (
                f"## 《{title}》笔记完善步骤\n\n"
                f"{state_line}\n\n"
                + "\n".join(f"{index}. {step}" for index, step in enumerate(steps, start=1))
                + "\n\n建议笔记结构：核心概念 → 教材依据 → 我的理解 → 例子/联系 → 待解决问题。"
            )
            return ToolResult(
                plan_text,
                status="advice_ready",
                action={
                    "kind": "open_notes",
                    "label": "打开专题笔记开始完善",
                    "href": f"/notes?chapter_id={context.chapter_id}",
                    "requires_confirmation": False,
                },
                data={
                    "chapter_id": context.chapter_id,
                    "has_note": has_note,
                    "note_length": note_length,
                    "suggested_steps": steps,
                },
            )
        if call.name == "search_materials":
            if not context.course_id:
                return ToolResult(
                    "尚未锁定教材，无法检索教材与权威资料。",
                    action={"kind": "select_context", "label": "选择教材专题", "href": "/courses", "requires_confirmation": False},
                    data={"grounded": False},
                )
            try:
                search_query = str(
                    call.arguments.get("query")
                    or call.arguments.get("keyword")
                    or question
                ).strip()
                search_limit = int(call.arguments.get("max_results") or 5)
                chunks = retrieve(
                    search_query,
                    course_id=context.course_id,
                    chapter_id=context.chapter_id,
                    top_k=max(1, min(search_limit, 10)),
                    fallback_to_course=True,
                )
            except Exception as exc:
                logger.exception("planning_agent_material_search_failed")
                return ToolResult(
                    f"资料检索暂时不可用：{str(exc) or '向量检索服务异常'}。可以稍后重试，或先检查资料索引。",
                    data={"grounded": False, "error": str(exc)},
                    status="failed",
                    warnings=["资料检索没有返回可用结果"],
                    retryable=True,
                )
            if not chunks:
                return ToolResult(
                    "当前专题没有检索到达到相关性门槛的资料，我不会用无依据内容替代教材。",
                    data={"grounded": False, "source_count": 0},
                )
            lines = []
            sources = []
            for index, chunk in enumerate(chunks, start=1):
                meta = chunk.metadata
                title = str(meta.get("source_title") or "课程资料")
                position = str(meta.get("position_label") or meta.get("position") or "当前专题正文")
                lines.append(f"{index}. {title} · {position}\n   {chunk.content[:180].strip()}")
                sources.append({
                    "source_title": title,
                    "position": position,
                    "material_type": str(meta.get("material_type") or "textbook"),
                    "score": round(float(chunk.score), 3),
                })
            return ToolResult(
                "已检索到以下可引用资料（仅展示检索结果，不代表自动发布）：\n\n" + "\n".join(lines),
                data={"grounded": True, "source_count": len(sources), "sources": sources},
            )
        if call.name == "check_lesson_readiness":
            if not context.course_id or not context.chapter_id:
                return ToolResult(
                    "尚未锁定具体专题，无法检查备课状态。",
                    action={"kind": "select_context", "label": "选择教材专题", "href": "/courses", "requires_confirmation": False},
                    data={"grounded": False},
                )
            latest = self.db.scalars(
                select(AgentRun)
                .where(
                    AgentRun.created_by == self.user.id,
                    AgentRun.course_id == context.course_id,
                    AgentRun.chapter_id == context.chapter_id,
                )
                .order_by(AgentRun.id.desc())
            ).first()
            if latest is None:
                return ToolResult(
                    "当前专题还没有备课任务，可从创建证据快照开始。",
                    action={"kind": "open_lesson_prep", "label": "进入课程备课", "href": "/lesson-prep", "requires_confirmation": False},
                    data={"run_id": None, "status": "missing"},
                )
            output = latest.output_data or {}
            has_outline = isinstance(output.get("outline"), dict)
            artifact_keys = sorted((output.get("artifacts") or {}).keys())
            if latest.status == "waiting_confirmation":
                return ToolResult(
                    f"备课任务 #{latest.id} 已生成 {len(latest.evidence_snapshot or [])} 条证据快照，正在等待教师确认。",
                    action={"kind": "approve_evidence", "label": "确认资料并生成课纲", "href": "", "run_id": latest.id, "requires_confirmation": True},
                    data={"run_id": latest.id, "status": latest.status, "has_outline": False, "artifacts": artifact_keys},
                )
            if latest.status in {"queued", "running"}:
                return ToolResult(
                    f"备课任务 #{latest.id} 正在后台执行，当前不需要重复提交。",
                    data={"run_id": latest.id, "status": latest.status, "has_outline": has_outline, "artifacts": artifact_keys},
                )
            if has_outline:
                missing = [key for key in ("ppt", "lesson_plan", "classroom_activities") if key not in artifact_keys]
                suffix = f"还缺：{'、'.join(missing)}。" if missing else "PPT、教案和课堂互动均已生成。"
                return ToolResult(
                    f"备课任务 #{latest.id} 已有课纲；{suffix}发布前仍需教师预览并确认教学班。",
                    action={"kind": "open_lesson_prep", "label": "进入预览与发布", "href": f"/lesson-prep?run_id={latest.id}", "run_id": latest.id, "requires_confirmation": False},
                    data={"run_id": latest.id, "status": latest.status, "has_outline": True, "artifacts": artifact_keys, "missing": missing},
                )
            return ToolResult(
                f"备课任务 #{latest.id} 尚未形成可用课纲，建议打开备课页查看失败步骤并重试。",
                action={"kind": "open_lesson_prep", "label": "查看备课任务", "href": f"/lesson-prep?run_id={latest.id}", "run_id": latest.id, "requires_confirmation": False},
                data={"run_id": latest.id, "status": latest.status, "has_outline": False, "artifacts": artifact_keys},
            )
        if call.name == "create_lesson_draft":
            if not context.course_id or not context.chapter_id:
                return ToolResult(
                    "未识别到具体专题，暂不能创建备课草稿。",
                    action={"kind": "select_context", "label": "选择教材专题", "href": "/courses", "requires_confirmation": False},
                )
            run = AgentService(self.db, self.user).create(AgentRunCreate(
                agent_type="teacher_lesson_prep",
                course_id=context.course_id,
                chapter_id=context.chapter_id,
                teaching_class_id=context.teaching_class_id,
                input=LessonPrepInput(lesson_hours=2, student_level="本科生", teaching_goal=question, output_types=["outline"]),
            ))
            if run.status == "failed":
                return ToolResult(
                    f"备课草稿创建失败：{run.error_message or '证据包构建失败'}",
                    status="failed",
                    warnings=[run.error_message or "证据包构建失败"],
                    retryable=True,
                )
            return ToolResult(
                f"已创建备课草稿并生成 {len(run.evidence_snapshot)} 条证据快照，等待教师确认后生成课纲。",
                action={"kind": "approve_evidence", "label": "确认资料并生成课纲", "href": "", "run_id": run.id, "requires_confirmation": True},
                data={"run_id": run.id},
            )
        if call.name == "draft_assignment":
            if not context.chapter_id or not context.chapter_title:
                return ToolResult(
                    "未识别到具体专题，暂不能生成任务草案。",
                    action={"kind": "select_context", "label": "选择教材专题", "href": "/courses", "requires_confirmation": False},
                )
            class_hint = f"，面向“{context.teaching_class_name}”" if context.teaching_class_name else ""
            draft = {
                "course_id": context.course_id,
                "chapter_id": context.chapter_id,
                "teaching_class_id": context.teaching_class_id,
                "learning_stage": "review",
                "task_kind": "reading",
                "title": f"《{context.chapter_title}》观点辨析与学习反思",
                "description": "写一篇 300—500 字学习反思或观点卡，写明一个核心观点、至少一处教材依据和一条待讨论问题。完成标准：观点相关、依据可核验、表达清楚。",
            }
            return ToolResult(
                f"## 课后学习任务草案\n\n**任务名称：**《{context.chapter_title}》观点辨析与学习反思\n\n"
                f"**适用范围：**当前教材专题{class_hint}\n\n"
                "**学生提交：**300—500 字学习反思或观点卡，写明一个核心观点、至少一处教材依据和一条待讨论问题。\n\n"
                "**完成标准：**观点相关、依据可核验、表达清楚。\n\n"
                "**教师待确认：**发布对象、截止时间、提交形式和评分权重。",
                status="advice_ready",
                action={"kind": "open_assignments", "label": "进入教学任务设置（带入草案）", "href": "/assignments", "requires_confirmation": True, "draft": draft},
                data={"draft": draft},
            )
        if call.name == "draft_study_plan":
            title = context.chapter_title or "当前教材专题"
            if not context.course_id or not context.chapter_id:
                return ToolResult(
                    "还没有选定教材专题，暂时不能生成有针对性的学习计划。",
                    action={"kind": "select_context", "label": "选择教材专题", "href": "/courses", "requires_confirmation": False},
                )
            try:
                summary = TaskService(self.db).summary(
                    self.user.id, context.course_id, context.chapter_id, context.learning_stage
                )
                note = StudyService(self.db).get_note(self.user.id, context.chapter_id)
                pending = [item.title for item in summary.tasks if item.status != "completed"]
                first_step = f"先完成“{pending[0]}”。" if pending else "先回顾本专题的任务点。"
                note_step = "再把关键观点整理到个人笔记。" if not note or not StudyService.plain_note_content(note.content) else "再回看个人笔记，补充一条教材依据。"
                plan_text = (
                    f"《{title}》本次建议按以下顺序学习：\n\n"
                    f"1. {first_step}\n"
                    f"2. 阅读教材原文并记录核心概念。\n"
                    f"3. {note_step}\n"
                    "4. 最后用 Chat 检查概念边界和原文引用。"
                )
                return ToolResult(
                    plan_text,
                    action={"kind": "open_learning_stage", "label": "进入当前专题学习", "href": f"/courses/{context.course_id}/chapters/{context.chapter_id}/preview", "requires_confirmation": False},
                    data={"progress": summary.progress, "pending_tasks": pending, "has_note": bool(note and StudyService.plain_note_content(note.content))},
                )
            except Exception as exc:
                logger.exception("planning_agent_study_plan_failed")
                return ToolResult(
                    f"已锁定《{title}》，但读取任务点失败：{str(exc) or '暂时无法读取'}。建议先进入专题学习页面。",
                    action={"kind": "open_learning_stage", "label": "进入当前专题学习", "href": f"/courses/{context.course_id}/chapters/{context.chapter_id}/preview", "requires_confirmation": False},
                    status="failed",
                    retryable=True,
                )
        if call.name == "prepare_grading_rubric":
            if not context.chapter_id or not context.chapter_title:
                return ToolResult(
                    "未识别到具体专题，暂不能生成有依据的批改量规。",
                    action={"kind": "select_context", "label": "选择教材专题", "href": "/courses", "requires_confirmation": False},
                )
            rubric = {
                "items": [
                    {"label": "教材理解", "weight": 40, "description": "准确表述核心概念，并说明概念之间的关系。"},
                    {"label": "论证与依据", "weight": 35, "description": "至少引用一处可核验教材依据，观点与依据一致。"},
                    {"label": "联系实际", "weight": 15, "description": "围绕具体问题形成有边界的分析，不泛化表态。"},
                    {"label": "表达规范", "weight": 10, "description": "结构完整、语言准确、引用位置清楚。"},
                ],
                "feedback_template": "先指出学生已把握的观点，再说明需补充的教材依据，最后给出一项可执行的修改建议。",
            }
            return ToolResult(
                f"《{context.chapter_title}》批改量规草案：\n\n"
                "1. 教材理解（40%）：能准确表述核心概念，并说明概念之间的关系。\n"
                "2. 论证与依据（35%）：至少引用一处可核验教材依据，观点与依据一致。\n"
                "3. 联系实际（15%）：围绕具体问题形成有边界的分析，不泛化表态。\n"
                "4. 表达规范（10%）：结构完整、语言准确、引用位置清楚。\n\n"
                "反馈模板：先指出学生已把握的观点，再说明需补充的教材依据，最后给出一项可执行的修改建议。"
                "该草案不会自动评分或发布。",
                status="advice_ready",
                action={"kind": "open_assignments", "label": "进入教学任务设置（确认量规）", "href": "/assignments", "requires_confirmation": True, "rubric": rubric},
                data={"rubric_ready": True, "chapter_id": context.chapter_id, "rubric": rubric},
            )
        if call.name == "prepare_follow_up":
            if not context.course_id:
                return ToolResult("还没有锁定教材范围，暂不能生成面向教学班的跟进建议。")
            assignments = AssignmentService(self.db).teacher_assignments(
                self.user.id, is_admin=role == "admin"
            )
            active = [item for item in assignments if item["status"] == "published" and item["course_id"] == context.course_id]
            outstanding = sum(max(int(item["total_count"]) - int(item["completed_count"]), 0) for item in active)
            return ToolResult(
                f"当前教材范围内有 {len(active)} 项已发布任务，尚有约 {outstanding} 人次未完成。\n\n"
                "建议跟进顺序：先查看临近截止且完成率最低的任务；再按教学班筛选未完成学生；"
                "最后由教师确认提醒文案和发送范围。系统不会自动向学生发送消息。",
                action={"kind": "open_assignments", "label": "查看未完成学生并确认提醒", "href": "/assignments", "requires_confirmation": True},
                data={"assignment_count": len(active), "outstanding_count": outstanding, "message_draft": "请结合当前专题完成学习任务；如遇到教材理解困难，可先查看专题重点并向 AI 助教提问。"},
            )
        if call.name == "check_material_health":
            if not context.course_id:
                return ToolResult(
                    "尚未锁定教材，无法检查资料与索引状态。",
                    action={"kind": "select_context", "label": "选择教材", "href": "/courses", "requires_confirmation": False},
                )
            documents = list(self.db.scalars(
                select(KnowledgeDocument).where(KnowledgeDocument.course_id == context.course_id)
            ).all())
            ready = [item for item in documents if item.status == "ready"]
            central = [item for item in ready if item.source_role == "central"]
            textbook = [item for item in ready if item.source_role in {"primary", "textbook"}]
            chunks = sum(int(item.chunk_count or 0) for item in ready)
            warnings = []
            if not textbook:
                warnings.append("未发现已就绪的教材资料")
            if not chunks:
                warnings.append("已就绪资料尚未产生可检索分块")
            summary = (
                f"资料检查完成：已就绪 {len(ready)}/{len(documents)} 份，"
                f"其中中央材料 {len(central)} 份、教材 {len(textbook)} 份、可检索分块 {chunks} 个。"
            )
            if warnings:
                summary += "\n\n需要处理：" + "；".join(warnings) + "。"
            else:
                summary += "\n\n当前资料链路可用于教材优先、中央材料优先级更高的检索回答。"
            return ToolResult(
                summary,
                action={"kind": "open_knowledge", "label": "进入资料中心核对", "href": "/knowledge", "requires_confirmation": False},
                data={"document_count": len(documents), "ready_count": len(ready), "central_count": len(central), "textbook_count": len(textbook), "chunk_count": chunks},
                warnings=warnings,
                retryable=bool(warnings),
            )
        if call.name in {
            "generate_lesson_outline",
            "generate_ppt",
            "generate_lesson_plan",
            "generate_classroom_activity",
            "generate_all_artifacts",
        }:
            if not context.course_id or not context.chapter_id:
                return ToolResult(
                    "未识别到具体教材专题，暂不能启动备课工作流。",
                    status="needs_input",
                    action={"kind": "select_context", "label": "选择教材专题", "href": "/courses", "requires_confirmation": False},
                )
            latest = self.db.scalars(
                select(AgentRun)
                .where(
                    AgentRun.created_by == self.user.id,
                    AgentRun.course_id == context.course_id,
                    AgentRun.chapter_id == context.chapter_id,
                )
                .order_by(AgentRun.id.desc())
            ).first()
            if latest is None or not isinstance((latest.output_data or {}).get("outline"), dict):
                # 没有课纲时复用现有证据确认流程，而不是伪造生成结果。
                draft = self.invoke(
                    ToolCall("create_lesson_draft", "先创建备课草稿", True),
                    question=question,
                    role=role,
                    context=context,
                )
                return ToolResult(
                    "当前还没有已确认课纲，已先启动备课工作流。" + (draft.text or ""),
                    action=draft.action,
                    data=draft.data,
                )
            output_map = {
                "generate_lesson_outline": [],
                "generate_ppt": ["ppt"],
                "generate_lesson_plan": ["lesson_plan"],
                "generate_classroom_activity": ["classroom_activities"],
                "generate_all_artifacts": ["ppt", "lesson_plan", "classroom_activities"],
            }
            output_types = output_map[call.name]
            if not output_types:
                return ToolResult("当前课纲已经生成，可继续选择 PPT、教案或课堂互动。", data={"run_id": latest.id})
            output_labels = {
                "ppt": "教学 PPT",
                "lesson_plan": "完整教案",
                "classroom_activities": "课堂活动",
            }
            output_label = "、".join(output_labels.get(item, item) for item in output_types)
            return ToolResult(
                f"已找到当前专题的已确认课纲，准备生成：{output_label}。",
                action={
                    "kind": "generate_artifacts",
                    "label": f"开始生成{'全部教学成果' if len(output_types) > 1 else output_label}",
                    "href": "",
                    "run_id": latest.id,
                    "output_types": output_types,
                    "requires_confirmation": False,
                },
                data={"run_id": latest.id, "output_types": output_types},
            )
        return ToolResult("工具未返回结果。")

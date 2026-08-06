"""面向教学场景的受控规划型 Agent。

规划器只允许调用本文件注册的工具。工具返回结构化结果，路由层再将结果
转成流式事件，因此后续可以把进程内执行器替换成任务队列，而不改变产品协议。
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from typing import Any, Iterator

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.agent_run import AgentRun
from app.models.knowledge_document import KnowledgeDocument
from app.models.user import User
from app.schemas.agent import AgentRunCreate, LessonPrepInput
from app.schemas.ai import AiWorkspaceContextData
from app.rag.retriever import retrieve
from app.services.agent_service import AgentService
from app.services.assignment_service import AssignmentService
from app.services.study_service import StudyService
from app.services.task_service import TaskService
from app.services.llm_compat import clean_model_text


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolCall:
    name: str
    reason: str
    requires_confirmation: bool = False


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
        }


class PlanningAgent:
    """规划、校验并执行教学工具，不允许模型直接访问数据库或写操作。"""

    TOOL_DESCRIPTIONS = {
        "inspect_context": "读取当前课程、教材专题、教学班和学习阶段",
        "inspect_tasks": "读取当前用户可见的待完成或已发布任务状态",
        "inspect_learning_state": "读取学生任务点、学习进度和个人笔记状态",
        "search_materials": "在当前教材专题范围内检索可引用的教材与权威资料",
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
    }

    ROLE_TOOL_DENYLIST = {
        "student": {
            "create_lesson_draft", "draft_assignment", "check_lesson_readiness",
            "generate_lesson_outline", "generate_ppt", "generate_lesson_plan",
            "generate_classroom_activity", "generate_all_artifacts",
            "prepare_grading_rubric", "prepare_follow_up", "check_material_health",
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
        if any(term in text for term in ("引用", "原文", "教材依据", "查资料", "找资料", "关联教材", "知识点")):
            return [
                ToolCall("inspect_context", "确认教材专题和学习范围"),
                ToolCall("search_materials", "检索可引用的教材与权威资料"),
            ]
        if role == "student" and any(term in text for term in ("我的进度", "学习状态", "笔记情况", "完成了什么", "还要做什么")):
            return [
                ToolCall("inspect_context", "确认当前学习专题"),
                ToolCall("inspect_learning_state", "读取任务点、进度和个人笔记状态"),
            ]
        if role in {"teacher", "admin"} and any(term in text for term in ("备课状态", "准备好了吗", "课纲状态", "生成到哪", "成果状态")):
            return [
                ToolCall("inspect_context", "确认当前备课专题"),
                ToolCall("check_lesson_readiness", "检查证据、课纲和教学成果状态"),
            ]
        if role in {"teacher", "admin"} and any(term in text for term in ("批改", "批阅", "评分", "量规", "反馈模板")):
            return [
                ToolCall("inspect_context", "确认批改所对应的教材专题"),
                ToolCall("prepare_grading_rubric", "生成可审阅的批改量规与反馈模板"),
            ]
        if role in {"teacher", "admin"} and any(term in text for term in ("提醒", "催办", "谁没完成", "未完成学生", "跟进学生")):
            return [
                ToolCall("inspect_context", "确认教学范围"),
                ToolCall("inspect_tasks", "读取任务完成状态"),
                ToolCall("prepare_follow_up", "形成不自动发送的跟进建议"),
            ]
        if role in {"teacher", "admin"} and any(term in text for term in ("索引状态", "资料状态", "资料健康", "材料健康", "检查资料")):
            return [
                ToolCall("inspect_context", "确认资料对应教材"),
                ToolCall("check_material_health", "检查教材、中央材料与索引状态"),
            ]
        if role in {"teacher", "admin"} and any(term in text for term in ("一键生成全部", "生成全部成果", "全部教学成果")):
            return [ToolCall("inspect_context", "确认当前备课专题"), ToolCall("generate_all_artifacts", "生成 PPT、教案和课堂互动")]
        if role in {"teacher", "admin"} and any(term in text for term in ("生成ppt", "生成课件", "制作ppt")):
            return [ToolCall("inspect_context", "确认当前备课专题"), ToolCall("generate_ppt", "生成 PPT")]
        if role in {"teacher", "admin"} and any(term in text for term in ("生成教案", "制作教案")):
            return [ToolCall("inspect_context", "确认当前备课专题"), ToolCall("generate_lesson_plan", "生成教案")]
        if role in {"teacher", "admin"} and any(term in text for term in ("生成课堂互动", "生成讨论题", "生成活动")):
            return [ToolCall("inspect_context", "确认当前备课专题"), ToolCall("generate_classroom_activity", "生成课堂互动")]
        if role in {"teacher", "admin"} and any(
            term in text
            for term in ("课纲", "备课", "教案", "ppt", "课件", "课堂互动", "讨论题", "活动设计")
        ):
            return [
                ToolCall("inspect_context", "确认教材专题和教学班"),
                ToolCall("create_lesson_draft", "构建教材证据并创建待确认备课草稿", True),
            ]
        if role in {"teacher", "admin"} and any(
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
        return set(self.TOOL_DESCRIPTIONS) - self.ROLE_TOOL_DENYLIST.get(role, set())

    def _llm_plan(self, question: str, role: str, context: AiWorkspaceContextData) -> list[ToolCall] | None:
        if not settings.agent_planner_use_llm or settings.ai_mock_mode or not settings.llm_api_key:
            return None
        prompt = ChatPromptTemplate.from_messages([
            ("system", "你是高校思政课工作流规划器。只能从给定工具中选择，不能编造工具。返回 JSON：{\"tools\":[{\"name\":\"工具名\",\"reason\":\"原因\",\"requires_confirmation\":false}]}。最多选择 5 个工具；发布、删除、通知永远不能自主调用。"),
            ("human", "角色：{role}\n问题：{question}\n当前范围：{context}\n可用工具：{tools}"),
        ])
        model = ChatOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            temperature=0,
            # 工具规划不承担内容创作，短超时后立即退回确定性规划，避免 SSE
            # 长时间只有“已读取上下文”而没有后续反馈。
            timeout=min(settings.llm_timeout_seconds, 8),
            streaming=False,
        )
        try:
            response = (prompt | model).invoke({
                "role": role,
                "question": question,
                "context": context.model_dump_json(ensure_ascii=False),
                "tools": json.dumps(
                    {name: self.TOOL_DESCRIPTIONS[name] for name in self._allowed_tools(role)},
                    ensure_ascii=False,
                ),
            })
            parsed = self._extract_json(response)
            if not parsed or not isinstance(parsed.get("tools"), list):
                return None
            allowed = self._allowed_tools(role)
            result: list[ToolCall] = []
            for item in parsed["tools"][: settings.agent_planner_max_steps]:
                if not isinstance(item, dict) or item.get("name") not in allowed:
                    continue
                name = str(item["name"])
                needs_confirmation = bool(item.get("requires_confirmation")) or name == "create_lesson_draft"
                result.append(ToolCall(name, str(item.get("reason") or "完成当前目标"), needs_confirmation))
            return result or None
        except Exception as exc:
            logger.warning("agent_planner_llm_fallback reason=%s", str(exc) or type(exc).__name__)
            return None

    def plan(self, question: str, role: str, context: AiWorkspaceContextData) -> list[ToolCall]:
        deterministic = self._deterministic_plan(question, role)
        # 备课、任务、资料检索等明确目标已有可审计的安全路径。先直接采用它们，
        # 不能让一次外部模型规划调用卡住整个 SSE 首屏；大模型仅用于模糊问题的
        # 工具补充与最终结果归纳。
        calls = deterministic if len(deterministic) > 1 else (self._llm_plan(question, role, context) or deterministic)
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
        if len(results) > 1 or not settings.agent_planner_use_llm or settings.ai_mock_mode or not settings.llm_api_key:
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
        model = ChatOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            temperature=0.2,
            timeout=min(settings.llm_timeout_seconds, 12),
            streaming=True,
        )
        emitted = False
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
                    emitted = True
                    yield text
        except Exception as exc:
            logger.warning("agent_summary_llm_failed reason=%s", str(exc) or type(exc).__name__)
        if not emitted:
            yield fallback

    def invoke(
        self,
        call: ToolCall,
        *,
        question: str,
        role: str,
        context: AiWorkspaceContextData,
    ) -> ToolResult:
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
            return ToolResult(
                f"已锁定《{context.course_name}》·{context.chapter_title}"
                + (f"·教学班：{context.teaching_class_name}" if context.teaching_class_name else ""),
                data={"grounded": True},
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
        if call.name == "search_materials":
            if not context.course_id:
                return ToolResult(
                    "尚未锁定教材，无法检索教材与权威资料。",
                    action={"kind": "select_context", "label": "选择教材专题", "href": "/courses", "requires_confirmation": False},
                    data={"grounded": False},
                )
            try:
                chunks = retrieve(
                    question,
                    course_id=context.course_id,
                    chapter_id=context.chapter_id,
                    top_k=5,
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
                return ToolResult(f"备课草稿创建失败：{run.error_message or '证据包构建失败'}")
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
            return ToolResult(
                f"## 课后学习任务草案\n\n**任务名称：**《{context.chapter_title}》观点辨析与学习反思\n\n"
                f"**适用范围：**当前教材专题{class_hint}\n\n"
                "**学生提交：**300—500 字学习反思或观点卡，写明一个核心观点、至少一处教材依据和一条待讨论问题。\n\n"
                "**完成标准：**观点相关、依据可核验、表达清楚。\n\n"
                "**教师待确认：**发布对象、截止时间、提交形式和评分权重。",
                action={"kind": "open_assignments", "label": "进入教学任务设置", "href": "/assignments", "requires_confirmation": True},
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
            return ToolResult(
                f"《{context.chapter_title}》批改量规草案：\n\n"
                "1. 教材理解（40%）：能准确表述核心概念，并说明概念之间的关系。\n"
                "2. 论证与依据（35%）：至少引用一处可核验教材依据，观点与依据一致。\n"
                "3. 联系实际（15%）：围绕具体问题形成有边界的分析，不泛化表态。\n"
                "4. 表达规范（10%）：结构完整、语言准确、引用位置清楚。\n\n"
                "反馈模板：先指出学生已把握的观点，再说明需补充的教材依据，最后给出一项可执行的修改建议。"
                "该草案不会自动评分或发布。",
                action={"kind": "open_assignments", "label": "在教学任务中确认量规", "href": "/assignments", "requires_confirmation": True},
                data={"rubric_ready": True, "chapter_id": context.chapter_id},
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
                return ToolResult("未识别到具体教材专题，暂不能启动备考工作流。")
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
            return ToolResult(
                f"已找到当前专题的已确认课纲，准备生成：{'、'.join(output_types)}。",
                action={
                    "kind": "generate_artifacts",
                    "label": f"开始生成{'全部教学成果' if len(output_types) > 1 else output_types[0]}",
                    "href": "",
                    "run_id": latest.id,
                    "output_types": output_types,
                    "requires_confirmation": False,
                },
                data={"run_id": latest.id, "output_types": output_types},
            )
        return ToolResult("工具未返回结果。")

from __future__ import annotations
from uuid import uuid4

from datetime import datetime
import json
import logging
from pathlib import Path
import re
from typing import Any

from fastapi import HTTPException, status
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from sqlalchemy import Engine, or_, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.prompts import (
    LESSON_ARTIFACT_SYSTEM_PROMPT,
    LESSON_ARTIFACT_USER_PROMPT,
    LESSON_PREP_SYSTEM_PROMPT,
    LESSON_PREP_USER_PROMPT,
    STAGE_INSTRUCTIONS,
    STAGE_LABELS,
)
from app.services.llm_compat import clean_model_text
from app.models.agent_run import AgentRun, AgentStep
from app.models.chapter import Chapter
from app.models.course import Course
from app.models.teaching_class import TeachingClass, TeachingClassTeacher
from app.models.user import User
from app.schemas.agent import (
    AgentArtifactRequest,
    AgentRunCreate,
    AgentRunData,
    AgentStepData,
    PptSlideRevisionRequest,
    PptImageRevisionRequest,
    PptPreferences,
)
from app.schemas.ai import AiAssistData, AiAssistRequest
from app.services.ai_service import AiService
from app.services.ai_operation_service import AiProviderConfigService, build_chat_model
from app.services.presentation_artifact_service import PresentationArtifactService
from app.services.presentation_template_service import PresentationTemplateService
from app.services.ppt_workflow_service import PptWorkflowService, PptWorkflowCancelled
from app.services.ppt_native_service import safe_artifact_path
from app.services.lesson_artifact_state import requires_previous_confirmation


logger = logging.getLogger(__name__)

STEP_DEFINITIONS = [
    ("set_context", "设置任务"),
    ("build_evidence", "构建证据"),
    ("generate_outline", "生成课纲"),
    ("generate_artifacts", "生成成果"),
    ("preview_publish", "预览发布"),
]


def _now() -> datetime:
    # AgentRun/AgentStep are legacy local-wall-time columns without a marker.
    # Keep their write basis stable so old and new rows remain comparable.
    return datetime.now()


def _local_now_iso() -> str:
    """Return a new protocol timestamp with the host's actual UTC offset."""
    return datetime.now().astimezone().isoformat()


def _local_protocol_timestamp(value: Any) -> Any:
    """Expose legacy agent wall clocks with their host offset, without rewriting rows."""
    if not isinstance(value, str) or not value:
        return value
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return (parsed.astimezone() if parsed.tzinfo is None else parsed).isoformat()




def _invoke_streaming_text(
    prompt: ChatPromptTemplate,
    model: ChatOpenAI,
    variables: dict[str, str],
) -> str:
    """优先流式读取；兼容接口空流或中断时自动改用完整响应重试一次。"""
    last_error: Exception | None = None
    for attempt in range(2):
        chunks: list[str] = []
        try:
            for chunk in (prompt | model | StrOutputParser()).stream(variables):
                if chunk:
                    chunks.append(chunk)
            result = clean_model_text("".join(chunks))
            if result:
                return result
            last_error = RuntimeError("流式响应为空")
        except Exception as exc:  # 兼容部分 OpenAI 协议网关的偶发中断
            last_error = exc
        logger.warning(
            "llm_stream_attempt_failed attempt=%s model=%s reason=%s",
            attempt + 1,
            getattr(model, "model_name", "unknown"),
            str(last_error) or type(last_error).__name__,
        )

    # 有些兼容网关会建立 SSE 连接却不下发 token；此时非流式 invoke 更稳定。
    try:
        response = (prompt | model).invoke(variables)
        content = getattr(response, "content", response)
        if isinstance(content, str):
            result = clean_model_text(content)
        elif isinstance(content, list):
            result = clean_model_text("".join(
                str(item.get("text", "")) if isinstance(item, dict) else str(item)
                for item in content
            ))
        else:
            result = clean_model_text(content)
        if result:
            logger.info("llm_stream_fallback_succeeded model=%s", getattr(model, "model_name", "unknown"))
            return result
    except Exception as exc:
        last_error = exc
        logger.warning(
            "llm_non_stream_fallback_failed model=%s reason=%s",
            getattr(model, "model_name", "unknown"),
            str(exc) or type(exc).__name__,
        )

    reason = str(last_error).strip() if last_error else "未知原因"
    # Keep the provider's actionable reason (for example context overflow or
    # an empty SSE body) in the run record.  The old generic message made the
    # frontend look like a transport failure and hid the real diagnosis.
    raise RuntimeError(f"大模型未返回有效内容：{reason[:500]}") from last_error


def _invoke_non_streaming_text(
    prompt: ChatPromptTemplate,
    model: ChatOpenAI,
    variables: dict[str, str],
) -> str:
    """Invoke a structured-output model without relying on an SSE response.

    A number of compatible gateways return HTTP 200 for ``stream=true`` but
    emit no content.  PPT generation consumes one complete JSON document, so a
    normal response is both more reliable and easier to validate.
    """
    try:
        response = (prompt | model).invoke(variables)
        content = getattr(response, "content", response)
        if isinstance(content, str):
            result = clean_model_text(content)
        elif isinstance(content, list):
            result = clean_model_text("".join(
                str(item.get("text", "")) if isinstance(item, dict) else str(item)
                for item in content
            ))
        else:
            result = clean_model_text(content)
        if result:
            return result
        raise RuntimeError("模型非流式响应为空")
    except Exception as exc:
        logger.warning(
            "llm_non_streaming_call_failed model=%s reason=%s",
            getattr(model, "model_name", "unknown"),
            str(exc) or type(exc).__name__,
        )
        raise RuntimeError(f"大模型非流式调用失败：{str(exc)[:500]}") from exc


def _extract_json_object(raw: str, *, error_message: str) -> dict[str, Any]:
    """从模型可能附带说明或 Markdown 代码块的输出中安全提取首个 JSON 对象。"""
    candidate = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", raw.strip(), flags=re.I)
    decoder = json.JSONDecoder()
    for index, character in enumerate(candidate):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(candidate[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise RuntimeError(error_message)


class LessonOutlineGenerator:
    def __init__(self, db: Session | None = None, user_id: int | None = None) -> None:
        self.db = db
        self.user_id = user_id
        self.model_name = "mock" if settings.ai_mock_mode else AiProviderConfigService.resolve(db).model_name

    def generate(self, variables: dict[str, str]) -> dict[str, Any]:
        if settings.ai_mock_mode:
            total_minutes = max(45, int(variables["lesson_hours"]) * 45)
            introduction = max(8, round(total_minutes * 0.15))
            lecture = max(20, round(total_minutes * 0.5))
            discussion = total_minutes - introduction - lecture
            return {
                "title": f"{variables['chapter_title']}教学课纲",
                "positioning": "围绕当前教材专题建立理论结构，并通过已确认资料联系时代发展。",
                "objectives": {
                    "knowledge": ["理解专题核心概念、主要观点和论证逻辑"],
                    "ability": ["能够依据教材与权威资料分析现实问题"],
                    "values": ["形成理论联系实际、依据原文作出判断的学习习惯"],
                },
                "key_points": ["专题核心概念及其逻辑关系[资料1]"],
                "difficult_points": ["区分教材基本原理与补充材料中的实践说明"],
                "teaching_flow": [
                    {
                        "stage": "问题导入",
                        "duration_minutes": introduction,
                        "teacher_activity": "提出与专题主旨相关的现实问题，引导学生定位教材依据。",
                        "student_activity": "阅读证据摘要并形成初步判断。",
                        "evidence_refs": ["资料1"],
                    },
                    {
                        "stage": "理论讲授",
                        "duration_minutes": lecture,
                        "teacher_activity": "按照概念、观点和逻辑关系讲解专题内容。",
                        "student_activity": "记录知识结构并标注仍有疑问的概念。",
                        "evidence_refs": ["资料1"],
                    },
                    {
                        "stage": "讨论与总结",
                        "duration_minutes": discussion,
                        "teacher_activity": "组织观点辨析，依据原文归纳结论。",
                        "student_activity": "小组讨论并用资料编号说明依据。",
                        "evidence_refs": ["资料1"],
                    },
                ],
                "discussion_questions": ["本专题的核心观点如何回应当前实践问题？请说明教材依据。"],
                "after_class_task": "整理一张包含核心概念、教材依据和个人疑问的学习卡片。",
                "citation_notes": ["模拟模式仅用于验证流程，正式使用前请逐条核验引用。"],
            }
        prompt = ChatPromptTemplate.from_messages(
            [("system", LESSON_PREP_SYSTEM_PROMPT), ("human", LESSON_PREP_USER_PROMPT)]
        )
        model, _ = build_chat_model(feature="lesson_outline", db=self.db, user_id=self.user_id, streaming=True)
        raw = _invoke_streaming_text(prompt, model, variables)
        parsed = _extract_json_object(raw, error_message="模型未返回合法的课纲 JSON")
        if not isinstance(parsed, dict) or not parsed.get("title") or not parsed.get("teaching_flow"):
            raise RuntimeError("模型返回的课纲缺少必要字段")
        return parsed


class LessonArtifactGenerator:
    """Generate non-presentation artifacts only; PPT has its own v2 workflow."""

    def __init__(self, db: Session | None = None, user_id: int | None = None) -> None:
        self.db, self.user_id = db, user_id

    def generate(self, variables: dict[str, str]) -> dict[str, Any]:
        if settings.ai_mock_mode:
            outline = json.loads(variables["outline_json"])
            objectives = outline.get("objectives") or {}
            return {
                "lesson_plan": {
                    "title": f"{variables['chapter_title']}教学教案",
                    "overview": outline.get("positioning") or "",
                    "objectives": [value for key in ("knowledge", "ability", "values") for value in objectives.get(key, [])],
                    "preparation": ["核验教材引用位置", "准备课堂讨论材料"],
                    "procedures": outline.get("teaching_flow") or [],
                    "assessment": ["观察课堂讨论中的依据使用情况", "检查课后学习卡片"],
                    "homework": outline.get("after_class_task") or "",
                },
                "classroom_activities": [{
                    "title": "教材观点定位与小组辨析", "purpose": "训练依据教材表达观点",
                    "duration_minutes": 15, "format": "小组",
                    "instructions": ["阅读教材并标出关键词", "小组形成结论并注明依据", "交换观点并核验原文"],
                    "questions": outline.get("discussion_questions") or ["结合教材说明你的判断"],
                    "evidence_refs": ["资料1"], "evaluation": "结论准确、依据真实、表达清晰",
                }],
            }
        prompt = ChatPromptTemplate.from_messages([
            ("system", LESSON_ARTIFACT_SYSTEM_PROMPT), ("human", LESSON_ARTIFACT_USER_PROMPT),
        ])
        runtime = AiProviderConfigService.resolve(self.db)
        model, _ = build_chat_model(
            feature="lesson_artifacts", db=self.db, user_id=self.user_id,
            timeout=max(runtime.timeout_seconds, 120), max_tokens=8192, streaming=False,
        )
        raw = _invoke_non_streaming_text(prompt, model, variables)
        parsed = _extract_json_object(raw, error_message="模型未返回合法的教学成果 JSON")
        if not (parsed.get("lesson_plan") or parsed.get("classroom_activities")):
            raise RuntimeError("模型返回的教案和课堂活动为空")
        return parsed


class AgentService:
    def __init__(self, db: Session, user: User) -> None:
        self.db = db
        self.user = user

    @staticmethod
    def _ppt_path(run: AgentRun) -> str | None:
        return (((run.output_data or {}).get("artifacts") or {}).get("ppt") or {}).get("storage_path")

    def _commit_artifact_mutation(self, run: AgentRun, previous_path: str | None, *, image_job_id: str | None = None) -> None:
        """Compare-and-swap protects long model calls from stale overwrite.

        Uses SQLAlchemy JSON extraction supported by both SQLite and MySQL.
        The new file remains isolated if another operation wins the race.
        """
        current_path = AgentRun.output_data["artifacts"]["ppt"]["storage_path"].as_string()
        values = {key: getattr(run, key) for key in (
            "output_data", "input_data", "status", "current_step", "cancel_requested",
            "error_message", "finished_time", "prompt_version",
        )}
        with self.db.no_autoflush:
            result = self.db.execute(update(AgentRun).where(
                AgentRun.id == run.id,
                (AgentRun.status == "running") if image_job_id else AgentRun.status.not_in(["queued", "running"]),
                (AgentRun.output_data["ppt_image_job"]["id"].as_string() == image_job_id) if image_job_id else True,
                current_path == previous_path if previous_path else current_path.is_(None),
            ).values(**values).execution_options(synchronize_session=False))
        if result.rowcount != 1:
            self.db.rollback()
            raise HTTPException(status_code=409, detail="课件版本或任务状态已变化，请刷新后重试；未覆盖当前成果")
        self.db.expire(run)
        self.db.commit()
        self.db.refresh(run)

    @staticmethod
    def _public_ppt(ppt: dict) -> dict:
        """Use the same safe view for the current deck and immutable snapshots."""
        result = json.loads(json.dumps(ppt, ensure_ascii=False))
        for slide in result.get("slides") or []:
            slide["preview_available"] = bool(slide.get("preview_path"))
            slide.pop("preview_path", None)
            slide.pop("svg", None)
            if isinstance(slide.get("visual_asset"), dict):
                slide["visual_asset"].pop("storage_path", None)
        return result

    @staticmethod
    def _public_artifact(artifact: dict) -> dict:
        return {key: value for key, value in artifact.items() if key not in {"storage_path", "preview"}}

    @staticmethod
    def _version_metadata(version: dict, current_path: str | None) -> dict:
        artifact = version.get("artifact") or {}
        ppt = version.get("preview") or {}
        path = artifact.get("storage_path")
        unavailable = None
        if not path:
            unavailable = "仅保留内容快照，没有 PPT 文件"
        else:
            try:
                safe_artifact_path(path)
            except FileNotFoundError:
                unavailable = "PPT 文件已不存在"
        return {
            **{key: value for key, value in version.items() if key not in {"preview", "artifact"}},
            "revision_id": ppt.get("revision_id"),
            "generated_time": artifact.get("generated_time"),
            "restorable": unavailable is None,
            "unavailable_reason": unavailable,
            "is_current": bool(path and path == current_path),
        }

    @staticmethod
    def serialize(db: Session, run: AgentRun) -> AgentRunData:
        output_data = json.loads(json.dumps(run.output_data or {}, ensure_ascii=False))
        attempt = output_data.get("artifact_attempt")
        if isinstance(attempt, dict):
            for key in ("started_time", "finished_time"):
                if key in attempt:
                    attempt[key] = _local_protocol_timestamp(attempt[key])
        if isinstance(output_data.get("ppt_image_job"), dict):
            output_data["ppt_image_job"].pop("previous_path", None)
        for key, artifact in (output_data.get("artifacts") or {}).items():
            if isinstance(artifact, dict):
                artifact["requires_previous_confirmation"] = requires_previous_confirmation(run.output_data or {}, key)
                artifact.pop("storage_path", None)
                artifact.pop("preview", None)
        # Restoring a version used to archive the same file repeatedly. Collapse
        # those duplicate entries in the read view, without rewriting old data.
        versions, seen = [], set()
        for version in reversed(output_data.get("ppt_versions") or []):
            if not isinstance(version, dict):
                continue
            identity = (version.get("artifact") or {}).get("storage_path") or version.get("version_id")
            if identity in seen:
                continue
            seen.add(identity)
            versions.append(AgentService._version_metadata(version, AgentService._ppt_path(run)))
        output_data["ppt_versions"] = list(reversed(versions))
        ppt = ((output_data.get("artifact_bundle") or {}).get("ppt") or {})
        if ppt:
            output_data["artifact_bundle"]["ppt"] = AgentService._public_ppt(ppt)
        steps = db.scalars(
            select(AgentStep).where(AgentStep.run_id == run.id).order_by(AgentStep.step_order)
        ).all()
        return AgentRunData(
            id=run.id,
            created_by=run.created_by,
            agent_type=run.agent_type,
            status=run.status,
            course_id=run.course_id,
            chapter_id=run.chapter_id,
            teaching_class_id=run.teaching_class_id,
            current_step=run.current_step,
            input_data=run.input_data,
            evidence_snapshot=run.evidence_snapshot,
            output_data=output_data,
            model_name=run.model_name,
            prompt_version=run.prompt_version,
            error_message=run.error_message,
            cancel_requested=run.cancel_requested,
            retry_of_run_id=run.retry_of_run_id,
            started_time=run.started_time,
            finished_time=run.finished_time,
            created_time=run.created_time,
            updated_time=run.updated_time,
            steps=[
                AgentStepData(
                    id=item.id,
                    step_key=item.step_key,
                    title=item.title,
                    step_order=item.step_order,
                    status=item.status,
                    output_data=item.output_data,
                    error_message=item.error_message,
                    started_time=item.started_time,
                    finished_time=item.finished_time,
                )
                for item in steps
            ],
        )

    def _get_owned(self, run_id: int) -> AgentRun:
        run = self.db.get(AgentRun, run_id)
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="智能任务不存在")
        if self.user.role != "admin" and run.created_by != self.user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权查看该智能任务")
        return run

    def _validate_context(self, payload: AgentRunCreate) -> tuple[Course, Chapter]:
        course = self.db.get(Course, payload.course_id)
        chapter = self.db.get(Chapter, payload.chapter_id)
        if course is None or chapter is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="课程或专题不存在")
        if chapter.course_id != course.id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="专题不属于当前课程")
        if payload.teaching_class_id is not None:
            teaching_class = self.db.get(TeachingClass, payload.teaching_class_id)
            if teaching_class is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="教学班不存在")
            if self.user.role == "teacher":
                allowed = self.db.scalar(
                    select(TeachingClass.id)
                    .outerjoin(
                        TeachingClassTeacher,
                        TeachingClassTeacher.teaching_class_id == TeachingClass.id,
                    )
                    .where(
                        TeachingClass.id == teaching_class.id,
                        or_(
                            TeachingClass.owner_id == self.user.id,
                            TeachingClassTeacher.user_id == self.user.id,
                        ),
                    )
                )
                if allowed is None:
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权使用该教学班")
        return course, chapter

    def create(self, payload: AgentRunCreate, *, retry_of: int | None = None) -> AgentRunData:
        course, chapter = self._validate_context(payload)
        input_data = payload.input.model_dump()
        run = AgentRun(
            created_by=self.user.id,
            agent_type=payload.agent_type,
            status="running",
            course_id=course.id,
            chapter_id=chapter.id,
            teaching_class_id=payload.teaching_class_id,
            current_step=0,
            input_data=input_data,
            model_name="mock" if settings.ai_mock_mode else AiProviderConfigService.resolve(self.db).model_name,
            retry_of_run_id=retry_of,
            started_time=_now(),
        )
        self.db.add(run)
        self.db.flush()
        steps: list[AgentStep] = []
        for order, (key, title) in enumerate(STEP_DEFINITIONS):
            step = AgentStep(
                run_id=run.id,
                step_key=key,
                title=title,
                step_order=order,
                status="pending",
            )
            self.db.add(step)
            steps.append(step)
        now = _now()
        steps[0].status = "completed"
        steps[0].started_time = now
        steps[0].finished_time = now
        steps[0].output_data = {
            "course_name": course.name,
            "chapter_title": chapter.title,
            **input_data,
        }
        steps[1].status = "running"
        steps[1].started_time = now
        self.db.flush()
        try:
            prepared = AiService(self.db, user=self.user)._prepare(
                AiAssistRequest(
                    course_id=course.id,
                    chapter_id=chapter.id,
                    learning_stage=payload.input.learning_stage,
                    task_type="chapter_summary",
                    question="为教师备课构建本专题证据包",
                )
            )
            if isinstance(prepared, AiAssistData):
                raise ValueError(prepared.answer)
            variables, sources, _ = prepared
            run.evidence_snapshot = [item.model_dump(mode="json") for item in sources]
            run.context_snapshot = variables["chapter_content"]
            run.status = "waiting_confirmation"
            run.current_step = 1
            steps[1].status = "completed"
            steps[1].finished_time = _now()
            steps[1].output_data = {"evidence_count": len(sources)}
        except Exception as exc:
            run.status = "failed"
            run.error_message = str(exc)
            run.finished_time = _now()
            steps[1].status = "failed"
            steps[1].error_message = str(exc)
            steps[1].finished_time = _now()
        self.db.commit()
        self.db.refresh(run)
        return self.serialize(self.db, run)

    def request_ppt_image_revision(self, run_id: int, slide_index: int,
                                   request: PptImageRevisionRequest) -> AgentRunData:
        run = self._get_owned(run_id)
        if run.status in {"queued", "running"}:
            raise HTTPException(status_code=409, detail="当前任务仍在执行")
        ppt = ((run.output_data or {}).get("artifact_bundle") or {}).get("ppt") or {}
        if ppt.get("revision_id") != request.expected_revision:
            raise HTTPException(status_code=409, detail="课件版本已变化，请刷新后再换图")
        pages = ppt.get("slides") or []
        if not 0 <= slide_index < len(pages):
            raise HTTPException(status_code=404, detail="PPT 页面不存在")
        if ppt.get("pipeline_version") != "ppt-master-svg-v2" or "visual-asset" not in pages[slide_index].get("svg", ""):
            raise HTTPException(status_code=409, detail="本页没有可替换的插图槽位，请使用修改本页")
        previous_path = self._ppt_path(run)
        run.output_data = {**(run.output_data or {}), "ppt_image_job": {"id": uuid4().hex,
            "status": "queued", "slide_index": slide_index, "prompt": request.prompt.strip(),
            "previous_path": previous_path, "started_time": _local_now_iso()}}
        run.status, run.cancel_requested, run.error_message = "queued", False, None
        run.finished_time = None
        self._commit_artifact_mutation(run, previous_path)
        return self.serialize(self.db, run)

    def get(self, run_id: int) -> AgentRunData:
        return self.serialize(self.db, self._get_owned(run_id))

    def list(self, limit: int = 30) -> list[AgentRunData]:
        query = select(AgentRun).order_by(AgentRun.id.desc()).limit(limit)
        if self.user.role != "admin":
            query = query.where(AgentRun.created_by == self.user.id)
        return [self.serialize(self.db, item) for item in self.db.scalars(query).all()]

    def approve_evidence(self, run_id: int) -> AgentRunData:
        run = self._get_owned(run_id)
        if run.status != "waiting_confirmation":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="当前任务不等待证据确认")
        if not run.evidence_snapshot or not run.context_snapshot:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="证据快照不完整")
        step = self.db.scalar(
            select(AgentStep).where(
                AgentStep.run_id == run.id,
                AgentStep.step_key == "generate_outline",
            )
        )
        if step is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="任务步骤不完整")
        run.status = "queued"
        run.current_step = 2
        step.status = "queued"
        self.db.commit()
        self.db.refresh(run)
        return self.serialize(self.db, run)

    def request_artifacts(self, run_id: int, payload: AgentArtifactRequest) -> AgentRunData:
        run = self._get_owned(run_id)
        previous_path = self._ppt_path(run)
        if not (run.output_data or {}).get("outline"):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="请先生成并核验课纲")
        if run.status in {"queued", "running"}:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="当前任务仍在执行")
        step = self.db.scalar(
            select(AgentStep).where(
                AgentStep.run_id == run.id,
                AgentStep.step_key == "generate_artifacts",
            )
        )
        if step is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="任务步骤不完整")
        output_types = list(dict.fromkeys(payload.output_types))
        previous_preferences = (run.input_data or {}).get("ppt_preferences") or {}
        ppt_preferences = (
            (payload.ppt_preferences or PptPreferences.model_validate(previous_preferences)).model_dump()
            if "ppt" in output_types else previous_preferences
        )
        if ppt_preferences and ppt_preferences["min_slides"] > ppt_preferences["max_slides"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="PPT 最少页数不能大于最多页数",
            )
        template_reference = PresentationTemplateService(self.db, self.user).prompt_reference(
            ppt_preferences.get("template_id") if ppt_preferences else None
        )
        if "ppt" in output_types:
            self._archive_ppt_version(run, "重新生成整套 PPT")
        run.status = "queued"
        run.current_step = 3
        run.cancel_requested = False
        run.error_message = None
        run.finished_time = None
        run.prompt_version = "lesson-artifacts-svg-v2"
        input_data = dict(run.input_data or {})
        input_data["artifact_output_types"] = output_types
        input_data["ppt_preferences"] = ppt_preferences
        input_data["ppt_template_reference"] = template_reference
        input_data["ppt_resume_requested"] = payload.resume
        run.input_data = input_data
        output_data = dict(run.output_data or {})
        output_data["artifact_errors"] = {key: value for key, value in (output_data.get("artifact_errors") or {}).items() if key not in output_types}
        output_data["artifacts"] = {
            key: {**value, "retained_from_previous_attempt": True} if key in output_types else value
            for key, value in (output_data.get("artifacts") or {}).items()
        }
        output_data.pop("ppt_image_job", None)
        output_data["artifact_attempt"] = {"id": uuid4().hex, "status": "queued", "resume": payload.resume,
            "requested_types": output_types, "started_time": _local_now_iso()}
        run.output_data = output_data
        step.status = "queued"
        step.input_data = {
            "output_types": output_types,
            "ppt_preferences": ppt_preferences,
            "template_reference": template_reference,
            "resume": payload.resume,
        }
        step.output_data = {}
        step.error_message = None
        step.started_time = None
        step.finished_time = None
        self._commit_artifact_mutation(run, previous_path)
        return self.serialize(self.db, run)

    def artifact_download(
        self, run_id: int, artifact_key: str, version_id: str | None = None,
        expected_revision: str | None = None,
    ) -> tuple[Path, dict[str, Any]]:
        run = self._get_owned(run_id)
        if version_id:
            if artifact_key != "ppt":
                raise HTTPException(status_code=400, detail="历史版本仅适用于 PPT")
            artifact = self._ppt_version(run, version_id).get("artifact")
        else:
            self._check_ppt_revision(run, expected_revision if artifact_key == "ppt" else None)
            artifact = ((run.output_data or {}).get("artifacts") or {}).get(artifact_key)
        if not isinstance(artifact, dict):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="教学成果不存在")
        try:
            path = PresentationArtifactService(run.id).resolve_download(artifact)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return path, artifact

    @staticmethod
    def _archive_ppt_version(run: AgentRun, reason: str) -> None:
        output_data = dict(run.output_data or {})
        bundle = output_data.get("artifact_bundle") or {}
        ppt_data = bundle.get("ppt") if isinstance(bundle, dict) else None
        if not isinstance(ppt_data, dict) or not ppt_data.get("slides"):
            return
        versions = list(output_data.get("ppt_versions") or [])
        current_path = AgentService._ppt_path(run)
        # Preserve one snapshot per immutable file, so repeated restores do not
        # evict real revisions from the ten-version undo history.
        if current_path:
            versions = [item for item in versions if (item.get("artifact") or {}).get("storage_path") != current_path]
        versions.append(
            {
                "version_id": _now().strftime("%Y%m%d%H%M%S%f"),
                "created_time": _local_now_iso(),
                "reason": reason,
                "title": ppt_data.get("title") or "教学 PPT",
                "slide_count": len(ppt_data.get("slides") or []),
                "design_name": (ppt_data.get("design") or {}).get("name"),
                "preview": json.loads(json.dumps(ppt_data, ensure_ascii=False)),
                "artifact": {
                    key: value for key, value in (output_data.get("artifacts", {}).get("ppt") or {}).items()
                    if key != "preview"
                },
            }
        )
        output_data["ppt_versions"] = versions[-10:]
        run.output_data = output_data

    def _save_updated_ppt(self, run: AgentRun, ppt_data: dict[str, Any], artifact: dict) -> None:
        output_data = dict(run.output_data or {})
        if (output_data.get("ppt_image_job") or {}).get("status") not in {"queued", "running"}:
            output_data.pop("ppt_image_job", None)
        bundle = dict(output_data.get("artifact_bundle") or {})
        artifacts = dict(output_data.get("artifacts") or {})
        bundle["ppt"] = ppt_data
        artifacts["ppt"] = {**artifact, "retained_from_previous_attempt": False}
        output_data["artifact_errors"] = {key: value for key, value in (output_data.get("artifact_errors") or {}).items() if key != "ppt"}
        output_data["artifact_bundle"] = bundle
        output_data["artifacts"] = artifacts
        run.output_data = output_data

    def revise_ppt_slide(
        self,
        run_id: int,
        slide_index: int,
        request: PptSlideRevisionRequest,
    ) -> AgentRunData:
        run = self._get_owned(run_id)
        previous_path = self._ppt_path(run)
        if run.status in {"queued", "running"}:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="当前任务仍在执行")
        ppt_data = json.loads(
            json.dumps(
                ((run.output_data or {}).get("artifact_bundle") or {}).get("ppt"),
                ensure_ascii=False,
            )
        )
        if not isinstance(ppt_data, dict) or not ppt_data.get("slides"):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="尚未生成 PPT")
        if not 0 <= slide_index < len(ppt_data["slides"]):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PPT 页面不存在")
        course = self.db.get(Course, run.course_id)
        chapter = self.db.get(Chapter, run.chapter_id)
        if course is None or chapter is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="课程或专题已不存在")
        try:
            if ppt_data.get("pipeline_version") != "ppt-master-svg-v2":
                raise HTTPException(status_code=409, detail="旧版课件继续支持下载；请重新生成新版后进行单页修改")
            artifact, revised = PptWorkflowService(self.db, self.user.id, run.id).revise(
                ppt_data, slide_index, request, run.evidence_snapshot or [],
            )
            self._archive_ppt_version(run, f"修改第 {slide_index + 1} 页前")
            self._save_updated_ppt(run, revised, artifact)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"本页重新生成失败：{exc}",
            ) from exc
        self._commit_artifact_mutation(run, previous_path)
        return self.serialize(self.db, run)

    @staticmethod
    def _ppt_version(run: AgentRun, version_id: str) -> dict:
        versions = list((run.output_data or {}).get("ppt_versions") or [])
        target = next(
            (item for item in versions if str(item.get("version_id")) == version_id),
            None,
        )
        if target is None or not isinstance(target.get("preview"), dict):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PPT 历史版本不存在")
        return target

    @staticmethod
    def _check_ppt_revision(run: AgentRun, expected_revision: str | None) -> None:
        current = ((run.output_data or {}).get("artifact_bundle") or {}).get("ppt") or {}
        if expected_revision is not None and expected_revision != (current.get("revision_id") or ""):
            raise HTTPException(status_code=409, detail="当前课件已变化，请刷新版本列表后重试；未覆盖任何成果")

    def ppt_version(self, run_id: int, version_id: str) -> dict:
        """Read-only history: selecting a snapshot must never restore it."""
        run = self._get_owned(run_id)
        target = self._ppt_version(run, version_id)
        return {
            **self._version_metadata(target, self._ppt_path(run)),
            "ppt": self._public_ppt(target["preview"]),
            "artifact": self._public_artifact(target.get("artifact") or {}),
        }

    def restore_ppt_version(
        self, run_id: int, version_id: str, expected_revision: str | None = None,
    ) -> AgentRunData:
        run = self._get_owned(run_id)
        previous_path = self._ppt_path(run)
        if run.status in {"queued", "running"}:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="当前任务仍在执行")
        self._check_ppt_revision(run, expected_revision)
        target = self._ppt_version(run, version_id)
        artifact = target.get("artifact") or {}
        if not artifact.get("storage_path"):
            raise HTTPException(status_code=409, detail="该旧版本仅有内容快照，没有可恢复文件；请基于该内容重新生成")
        try:
            safe_artifact_path(artifact["storage_path"])
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="历史版本文件不存在，当前版本保持不变") from exc
        if artifact["storage_path"] == previous_path:
            return self.serialize(self.db, run)
        self._archive_ppt_version(run, "切换版本前自动保存")
        self._save_updated_ppt(
            run,
            json.loads(json.dumps(target["preview"], ensure_ascii=False)),
            json.loads(json.dumps(artifact, ensure_ascii=False)),
        )
        self._commit_artifact_mutation(run, previous_path)
        return self.serialize(self.db, run)

    def ppt_preview(
        self, run_id: int, slide_index: int, version_id: str | None = None,
        expected_revision: str | None = None,
    ) -> Path:
        run = self._get_owned(run_id)
        if version_id:
            ppt = self._ppt_version(run, version_id)["preview"]
        else:
            self._check_ppt_revision(run, expected_revision)
            ppt = ((run.output_data or {}).get("artifact_bundle") or {}).get("ppt") or {}
        pages = ppt.get("slides") or []
        if not 0 <= slide_index < len(pages):
            raise HTTPException(status_code=404, detail="课件页面不存在")
        path = pages[slide_index].get("preview_path")
        if not path:
            raise HTTPException(status_code=404, detail="此历史课件没有成品预览，请下载查看")
        try:
            return safe_artifact_path(path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="课件预览文件不存在") from exc

    def cancel(self, run_id: int) -> AgentRunData:
        run = self._get_owned(run_id)
        if run.status in {"completed", "failed", "cancelled"}:
            return self.serialize(self.db, run)
        run.cancel_requested = True
        if run.status in {"queued", "waiting_confirmation"}:
            run.status = "cancelled"
            run.finished_time = _now()
            if (run.output_data or {}).get("ppt_image_job"):
                run.output_data = {**run.output_data, "ppt_image_job": {**run.output_data["ppt_image_job"], "status": "cancelled"}}
        self.db.commit()
        self.db.refresh(run)
        return self.serialize(self.db, run)

    def retry(self, run_id: int) -> AgentRunData:
        previous = self._get_owned(run_id)
        if previous.status not in {"failed", "cancelled"}:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="只有失败或已取消任务可以重试")
        payload = AgentRunCreate(
            agent_type="teacher_lesson_prep",
            course_id=previous.course_id,
            chapter_id=previous.chapter_id,
            teaching_class_id=previous.teaching_class_id,
            input=previous.input_data,
        )
        return self.create(payload, retry_of=previous.id)


def execute_lesson_outline(run_id: int, bind: Engine) -> None:
    """后台生成课纲；使用独立 Session，避免占用请求数据库会话。"""
    with Session(bind=bind, autoflush=False, expire_on_commit=False) as db:
        run = db.get(AgentRun, run_id)
        if run is None or run.status not in {"queued", "running"}:
            return
        step = db.scalar(
            select(AgentStep).where(
                AgentStep.run_id == run.id,
                AgentStep.step_key == "generate_outline",
            )
        )
        if step is None:
            return
        if run.cancel_requested:
            run.status = "cancelled"
            run.finished_time = _now()
            db.commit()
            return
        run.status = "running"
        step.status = "running"
        step.started_time = _now()
        db.commit()
        try:
            course = db.get(Course, run.course_id)
            chapter = db.get(Chapter, run.chapter_id)
            if course is None or chapter is None:
                raise RuntimeError("课程或专题已不存在")
            input_data = run.input_data
            learning_stage = str(input_data.get("learning_stage") or "preview")
            learning_stage_label = STAGE_LABELS.get(learning_stage, STAGE_LABELS["preview"])
            outline = LessonOutlineGenerator(db, run.created_by).generate(
                {
                    "course_name": course.name,
                    "chapter_title": chapter.title,
                    "learning_stage_label": learning_stage_label,
                    "learning_stage_instructions": STAGE_INSTRUCTIONS[learning_stage_label],
                    "lesson_hours": str(input_data.get("lesson_hours", 2)),
                    "student_level": str(input_data.get("student_level", "本科生")),
                    "completion_condition": str(input_data.get("completion_condition") or "教材阅读"),
                    "teaching_goal": str(input_data.get("teaching_goal") or "按教材要求完成本专题教学"),
                    "evidence_context": run.context_snapshot or "",
                }
            )
            db.refresh(run)
            if run.cancel_requested:
                run.status = "cancelled"
                run.finished_time = _now()
                step.status = "cancelled"
            else:
                run.output_data = {"outline": outline}
                run.status = "completed"
                run.current_step = 2
                run.finished_time = _now()
                step.status = "completed"
                step.output_data = {"title": outline.get("title", "课纲草稿")}
                step.finished_time = _now()
                artifact_step = db.scalar(
                    select(AgentStep).where(
                        AgentStep.run_id == run.id,
                        AgentStep.step_key == "generate_artifacts",
                    )
                )
                if artifact_step is not None:
                    artifact_step.status = "pending"
            db.commit()
        except Exception as exc:
            logger.exception("lesson prep agent failed run_id=%s", run_id)
            run.status = "failed"
            run.error_message = str(exc)
            run.finished_time = _now()
            step.status = "failed"
            step.error_message = str(exc)
            step.finished_time = _now()
            db.commit()


def execute_lesson_artifacts(run_id: int, bind: Engine) -> None:
    """后台生成课件、教案与课堂活动，并渲染为可下载文件。"""
    with Session(bind=bind, autoflush=False, expire_on_commit=False) as db:
        run = db.get(AgentRun, run_id)
        if run is None or run.status not in {"queued", "running"}:
            return
        step = db.scalar(
            select(AgentStep).where(
                AgentStep.run_id == run.id,
                AgentStep.step_key == "generate_artifacts",
            )
        )
        if step is None:
            return
        if run.cancel_requested:
            run.status = "cancelled"
            run.finished_time = _now()
            step.status = "cancelled"
            step.finished_time = _now()
            db.commit()
            return
        run.status = "running"
        step.status = "running"
        step.started_time = _now()
        db.commit()
        try:
            course = db.get(Course, run.course_id)
            chapter = db.get(Chapter, run.chapter_id)
            outline = (run.output_data or {}).get("outline")
            if course is None or chapter is None or not isinstance(outline, dict):
                raise RuntimeError("课程、专题或课纲已不存在")
            requested = list(
                dict.fromkeys((run.input_data or {}).get("artifact_output_types") or [])
            )
            if not requested:
                raise RuntimeError("未选择需要生成的教学成果")
            evidence_context = "\n\n".join(
                f"[资料{index}] {item.get('source_title') or '课程资料'}\n"
                f"{item.get('position') or ''}\n{item.get('excerpt') or ''}"
                for index, item in enumerate(run.evidence_snapshot or [], start=1)
            )
            variables = {
                "course_name": course.name,
                "chapter_title": chapter.title,
                "lesson_hours": str((run.input_data or {}).get("lesson_hours", 2)),
                "student_level": str((run.input_data or {}).get("student_level", "本科生")),
                "teaching_goal": str((run.input_data or {}).get("teaching_goal") or "按已确认课纲完成本专题教学"),
                "output_types": "、".join(item for item in requested if item != "ppt"),
                "outline_json": json.dumps(outline, ensure_ascii=False),
                "evidence_context": evidence_context,
                "ppt_preferences": json.dumps((run.input_data or {}).get("ppt_preferences") or {}, ensure_ascii=False),
                "template_reference": json.dumps((run.input_data or {}).get("ppt_template_reference") or {}, ensure_ascii=False),
            }
            renderer = PresentationArtifactService(run.id)
            generated: dict[str, Any] = {}
            artifacts: dict[str, Any] = {}
            successful_types: list[str] = []
            artifact_errors: dict[str, str] = {}

            ppt_workflow = None
            def report_progress(stage: str, completed: int, total: int) -> None:
                db.refresh(run)
                if run.cancel_requested:
                    raise PptWorkflowCancelled("已取消课件生成")
                step.output_data = {
                    **(step.output_data or {}),
                    "ppt_workflow": {"stage": stage, "completed_pages": completed, "total_pages": total,
                        "resume": dict(ppt_workflow.resume_info) if ppt_workflow else {}},
                }
                output = dict(run.output_data or {})
                output["artifact_attempt"] = {**(output.get("artifact_attempt") or {}), "status": "running"}
                run.output_data = output
                db.commit()

            if "ppt" in requested:
                try:
                    ppt_workflow = PptWorkflowService(db, run.created_by, run.id, progress=report_progress)
                    options = {"resume": True} if (run.input_data or {}).get("ppt_resume_requested") else {}
                    artifacts["ppt"], generated["ppt"] = ppt_workflow.generate(variables, run.evidence_snapshot or [], **options)
                    successful_types.append("ppt")
                except PptWorkflowCancelled:
                    raise
                except Exception as exc:
                    logger.exception("lesson artifact ppt failed run_id=%s", run_id)
                    artifact_errors["ppt"] = str(exc) or type(exc).__name__
            if any(key != "ppt" for key in requested):
                try:
                    generated.update(LessonArtifactGenerator(db, run.created_by).generate(variables))
                except Exception as exc:
                    logger.exception("non-ppt lesson artifacts failed run_id=%s", run_id)
                    artifact_errors.update({key: str(exc) or type(exc).__name__ for key in requested if key != "ppt"})
            if "lesson_plan" in requested:
                try:
                    lesson_plan = generated.get("lesson_plan")
                    if not isinstance(lesson_plan, dict):
                        raise RuntimeError("模型没有返回可用的教案结构")
                    artifacts["lesson_plan"] = renderer.render_lesson_plan(
                        course_name=course.name,
                        chapter_title=chapter.title,
                        lesson_plan=lesson_plan,
                        evidence=run.evidence_snapshot or [],
                    )
                    successful_types.append("lesson_plan")
                except Exception as exc:
                    logger.exception("lesson artifact lesson_plan failed run_id=%s", run_id)
                    artifact_errors["lesson_plan"] = str(exc) or type(exc).__name__
            if "classroom_activities" in requested:
                try:
                    activities = generated.get("classroom_activities")
                    if not isinstance(activities, list) or not activities:
                        raise RuntimeError("模型没有返回可用的课堂活动")
                    artifacts["classroom_activities"] = renderer.render_activity_guide(
                        course_name=course.name,
                        chapter_title=chapter.title,
                        activities=activities,
                        evidence=run.evidence_snapshot or [],
                    )
                    successful_types.append("classroom_activities")
                except Exception as exc:
                    logger.exception("lesson artifact classroom_activities failed run_id=%s", run_id)
                    artifact_errors["classroom_activities"] = str(exc) or type(exc).__name__
            if not successful_types:
                detail = "；".join(
                    f"{key}: {message}" for key, message in artifact_errors.items()
                )
                raise RuntimeError(detail or "所有教学成果均生成失败")
            db.refresh(run)
            if run.cancel_requested:
                run.status = "cancelled"
                run.finished_time = _now()
                step.status = "cancelled"
            else:
                # 成果是可独立重试的。重新生成 PPT、教案或课堂活动时，
                # 只替换本次请求的类型，保留同一任务中已经成功的其它成果，
                # 避免用户为了补一份教案而丢失已经核验过的 PPT。
                output_data = dict(run.output_data or {})
                existing_bundle = dict(output_data.get("artifact_bundle") or {})
                existing_bundle.update(
                    {
                        key: value
                        for key, value in generated.items()
                        if key in successful_types
                    }
                )
                existing_artifacts = dict(output_data.get("artifacts") or {})
                existing_artifacts.update(artifacts)
                output_data["artifact_bundle"] = existing_bundle
                output_data["artifacts"] = existing_artifacts
                output_data["artifact_errors"] = artifact_errors
                output_data["artifact_success_types"] = successful_types
                visual = (generated.get("ppt") or {}).get("multimodal") or {}
                partial_images = visual.get("requested_count", 0) > visual.get("generated_count", 0)
                output_data["artifact_attempt"] = {**(output_data.get("artifact_attempt") or {}),
                    "status": "partial" if artifact_errors or partial_images else "completed",
                    "finished_time": _local_now_iso()}
                for artifact in artifacts.values():
                    artifact.setdefault("generated_time", _now().isoformat())
                    artifact["attempt_id"] = output_data["artifact_attempt"].get("id")
                    artifact["retained_from_previous_attempt"] = False
                run.output_data = output_data
                run.status = "completed"
                run.current_step = 3
                run.finished_time = _now()
                step.status = "failed" if artifact_errors else "completed"
                step.error_message = "；".join(artifact_errors.values()) or None
                step.output_data = {
                    **(step.output_data or {}),
                    "output_types": requested,
                    "artifact_count": len(artifacts),
                    "successful_types": successful_types,
                    "artifact_errors": artifact_errors,
                }
                step.finished_time = _now()
            db.commit()
        except PptWorkflowCancelled:
            run.status = "cancelled"
            run.finished_time = _now()
            step.status = "cancelled"
            step.finished_time = _now()
            db.commit()
        except Exception as exc:
            logger.exception("lesson artifact agent failed run_id=%s", run_id)
            failures = artifact_errors if "artifact_errors" in locals() else {"workflow": str(exc)}
            step.output_data = {**(step.output_data or {}), "artifact_errors": failures, "successful_types": []}
            run.output_data = {**(run.output_data or {}), "artifact_errors": failures, "artifact_success_types": []}
            run.output_data = {**run.output_data, "artifact_attempt": {
                **(run.output_data.get("artifact_attempt") or {}), "status": "failed", "finished_time": _local_now_iso()}}
            step.status = "failed"
            step.error_message = str(exc)
            step.finished_time = _now()
            # 成果是课纲后的可选步骤。课纲已存在时，不应因一次 PPT/教案生成
            # 失败而抹掉前序成功状态；保留可用课纲并允许教师只重试该成果。
            if isinstance((run.output_data or {}).get("outline"), dict):
                run.status = "completed"
                run.current_step = max(run.current_step or 0, 2)
                run.error_message = None
                run.finished_time = _now()
            else:
                run.status = "failed"
                run.error_message = str(exc)
                run.finished_time = _now()
            db.commit()


def execute_ppt_image_revision(run_id: int, job_id: str, bind: Engine) -> None:
    """A short HTTP enqueue, then isolated image replacement and verified export."""
    with Session(bind=bind, autoflush=False, expire_on_commit=False) as db:
        run = db.get(AgentRun, run_id)
        job = dict((run.output_data or {}).get("ppt_image_job") or {}) if run else {}
        if not run or run.status != "queued" or job.get("id") != job_id:
            return
        previous_path = job.get("previous_path")
        service = AgentService(db, db.get(User, run.created_by))
        run.status = "running"
        run.output_data = {**run.output_data, "ppt_image_job": {**job, "status": "running"}}
        db.commit()
        def progress(stage, done, total):
            db.refresh(run)
            if run.cancel_requested or run.status == "cancelled":
                raise PptWorkflowCancelled("已取消换图，原课件保持不变")
            if (run.output_data.get("ppt_image_job") or {}).get("id") != job_id:
                raise PptWorkflowCancelled("换图任务已变化")
            run.output_data = {**run.output_data, "ppt_image_job": {
                **run.output_data["ppt_image_job"], "stage": stage}}
            db.commit()
        try:
            original = ((run.output_data or {}).get("artifact_bundle") or {}).get("ppt")
            artifact, revised = PptWorkflowService(db, run.created_by, run.id, progress=progress).regenerate_image(
                original, job["slide_index"], job["prompt"], run.evidence_snapshot or [])
            db.refresh(run)
            service._archive_ppt_version(run, f"替换第 {job['slide_index']+1} 页插图前")
            service._save_updated_ppt(run, revised, artifact)
            output = dict(run.output_data)
            output["ppt_image_job"] = {**output["ppt_image_job"], "status": "completed", "finished_time": _local_now_iso()}
            output["artifact_errors"] = {key: value for key, value in (output.get("artifact_errors") or {}).items() if key != "ppt"}
            if output.get("artifact_attempt"):
                visual = revised.get("multimodal") or {}
                output["artifact_attempt"] = {**output["artifact_attempt"], "status": "partial" if output["artifact_errors"] or visual.get("requested_count", 0) > visual.get("generated_count", 0) else "completed"}
            run.output_data, run.status, run.finished_time = output, "completed", _now()
            service._commit_artifact_mutation(run, previous_path, image_job_id=job_id)
        except Exception as exc:
            db.rollback()
            db.refresh(run)
            live_job = (run.output_data or {}).get("ppt_image_job") or {}
            if live_job.get("id") != job_id or service._ppt_path(run) != previous_path:
                return
            cancelled = isinstance(exc, PptWorkflowCancelled)
            message = "已取消换图，原课件保持不变" if cancelled else str(exc)[:600]
            output = {**run.output_data, "ppt_image_job": {**live_job,
                "status": "cancelled" if cancelled else "failed", "error": message, "finished_time": _local_now_iso()}}
            db.execute(update(AgentRun).where(AgentRun.id == run.id,
                AgentRun.output_data["ppt_image_job"]["id"].as_string() == job_id,
                AgentRun.output_data["artifacts"]["ppt"]["storage_path"].as_string() == previous_path,
            ).values(output_data=output, status="cancelled" if cancelled else "completed", finished_time=_now()))
            db.commit()
            logger.warning("ppt_single_image_revision_failed run_id=%s cancelled=%s", run_id, cancelled)


def recover_agent_runs(bind: Engine) -> int:
    """进程重启后将失去执行器的任务转为可重试失败状态。"""
    with Session(bind=bind, autoflush=False, expire_on_commit=False) as db:
        runs = db.scalars(
            select(AgentRun).where(AgentRun.status.in_(["queued", "running"]))
        ).all()
        if not runs:
            return 0
        for run in runs:
            image_job = (run.output_data or {}).get("ppt_image_job") or {}
            if image_job.get("status") in {"queued", "running"}:
                run.output_data = {**run.output_data, "ppt_image_job": {**image_job,
                    "status": "failed", "error": "服务重启导致换图中断，原课件保持不变"}}
                run.status, run.finished_time = "completed", _now()
                continue
            run.status = "failed"
            run.error_message = "服务重启导致后台任务中断，请点击重新执行"
            run.finished_time = _now()
            if (run.output_data or {}).get("artifact_attempt"):
                run.output_data = {**run.output_data, "artifact_attempt": {
                    **run.output_data["artifact_attempt"], "status": "failed", "finished_time": _local_now_iso()}}
            step = db.scalar(
                select(AgentStep)
                .where(
                    AgentStep.run_id == run.id,
                    AgentStep.status.in_(["queued", "running"]),
                )
                .order_by(AgentStep.step_order)
            )
            if step is not None:
                step.status = "failed"
                step.error_message = run.error_message
                step.finished_time = _now()
        db.commit()
        return len(runs)

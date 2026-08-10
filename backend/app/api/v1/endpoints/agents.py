import json
from time import sleep
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.dependencies import require_roles
from app.core.config import settings
from app.db.session import get_db
from app.models.agent_run import AgentRun
from app.models.user import User
from app.schemas.agent import (
    AgentArtifactRequest,
    AgentConfirmRequest,
    AgentRunCreate,
    AgentRunData,
    AgentCapabilities,
    LessonPublicationData,
    LessonPublishRequest,
    PptSlideRevisionRequest,
    PptVersionRestoreRequest,
    PresentationTemplateData,
)
from app.schemas.common import ApiResponse, api_json_value
from app.services.agent_service import (
    AgentService,
    execute_lesson_artifacts,
    execute_lesson_outline,
)
from app.services.ai_operation_service import AiProviderConfigService
from app.services.presentation_template_service import PresentationTemplateService
from app.services.lesson_publication_service import LessonPublicationService


router = APIRouter(prefix="/agent", tags=["agent"])


@router.get("/capabilities", response_model=ApiResponse[AgentCapabilities])
def agent_capabilities(
    _: User = Depends(require_roles("teacher", "admin")),
    db: Session = Depends(get_db),
) -> ApiResponse[AgentCapabilities]:
    config = AiProviderConfigService.resolve_capability("image_generation", db)
    available = bool(
        config.enabled
        and config.api_key
        and config.base_url
        and config.model_name
    )
    return ApiResponse(
        data=AgentCapabilities(
            ppt_multimodal_available=available,
            ppt_multimodal_model=config.model_name if available else None,
            ppt_multimodal_max_images=settings.ppt_multimodal_max_images if available else 0,
        )
    )


@router.get("/ppt-templates", response_model=ApiResponse[list[PresentationTemplateData]])
def list_ppt_templates(
    user: User = Depends(require_roles("teacher", "admin")),
    db: Session = Depends(get_db),
) -> ApiResponse[list[PresentationTemplateData]]:
    return ApiResponse(data=PresentationTemplateService(db, user).list())


@router.post("/ppt-templates", response_model=ApiResponse[PresentationTemplateData])
async def upload_ppt_template(
    name: str = Form(..., min_length=1, max_length=120),
    description: str | None = Form(default=None, max_length=1000),
    is_shared: bool = Form(default=False),
    file: UploadFile = File(...),
    user: User = Depends(require_roles("teacher", "admin")),
    db: Session = Depends(get_db),
) -> ApiResponse[PresentationTemplateData]:
    content = await file.read()
    data = PresentationTemplateService(db, user).create(
        name=name,
        description=description,
        is_shared=is_shared,
        original_filename=file.filename or "presentation-template.pptx",
        content=content,
    )
    return ApiResponse(message="PPT 模板已解析，可在生成设置中选择", data=data)


@router.delete("/ppt-templates/{template_id}", response_model=ApiResponse[None])
def delete_ppt_template(
    template_id: int,
    user: User = Depends(require_roles("teacher", "admin")),
    db: Session = Depends(get_db),
) -> ApiResponse[None]:
    PresentationTemplateService(db, user).delete(template_id)
    return ApiResponse(message="PPT 模板已删除")


@router.get("/publications", response_model=ApiResponse[list[LessonPublicationData]])
def list_lesson_publications(
    teaching_class_id: int | None = Query(default=None, ge=1),
    user: User = Depends(require_roles("student", "teacher", "admin")),
    db: Session = Depends(get_db),
) -> ApiResponse[list[LessonPublicationData]]:
    return ApiResponse(data=LessonPublicationService(db, user).list(teaching_class_id))


@router.get("/publications/{publication_id}/ppt")
def download_published_ppt(
    publication_id: int,
    user: User = Depends(require_roles("student", "teacher", "admin")),
    db: Session = Depends(get_db),
) -> FileResponse:
    path, item = LessonPublicationService(db, user).download(publication_id)
    filename = item.ppt_file_name or path.name
    response = FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename=filename,
    )
    response.headers["Content-Disposition"] = (
        f"attachment; filename*=UTF-8''{quote(str(filename))}"
    )
    return response


@router.post("/runs", response_model=ApiResponse[AgentRunData])
def create_run(
    payload: AgentRunCreate,
    user: User = Depends(require_roles("teacher", "admin")),
    db: Session = Depends(get_db),
) -> ApiResponse[AgentRunData]:
    data = AgentService(db, user).create(payload)
    return ApiResponse(message="证据包已构建，请人工确认后生成课纲", data=data)


@router.get("/runs", response_model=ApiResponse[list[AgentRunData]])
def list_runs(
    limit: int = Query(default=30, ge=1, le=100),
    user: User = Depends(require_roles("teacher", "admin")),
    db: Session = Depends(get_db),
) -> ApiResponse[list[AgentRunData]]:
    return ApiResponse(data=AgentService(db, user).list(limit))


@router.get("/runs/{run_id}", response_model=ApiResponse[AgentRunData])
def get_run(
    run_id: int,
    user: User = Depends(require_roles("teacher", "admin")),
    db: Session = Depends(get_db),
) -> ApiResponse[AgentRunData]:
    return ApiResponse(data=AgentService(db, user).get(run_id))


@router.post("/runs/{run_id}/confirm", response_model=ApiResponse[AgentRunData])
def confirm_run(
    run_id: int,
    payload: AgentConfirmRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_roles("teacher", "admin")),
    db: Session = Depends(get_db),
) -> ApiResponse[AgentRunData]:
    service = AgentService(db, user)
    if payload.action == "approve_evidence":
        data = service.approve_evidence(run_id)
        background_tasks.add_task(execute_lesson_outline, run_id, db.get_bind())
        return ApiResponse(message="证据已确认，课纲正在后台生成", data=data)
    return ApiResponse(message="确认完成", data=service.get(run_id))


@router.post("/runs/{run_id}/artifacts", response_model=ApiResponse[AgentRunData])
def generate_artifacts(
    run_id: int,
    payload: AgentArtifactRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_roles("teacher", "admin")),
    db: Session = Depends(get_db),
) -> ApiResponse[AgentRunData]:
    data = AgentService(db, user).request_artifacts(run_id, payload)
    background_tasks.add_task(execute_lesson_artifacts, run_id, db.get_bind())
    return ApiResponse(message="教学成果已进入后台生成", data=data)


@router.post(
    "/runs/{run_id}/publish",
    response_model=ApiResponse[LessonPublicationData],
)
def publish_lesson_artifacts(
    run_id: int,
    payload: LessonPublishRequest,
    user: User = Depends(require_roles("teacher", "admin")),
    db: Session = Depends(get_db),
) -> ApiResponse[LessonPublicationData]:
    data = LessonPublicationService(db, user).publish(run_id, payload)
    return ApiResponse(message="PPT 与课堂讨论已发布到教学班", data=data)


@router.post(
    "/runs/{run_id}/ppt/slides/{slide_index}/revise",
    response_model=ApiResponse[AgentRunData],
)
def revise_ppt_slide(
    run_id: int,
    slide_index: int,
    payload: PptSlideRevisionRequest,
    user: User = Depends(require_roles("teacher", "admin")),
    db: Session = Depends(get_db),
) -> ApiResponse[AgentRunData]:
    data = AgentService(db, user).revise_ppt_slide(run_id, slide_index, payload)
    return ApiResponse(message="本页已重新生成，并保留上一版本", data=data)


@router.post("/runs/{run_id}/ppt/versions/restore", response_model=ApiResponse[AgentRunData])
def restore_ppt_version(
    run_id: int,
    payload: PptVersionRestoreRequest,
    user: User = Depends(require_roles("teacher", "admin")),
    db: Session = Depends(get_db),
) -> ApiResponse[AgentRunData]:
    data = AgentService(db, user).restore_ppt_version(run_id, payload.version_id)
    return ApiResponse(message="已恢复所选 PPT 版本", data=data)


@router.get("/runs/{run_id}/artifacts/{artifact_key}/download")
def download_artifact(
    run_id: int,
    artifact_key: str,
    user: User = Depends(require_roles("teacher", "admin")),
    db: Session = Depends(get_db),
) -> FileResponse:
    path, artifact = AgentService(db, user).artifact_download(run_id, artifact_key)
    filename = artifact.get("file_name") or path.name
    response = FileResponse(
        path,
        media_type=artifact.get("media_type") or "application/octet-stream",
        filename=filename,
    )
    response.headers["Content-Disposition"] = (
        f"attachment; filename*=UTF-8''{quote(str(filename))}"
    )
    return response


@router.post("/runs/{run_id}/cancel", response_model=ApiResponse[AgentRunData])
def cancel_run(
    run_id: int,
    user: User = Depends(require_roles("teacher", "admin")),
    db: Session = Depends(get_db),
) -> ApiResponse[AgentRunData]:
    return ApiResponse(message="任务已取消", data=AgentService(db, user).cancel(run_id))


@router.post("/runs/{run_id}/retry", response_model=ApiResponse[AgentRunData])
def retry_run(
    run_id: int,
    user: User = Depends(require_roles("teacher", "admin")),
    db: Session = Depends(get_db),
) -> ApiResponse[AgentRunData]:
    return ApiResponse(message="已创建重试任务", data=AgentService(db, user).retry(run_id))


@router.get("/runs/{run_id}/events")
def run_events(
    run_id: int,
    user: User = Depends(require_roles("teacher", "admin")),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    AgentService(db, user).get(run_id)
    bind = db.get_bind()
    user_id = user.id
    is_admin = user.role == "admin"

    def event_stream():
        previous = ""
        while True:
            with Session(bind=bind, autoflush=False, expire_on_commit=False) as event_db:
                run = event_db.get(AgentRun, run_id)
                if run is None or (not is_admin and run.created_by != user_id):
                    yield f"event: error\ndata: {json.dumps({'message': '任务不存在或无权访问'}, ensure_ascii=False)}\n\n"
                    return
                data = api_json_value(AgentService.serialize(event_db, run))
                serialized = json.dumps(data, ensure_ascii=False)
                if serialized != previous:
                    yield f"event: snapshot\ndata: {serialized}\n\n"
                    previous = serialized
                if run.status in {"waiting_confirmation", "completed", "failed", "cancelled"}:
                    yield "event: done\ndata: {}\n\n"
                    return
            sleep(0.5)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

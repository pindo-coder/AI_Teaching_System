from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import require_roles
from app.db.session import get_db
from app.models.ai_operation import AiProviderConfig
from app.models.user import User
from app.schemas.ai_operation import (
    AiCallLogData,
    AiConnectionTestData,
    AiOperationSummaryData,
    AiProviderConfigData,
    AiProviderConfigInput,
)
from app.schemas.common import ApiResponse
from app.services.ai_operation_service import (
    AiOperationQueryService,
    AiProviderConfigService,
    mask_api_key,
)


router = APIRouter(prefix="/admin/ai-operations", tags=["ai-operations"])


def config_data(db: Session) -> AiProviderConfigData:
    runtime = AiProviderConfigService.resolve(db)
    row = db.scalar(
        select(AiProviderConfig)
        .where(AiProviderConfig.is_active.is_(True))
        .order_by(AiProviderConfig.id.desc())
    )
    return AiProviderConfigData(
        id=row.id if row else None,
        source=runtime.source,
        base_url=runtime.base_url,
        model_name=runtime.model_name,
        api_key_masked=mask_api_key(runtime.api_key),
        temperature=runtime.temperature,
        timeout_seconds=runtime.timeout_seconds,
        streaming_enabled=runtime.streaming_enabled,
        last_test_status=row.last_test_status if row else None,
        last_test_message=row.last_test_message if row else None,
        last_test_time=row.last_test_time if row else None,
        updated_time=row.updated_time if row else None,
    )


@router.get("/config", response_model=ApiResponse[AiProviderConfigData])
def get_config(
    _: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> ApiResponse[AiProviderConfigData]:
    return ApiResponse(message="已获取当前 AI 服务配置", data=config_data(db))


@router.post("/config/test", response_model=ApiResponse[AiConnectionTestData])
def test_config(
    payload: AiProviderConfigInput,
    _: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> ApiResponse[AiConnectionTestData]:
    try:
        latency, _, message = AiProviderConfigService.test(payload, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(
        message="模型连通性测试通过",
        data=AiConnectionTestData(success=True, model_name=payload.model_name, latency_ms=latency, message=message),
    )


@router.put("/config", response_model=ApiResponse[AiProviderConfigData])
def activate_config(
    payload: AiProviderConfigInput,
    user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> ApiResponse[AiProviderConfigData]:
    try:
        AiProviderConfigService.activate(payload, db, user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(message="AI 服务配置已测试并启用", data=config_data(db))


@router.get("/calls", response_model=ApiResponse[list[AiCallLogData]])
def list_calls(
    status: str | None = Query(default=None, max_length=24),
    feature: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=100, ge=1, le=500),
    _: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> ApiResponse[list[AiCallLogData]]:
    rows = AiOperationQueryService.list_logs(db, status=status, feature=feature, limit=limit)
    return ApiResponse(
        message="已获取 AI 调用记录",
        data=[AiCallLogData(
            id=row.id,
            request_id=row.request_id,
            user_id=row.user_id,
            username=username,
            feature=row.feature,
            model_name=row.model_name,
            status=row.status,
            streaming=row.streaming,
            input_chars=row.input_chars,
            output_chars=row.output_chars,
            prompt_tokens=row.prompt_tokens,
            completion_tokens=row.completion_tokens,
            latency_ms=row.latency_ms,
            error_type=row.error_type,
            error_message=row.error_message,
            started_time=row.started_time,
            finished_time=row.finished_time,
        ) for row, username in rows],
    )


@router.get("/summary", response_model=ApiResponse[AiOperationSummaryData])
def operation_summary(
    _: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> ApiResponse[AiOperationSummaryData]:
    return ApiResponse(
        message="已获取 AI 运行摘要",
        data=AiOperationSummaryData(**AiOperationQueryService.summary(db)),
    )

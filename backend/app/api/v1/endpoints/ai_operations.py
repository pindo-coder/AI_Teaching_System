from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import require_roles
from app.db.session import get_db
from app.models.ai_operation import AiProviderConfig
from app.models.user import User
from app.schemas.ai_operation import (
    AiAllConfigOperationData,
    AiAllProviderConfigData,
    AiAllProviderConfigInput,
    AiCallLogData,
    AiCapabilityConfigData,
    AiCapabilityName,
    AiCapabilityOperationResultData,
    AiConnectionTestData,
    AiOperationSummaryData,
    AiProviderConfigData,
    AiProviderConfigInput,
    AiProviderPresetsData,
)
from app.schemas.common import ApiResponse
from app.services.ai_operation_service import (
    AI_CAPABILITIES,
    AiOperationQueryService,
    AiProviderConfigService,
    CapabilityTestOutcome,
    mask_api_key,
)


router = APIRouter(prefix="/admin/ai-operations", tags=["ai-operations"])


def config_data(db: Session) -> AiProviderConfigData:
    runtime = AiProviderConfigService.resolve(db)
    row = db.scalar(
        select(AiProviderConfig)
        .where(
            AiProviderConfig.capability == "text",
            AiProviderConfig.is_active.is_(True),
        )
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


def capability_config_data(
    db: Session,
    capability: AiCapabilityName,
) -> AiCapabilityConfigData:
    runtime = AiProviderConfigService.resolve_capability(capability, db)
    row = AiProviderConfigService.active_row(db, capability)
    return AiCapabilityConfigData(
        id=row.id if row else None,
        source=runtime.source,
        capability=capability,
        provider_name=runtime.provider_name,
        enabled=runtime.enabled,
        base_url=runtime.base_url,
        model_name=runtime.model_name,
        api_key_masked=mask_api_key(runtime.api_key),
        dimensions=runtime.dimensions,
        temperature=runtime.temperature,
        timeout_seconds=runtime.timeout_seconds,
        streaming_enabled=runtime.streaming_enabled,
        last_test_status=row.last_test_status if row else None,
        last_test_message=row.last_test_message if row else None,
        last_test_time=row.last_test_time if row else None,
        updated_time=row.updated_time if row else None,
    )


def all_config_data(db: Session) -> AiAllProviderConfigData:
    capabilities = {
        capability: capability_config_data(db, capability)
        for capability in AI_CAPABILITIES
    }
    runtimes = [
        AiProviderConfigService.resolve_capability(capability, db)
        for capability in AI_CAPABILITIES
    ]
    provider_names = {runtime.provider_name for runtime in runtimes}
    keys = {runtime.api_key for runtime in runtimes if runtime.api_key}
    return AiAllProviderConfigData(
        provider_name=provider_names.pop() if len(provider_names) == 1 else "mixed",
        api_key_masked=mask_api_key(keys.pop()) if len(keys) == 1 else None,
        capabilities=capabilities,
    )


def operation_result_data(
    outcome: CapabilityTestOutcome,
    *,
    db: Session | None = None,
) -> AiCapabilityOperationResultData:
    return AiCapabilityOperationResultData(
        capability=outcome.capability,
        success=outcome.success,
        skipped=outcome.skipped,
        latency_ms=outcome.latency_ms,
        message=outcome.message,
        kept_previous=outcome.kept_previous,
        config=(
            capability_config_data(db, outcome.capability)
            if db is not None
            else None
        ),
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


@router.get("/config/presets", response_model=ApiResponse[AiProviderPresetsData])
def get_config_presets(
    _: User = Depends(require_roles("admin")),
) -> ApiResponse[AiProviderPresetsData]:
    return ApiResponse(
        message="已获取 AI 服务配置预设",
        data=AiProviderPresetsData(presets=AiProviderConfigService.presets()),
    )


@router.get("/config/all", response_model=ApiResponse[AiAllProviderConfigData])
def get_all_configs(
    _: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> ApiResponse[AiAllProviderConfigData]:
    return ApiResponse(message="已获取全部 AI 能力配置", data=all_config_data(db))


@router.post("/config/all/test", response_model=ApiResponse[AiAllConfigOperationData])
def test_all_configs(
    payload: AiAllProviderConfigInput,
    _: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> ApiResponse[AiAllConfigOperationData]:
    outcomes = AiProviderConfigService.test_all(payload, db)
    return ApiResponse(
        message="已完成 AI 能力配置测试",
        data=AiAllConfigOperationData(
            provider_name=payload.provider_name,
            capabilities={
                capability: operation_result_data(outcome)
                for capability, outcome in outcomes.items()
            },
        ),
    )


@router.put("/config/all", response_model=ApiResponse[AiAllConfigOperationData])
def activate_all_configs(
    payload: AiAllProviderConfigInput,
    user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> ApiResponse[AiAllConfigOperationData]:
    outcomes = AiProviderConfigService.activate_all(payload, db, user)
    partial = any(not outcome.success for outcome in outcomes.values())
    return ApiResponse(
        message=(
            "可用能力已启用；测试失败的能力继续使用原配置"
            if partial
            else "全部 AI 能力配置已更新"
        ),
        data=AiAllConfigOperationData(
            provider_name=payload.provider_name,
            capabilities={
                capability: operation_result_data(outcome, db=db)
                for capability, outcome in outcomes.items()
            },
        ),
    )


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

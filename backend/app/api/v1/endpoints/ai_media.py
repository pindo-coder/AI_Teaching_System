from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.core.config import settings
from app.schemas.ai_media import AiMediaAssetRead, AiMediaCapabilities, AiMediaTranscription
from app.schemas.common import ApiResponse
from app.services.ai_media_service import (
    AiMediaNotFoundError,
    AiMediaQuotaExceededError,
    AiMediaRuntimeUnavailableError,
    AiMediaService,
    AiMediaStorageError,
    AiMediaTooLargeError,
    AiMediaValidationError,
    audio_probe_available,
)
from app.services.multimodal_provider import (
    MultimodalProviderError,
    SpeechTranscriptionProvider,
    VisionProvider,
)


router = APIRouter(prefix="/ai/media", tags=["ai-media"])


@router.get("/capabilities", response_model=ApiResponse[AiMediaCapabilities])
def media_capabilities(
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[AiMediaCapabilities]:
    """Expose only availability and bounded limits; provider details stay private."""
    vision = VisionProvider(db=db)
    speech = SpeechTranscriptionProvider(db=db)
    return ApiResponse(
        data=AiMediaCapabilities(
            image_enabled=vision.available,
            # Audio stays fail-closed unless the server can independently
            # verify its real duration instead of trusting the browser field.
            audio_enabled=speech.available and audio_probe_available(),
            max_images=int(getattr(settings, "ai_media_max_images", 2)),
            max_image_mb=int(getattr(settings, "ai_media_max_image_mb", 5)),
            max_audio_mb=int(getattr(settings, "ai_media_max_audio_mb", 10)),
            max_audio_seconds=int(getattr(settings, "ai_media_max_audio_seconds", 60)),
            retention_hours=int(getattr(settings, "ai_media_retention_hours", 24)),
            user_quota_mb=int(getattr(settings, "ai_media_user_quota_mb", 50)),
        )
    )


@router.post(
    "/assets",
    response_model=ApiResponse[AiMediaAssetRead],
    status_code=status.HTTP_201_CREATED,
)
async def upload_asset(
    file: Annotated[UploadFile, File()],
    course_id: Annotated[int | None, Form()] = None,
    chapter_id: Annotated[int | None, Form()] = None,
    duration_seconds: Annotated[float | None, Form(gt=0)] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[AiMediaAssetRead]:
    try:
        asset = await AiMediaService(db).create(
            owner_user_id=user.id,
            upload=file,
            course_id=course_id,
            chapter_id=chapter_id,
            duration_seconds=duration_seconds,
        )
    except AiMediaTooLargeError as exc:
        label = "图片" if exc.media_kind == "image" else "音频"
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"{label}不能超过 {exc.max_bytes // (1024 * 1024)} MB",
        ) from exc
    except AiMediaQuotaExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"个人临时媒体空间不能超过 {exc.max_bytes // (1024 * 1024)} MB",
        ) from exc
    except AiMediaRuntimeUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except AiMediaValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except AiMediaStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc
    return ApiResponse(message="媒体文件上传成功", data=AiMediaAssetRead.model_validate(asset))


@router.get("/assets", response_model=ApiResponse[list[AiMediaAssetRead]])
def list_assets(
    media_kind: Literal["image", "audio"] | None = Query(default=None),
    course_id: int | None = Query(default=None),
    chapter_id: int | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[list[AiMediaAssetRead]]:
    assets = AiMediaService(db).list_owned(
        user.id,
        media_kind=media_kind,
        course_id=course_id,
        chapter_id=chapter_id,
        limit=limit,
    )
    return ApiResponse(
        message="已获取媒体资产",
        data=[AiMediaAssetRead.model_validate(asset) for asset in assets],
    )


@router.get("/assets/{asset_id}", response_model=ApiResponse[AiMediaAssetRead])
def get_asset(
    asset_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[AiMediaAssetRead]:
    try:
        asset = AiMediaService(db).get_owned(asset_id, user.id)
    except AiMediaNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ApiResponse(data=AiMediaAssetRead.model_validate(asset))


@router.delete("/assets/{asset_id}", response_model=ApiResponse[AiMediaAssetRead])
def delete_asset(
    asset_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[AiMediaAssetRead]:
    try:
        asset = AiMediaService(db).get_owned(asset_id, user.id)
        response_data = AiMediaAssetRead.model_validate(asset)
        AiMediaService(db).delete_owned(asset_id, user.id)
    except AiMediaNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AiMediaStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc
    return ApiResponse(message="媒体资产已删除", data=response_data)


@router.post(
    "/assets/{asset_id}/transcribe",
    response_model=ApiResponse[AiMediaTranscription],
)
def transcribe_asset(
    asset_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[AiMediaTranscription]:
    media = AiMediaService(db)
    try:
        asset = media.get_owned(asset_id, user.id)
    except AiMediaNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if asset.media_kind != "audio" or asset.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="只有已就绪的录音可以转成文字",
        )
    provider = SpeechTranscriptionProvider(db=db)
    if not provider.available:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="语音识别服务尚未配置",
        )
    try:
        text = provider.transcribe(
            media.path_for(asset),
            filename=asset.original_filename,
            content_type=asset.mime_type,
            language="zh",
        )
    except MultimodalProviderError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return ApiResponse(message="语音已转成文字", data=AiMediaTranscription(text=text))

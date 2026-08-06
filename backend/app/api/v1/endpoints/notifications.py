from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.notifications import TeachingNotificationRead
from app.services.notification_service import NotificationService


router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=ApiResponse[list[TeachingNotificationRead]])
def list_notifications(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[list[TeachingNotificationRead]]:
    items = NotificationService(db).list_for_user(user.id, unread_only=unread_only, limit=limit)
    return ApiResponse(data=[TeachingNotificationRead.model_validate(item) for item in items])


@router.post("/read-all", response_model=ApiResponse[dict[str, int]])
def mark_all_read(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ApiResponse[dict[str, int]]:
    count = NotificationService(db).mark_all_read(user.id)
    return ApiResponse(message="提醒已全部标记为已读", data={"updated": count})


@router.post("/{notification_id}/read", response_model=ApiResponse[TeachingNotificationRead])
def mark_read(
    notification_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[TeachingNotificationRead]:
    try:
        item = NotificationService(db).mark_read(notification_id, user.id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ApiResponse(message="提醒已标记为已读", data=TeachingNotificationRead.model_validate(item))

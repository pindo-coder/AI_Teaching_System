from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_roles
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.news import NewsItemRead
from app.services.news_service import NewsService


router = APIRouter(prefix="/current-affairs", tags=["current-affairs"])


@router.get("", response_model=ApiResponse[list[NewsItemRead]])
def list_news(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ApiResponse[list[NewsItemRead]]:
    service = NewsService(db)
    service.refresh_if_stale()
    return ApiResponse(data=[NewsItemRead.model_validate(item) for item in service.list()])


@router.post("/refresh", response_model=ApiResponse[list[NewsItemRead]])
def refresh_news(_: User = Depends(require_roles("teacher", "admin")), db: Session = Depends(get_db)) -> ApiResponse[list[NewsItemRead]]:
    service = NewsService(db)
    service.refresh()
    return ApiResponse(message="时政要点已更新", data=[NewsItemRead.model_validate(item) for item in service.list()])

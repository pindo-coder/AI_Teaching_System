from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.news import NewsItemRead, NewsSearchData, NewsStudyNoteSave, NewsStudyNoteSaveResult, TextbookRelationItem
from app.services.news_service import NewsService


router = APIRouter(prefix="/current-affairs", tags=["current-affairs"])


@router.get("", response_model=ApiResponse[list[NewsItemRead]])
def list_news(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ApiResponse[list[NewsItemRead]]:
    service = NewsService(db)
    service.refresh_if_stale()
    return ApiResponse(data=[NewsItemRead.model_validate(item) for item in service.list()])


@router.post("/refresh", response_model=ApiResponse[list[NewsItemRead]])
def refresh_news(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ApiResponse[list[NewsItemRead]]:
    service = NewsService(db)
    service.refresh()
    return ApiResponse(message="时政要点已更新", data=[NewsItemRead.model_validate(item) for item in service.list()])


@router.get("/search", response_model=ApiResponse[NewsSearchData])
def search_news(
    q: str = Query(default="", max_length=100),
    source: list[str] | None = Query(default=None),
    days: int | None = Query(default=None, ge=1, le=365),
    sort: str = Query(default="latest", pattern="^(latest|relevance)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=5, le=50),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[NewsSearchData]:
    service = NewsService(db)
    service.refresh_if_stale()
    result = service.search(q, source, days, sort, page, page_size)
    result["items"] = [NewsItemRead.model_validate(item) for item in result["items"]]
    return ApiResponse(data=NewsSearchData(**result))


@router.get("/{news_id}/textbook-relations", response_model=ApiResponse[list[TextbookRelationItem]])
def textbook_relations(news_id: int, course_id: int = Query(gt=0),
                       _: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ApiResponse[list[TextbookRelationItem]]:
    return ApiResponse(data=NewsService(db).textbook_relations(news_id, course_id))


@router.post("/{news_id}/study-note", response_model=ApiResponse[NewsStudyNoteSaveResult])
def save_study_note(news_id: int, payload: NewsStudyNoteSave,
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ApiResponse[NewsStudyNoteSaveResult]:
    result = NewsService(db).save_study_note(user.id, news_id, payload)
    return ApiResponse(message="研学笔记已添加到笔记空间", data=NewsStudyNoteSaveResult(**result))

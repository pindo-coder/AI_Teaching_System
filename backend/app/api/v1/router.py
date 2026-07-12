from fastapi import APIRouter

from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.ai import router as ai_router
from app.api.v1.endpoints.courses import router as courses_router
from app.api.v1.endpoints.learning import router as learning_router
from app.api.v1.endpoints.knowledge import router as knowledge_router
from app.api.v1.endpoints.news import router as news_router
from app.core.config import settings
from app.schemas.common import ApiResponse, HealthData


router = APIRouter()
router.include_router(auth_router)
router.include_router(ai_router)
router.include_router(courses_router)
router.include_router(learning_router)
router.include_router(knowledge_router)
router.include_router(news_router)


@router.get("/health", response_model=ApiResponse[HealthData], tags=["system"])
def health_check() -> ApiResponse[HealthData]:
    return ApiResponse(
        message="服务运行正常",
        data=HealthData(status="ok", environment=settings.app_env),
    )

from fastapi import APIRouter

from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.ai import router as ai_router
from app.api.v1.endpoints.courses import router as courses_router
from app.api.v1.endpoints.learning import router as learning_router
from app.api.v1.endpoints.knowledge import router as knowledge_router
from app.api.v1.endpoints.news import router as news_router
from app.api.v1.endpoints.classroom import router as classroom_router
from app.api.v1.endpoints.study import router as study_router
from app.api.v1.endpoints.tasks import router as tasks_router
from app.api.v1.endpoints.assignments import router as assignments_router
from app.api.v1.endpoints.teaching_classes import router as teaching_classes_router
from app.core.config import settings
from app.schemas.common import ApiResponse, HealthData


router = APIRouter()
router.include_router(auth_router)
router.include_router(ai_router)
router.include_router(courses_router)
router.include_router(learning_router)
router.include_router(knowledge_router)
router.include_router(news_router)
router.include_router(classroom_router)
router.include_router(study_router)
router.include_router(tasks_router)
router.include_router(assignments_router)
router.include_router(teaching_classes_router)


@router.get("/health", response_model=ApiResponse[HealthData], tags=["system"])
def health_check() -> ApiResponse[HealthData]:
    return ApiResponse(
        message="服务运行正常",
        data=HealthData(status="ok", environment=settings.app_env),
    )

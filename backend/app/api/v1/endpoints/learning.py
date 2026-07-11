from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.learning import DashboardData, ProgressRead, ProgressUpdate
from app.services.learning_service import LearningService


router = APIRouter(tags=["learning"])


@router.get("/dashboard", response_model=ApiResponse[DashboardData])
def dashboard(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ApiResponse[DashboardData]:
    return ApiResponse(data=LearningService(db).dashboard(current_user))


@router.get("/learning/progress", response_model=ApiResponse[list[ProgressRead]])
def list_progress(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ApiResponse[list[ProgressRead]]:
    records = LearningService(db).list_progress(current_user.id)
    return ApiResponse(data=[ProgressRead.model_validate(item) for item in records])


@router.put("/learning/progress", response_model=ApiResponse[ProgressRead])
def update_progress(
    payload: ProgressUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[ProgressRead]:
    record = LearningService(db).update_progress(current_user.id, payload)
    return ApiResponse(message="学习进度已更新", data=ProgressRead.model_validate(record))

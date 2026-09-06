from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies import require_roles
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.teacher_dashboard import TeacherDashboardData
from app.services.teacher_dashboard_service import TeacherDashboardService


router = APIRouter(prefix="/teacher", tags=["teacher-dashboard"])


@router.get("/dashboard", response_model=ApiResponse[TeacherDashboardData])
def teacher_dashboard(
    month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    user: User = Depends(require_roles("teacher", "admin")),
    db: Session = Depends(get_db),
) -> ApiResponse[TeacherDashboardData]:
    try:
        data = TeacherDashboardService(db).build(user, month=month)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(data=data)

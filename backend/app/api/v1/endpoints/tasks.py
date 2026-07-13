from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.task import LearningEventCreate, TaskProgressSummary
from app.services.task_service import TaskService


router = APIRouter(prefix="/learning", tags=["learning-tasks"])


@router.get("/task-points", response_model=ApiResponse[TaskProgressSummary])
def task_points(course_id: int, chapter_id: int, learning_stage: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ApiResponse[TaskProgressSummary]:
    return ApiResponse(data=TaskService(db).summary(user.id, course_id, chapter_id, learning_stage))


@router.post("/events", response_model=ApiResponse[TaskProgressSummary])
def record_event(payload: LearningEventCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ApiResponse[TaskProgressSummary]:
    return ApiResponse(message="学习行为已记录", data=TaskService(db).record(user.id, payload))

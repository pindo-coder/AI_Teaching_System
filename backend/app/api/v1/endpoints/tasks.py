from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.task import (
    LearningEventCreate,
    LearningQuestionCreate,
    LearningTelemetryCreate,
    TaskProgressSummary,
)
from app.schemas.learning import LearningFootprint
from app.services.task_service import TaskService
from app.services.learning_footprint_service import LearningFootprintService


router = APIRouter(prefix="/learning", tags=["learning-tasks"])


@router.get("/footprint", response_model=ApiResponse[LearningFootprint])
def learning_footprint(
    course_id: int,
    chapter_id: int,
    learning_stage: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[LearningFootprint]:
    try:
        footprint = LearningFootprintService(db).summary(user.id, course_id, chapter_id, learning_stage)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(data=footprint)


@router.post("/activity", response_model=ApiResponse[LearningFootprint])
def record_learning_activity(
    payload: LearningTelemetryCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[LearningFootprint]:
    try:
        footprint = LearningFootprintService(db).record(user.id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(message="学习足迹已更新", data=footprint)


@router.get("/task-points", response_model=ApiResponse[TaskProgressSummary])
def task_points(course_id: int, chapter_id: int, learning_stage: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ApiResponse[TaskProgressSummary]:
    return ApiResponse(data=TaskService(db).summary(user.id, course_id, chapter_id, learning_stage))


@router.post("/events", response_model=ApiResponse[TaskProgressSummary])
def record_event(payload: LearningTelemetryCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ApiResponse[TaskProgressSummary]:
    return ApiResponse(message="学习行为已记录", data=TaskService(db).record(user.id, payload))


@router.post("/questions", response_model=ApiResponse[TaskProgressSummary])
def submit_learning_question(
    payload: LearningQuestionCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[TaskProgressSummary]:
    """Persist the student's actual question before awarding task evidence."""

    event = LearningEventCreate(
        course_id=payload.course_id,
        chapter_id=payload.chapter_id,
        learning_stage=payload.learning_stage,
        event_type="question_submitted",
        event_data={"count": 1, "content": payload.content.strip()},
    )
    return ApiResponse(
        message="学习问题已提交",
        data=TaskService(db).record(user.id, event),
    )

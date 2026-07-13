from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_roles
from app.db.session import get_db
from app.models.chapter import Chapter
from app.models.classroom import ClassroomActivity, ClassroomResponse
from app.models.course import Course
from app.models.user import User
from app.schemas.classroom import ActivityCreate, ActivityRead, ResponseCreate, ResponseRead
from app.schemas.common import ApiResponse


router = APIRouter(prefix="/classroom", tags=["classroom"])


@router.get("/activities", response_model=ApiResponse[list[ActivityRead]])
def list_activities(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ApiResponse[list[ActivityRead]]:
    activities = db.scalars(select(ClassroomActivity).where(ClassroomActivity.status == "published").order_by(ClassroomActivity.id.desc())).all()
    return ApiResponse(data=list(activities))


@router.post("/activities", response_model=ApiResponse[ActivityRead], status_code=status.HTTP_201_CREATED)
def publish_activity(payload: ActivityCreate, current_user: User = Depends(require_roles("teacher", "admin")), db: Session = Depends(get_db)) -> ApiResponse[ActivityRead]:
    if db.get(Course, payload.course_id) is None or db.scalar(select(Chapter).where(Chapter.id == payload.chapter_id, Chapter.course_id == payload.course_id)) is None:
        raise HTTPException(status_code=404, detail="教材或专题不存在")
    activity = ClassroomActivity(**payload.model_dump(), created_by=current_user.id)
    db.add(activity)
    db.commit()
    db.refresh(activity)
    return ApiResponse(message="课堂互动已发布", data=activity)


@router.post("/activities/{activity_id}/responses", response_model=ApiResponse[ResponseRead], status_code=status.HTTP_201_CREATED)
def submit_response(activity_id: int, payload: ResponseCreate, current_user: User = Depends(require_roles("student", "teacher", "admin")), db: Session = Depends(get_db)) -> ApiResponse[ResponseRead]:
    activity = db.get(ClassroomActivity, activity_id)
    if activity is None or activity.status != "published":
        raise HTTPException(status_code=404, detail="课堂互动不存在或已结束")
    response = ClassroomResponse(activity_id=activity_id, user_id=current_user.id, answer=payload.answer.strip())
    db.add(response)
    db.commit()
    db.refresh(response)
    return ApiResponse(message="观点提交成功", data=response)

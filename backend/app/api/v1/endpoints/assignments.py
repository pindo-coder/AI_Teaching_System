from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_roles
from app.db.session import get_db
from app.models.user import User
from app.schemas.assignment import (
    AssignmentCreate,
    AssignmentRecipientRead,
    AssignmentStudentItem,
    StudentAssignmentRead,
    TeacherAssignmentRead,
)
from app.schemas.common import ApiResponse
from app.services.assignment_service import AssignmentService


router = APIRouter(prefix="/assignments", tags=["teacher-assignments"])
manager = require_roles("teacher", "admin")


@router.get("/students", response_model=ApiResponse[list[AssignmentStudentItem]])
def list_students(teaching_class_id: int | None = None, user: User = Depends(manager),
                  db: Session = Depends(get_db)) -> ApiResponse[list[AssignmentStudentItem]]:
    return ApiResponse(data=AssignmentService(db).list_students(user, teaching_class_id))


@router.get("/student", response_model=ApiResponse[list[StudentAssignmentRead]])
def student_assignments(include_completed: bool = Query(default=True), user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)) -> ApiResponse[list[StudentAssignmentRead]]:
    if user.role != "student":
        return ApiResponse(data=[])
    return ApiResponse(data=AssignmentService(db).student_assignments(user.id, include_completed))


@router.get("", response_model=ApiResponse[list[TeacherAssignmentRead]])
def teacher_assignments(user: User = Depends(manager), db: Session = Depends(get_db)) -> ApiResponse[list[TeacherAssignmentRead]]:
    return ApiResponse(data=AssignmentService(db).teacher_assignments(user.id, user.role == "admin"))


@router.post("", response_model=ApiResponse[TeacherAssignmentRead], status_code=status.HTTP_201_CREATED)
def create_assignment(payload: AssignmentCreate, user: User = Depends(manager), db: Session = Depends(get_db)) -> ApiResponse[TeacherAssignmentRead]:
    assignment = AssignmentService(db).create(user.id, payload)
    item = next(item for item in AssignmentService(db).teacher_assignments(user.id, user.role == "admin") if item["id"] == assignment.id)
    return ApiResponse(message="学习任务已发布", data=TeacherAssignmentRead(**item))


@router.get("/{assignment_id}/recipients", response_model=ApiResponse[list[AssignmentRecipientRead]])
def assignment_recipients(
    assignment_id: int,
    user: User = Depends(manager),
    db: Session = Depends(get_db),
) -> ApiResponse[list[AssignmentRecipientRead]]:
    return ApiResponse(data=AssignmentService(db).recipient_details(assignment_id, user))


@router.delete("/{assignment_id}", response_model=ApiResponse[dict[str, int]])
def cancel_assignment(assignment_id: int, user: User = Depends(manager), db: Session = Depends(get_db)) -> ApiResponse[dict[str, int]]:
    AssignmentService(db).cancel(assignment_id, user.id, user.role == "admin")
    return ApiResponse(message="任务已撤回", data={"id": assignment_id})

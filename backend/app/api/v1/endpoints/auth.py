from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_roles
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.user import TeacherApprovalUpdate, TokenData, UserCreate, UserLogin, UserRead
from app.services.auth_service import AuthService


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=ApiResponse[UserRead], status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, db: Session = Depends(get_db)) -> ApiResponse[UserRead]:
    user = AuthService(db).register(
        username=payload.username,
        password=payload.password,
        role=payload.role,
        identity_no=payload.identity_no,
    )
    return ApiResponse(message="注册成功", data=UserRead.model_validate(user))


@router.post("/login", response_model=ApiResponse[TokenData])
def login(payload: UserLogin, db: Session = Depends(get_db)) -> ApiResponse[TokenData]:
    token, user = AuthService(db).login(username=payload.username, password=payload.password)
    return ApiResponse(message="登录成功", data=TokenData(access_token=token, user=UserRead.model_validate(user)))


@router.get("/me", response_model=ApiResponse[UserRead])
def me(current_user: User = Depends(get_current_user)) -> ApiResponse[UserRead]:
    return ApiResponse(data=UserRead.model_validate(current_user))


@router.get("/teachers/pending", response_model=ApiResponse[list[UserRead]])
def pending_teachers(
    _: User = Depends(require_roles("admin")), db: Session = Depends(get_db)
) -> ApiResponse[list[UserRead]]:
    users = db.scalars(
        select(User).where(User.role == "teacher", User.approval_status == "pending").order_by(User.created_time)
    ).all()
    return ApiResponse(data=[UserRead.model_validate(item) for item in users])


@router.put("/teachers/{user_id}/approval", response_model=ApiResponse[UserRead])
def update_teacher_approval(
    user_id: int,
    payload: TeacherApprovalUpdate,
    admin: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> ApiResponse[UserRead]:
    teacher = db.get(User, user_id)
    if teacher is None or teacher.role != "teacher":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="教师账号不存在")
    teacher.approval_status = payload.status
    teacher.approval_note = payload.note.strip() or None
    teacher.approved_by = admin.id
    teacher.approved_time = datetime.now() if payload.status == "approved" else None
    db.commit()
    db.refresh(teacher)
    return ApiResponse(message="教师审核状态已更新", data=UserRead.model_validate(teacher))

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_session_user, require_roles
from app.db.session import get_db
from app.models.user import User
from app.models.password_reset_request import PasswordResetRequest as PasswordResetRequestModel
from app.schemas.common import ApiResponse
from app.schemas.user import (
    AdminTemporaryPasswordRead,
    EmailVerificationConfirm,
    EmailVerificationRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    PasswordResetRequestRead,
    PasswordResetRequestResult,
    PasswordChange,
    TeacherApprovalUpdate,
    TokenData,
    UserCreate,
    UserLogin,
    UserRead,
)
from app.services.auth_service import AuthService


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=ApiResponse[UserRead], status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, request: Request, db: Session = Depends(get_db)) -> ApiResponse[UserRead]:
    user = AuthService(db).register(
        username=payload.username,
        password=payload.password,
        role=payload.role,
        identity_no=payload.identity_no,
        email=payload.email,
    )
    if payload.email:
        AuthService(db).request_email_verification(
            user=user, email=payload.email, request_ip=request.client.host if request.client else None
        )
    return ApiResponse(message="注册成功", data=UserRead.model_validate(user))


@router.post("/login", response_model=ApiResponse[TokenData])
def login(payload: UserLogin, db: Session = Depends(get_db)) -> ApiResponse[TokenData]:
    token, user = AuthService(db).login(username=payload.username, password=payload.password)
    return ApiResponse(message="登录成功", data=TokenData(access_token=token, user=UserRead.model_validate(user)))


@router.post("/email/verification/request", response_model=ApiResponse[dict[str, str]])
def request_email_verification(
    payload: EmailVerificationRequest,
    request: Request,
    current_user: User = Depends(get_session_user),
    db: Session = Depends(get_db),
) -> ApiResponse[dict[str, str]]:
    AuthService(db).request_email_verification(
        user=current_user, email=payload.email, request_ip=request.client.host if request.client else None
    )
    return ApiResponse(message="验证码邮件已发送，请查收邮箱", data={})


@router.post("/email/verification/confirm", response_model=ApiResponse[UserRead])
def confirm_email_verification(
    payload: EmailVerificationConfirm, db: Session = Depends(get_db)
) -> ApiResponse[UserRead]:
    user = AuthService(db).confirm_email_verification(email=payload.email, code=payload.code)
    return ApiResponse(message="邮箱验证成功", data=UserRead.model_validate(user))


@router.post("/password-reset/request", response_model=ApiResponse[PasswordResetRequestResult], status_code=status.HTTP_202_ACCEPTED)
def request_password_reset(
    payload: PasswordResetRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> ApiResponse[PasswordResetRequestResult]:
    next_step = AuthService(db).request_password_reset(
        identifier=payload.identifier, request_ip=request.client.host if request.client else None
    )
    if next_step == "admin":
        return ApiResponse(message="该账号请联系管理员重置密码", data=PasswordResetRequestResult(next_step=next_step))
    if next_step == "verify_email":
        return ApiResponse(message="验证码已发送，请先完成邮箱验证，再重新申请密码重置", data=PasswordResetRequestResult(next_step=next_step))
    return ApiResponse(message="请查收邮箱中的密码重置验证码", data=PasswordResetRequestResult(next_step=next_step))


@router.post("/password-reset/confirm", response_model=ApiResponse[dict[str, str]])
def confirm_password_reset(
    payload: PasswordResetConfirm, db: Session = Depends(get_db)
) -> ApiResponse[dict[str, str]]:
    AuthService(db).confirm_password_reset(
        token=payload.token,
        identifier=payload.identifier,
        code=payload.code,
        new_password=payload.new_password,
    )
    return ApiResponse(message="密码重置成功，请重新登录", data={})


@router.post("/password/change", response_model=ApiResponse[dict[str, str]])
def change_password(
    payload: PasswordChange,
    current_user: User = Depends(get_session_user),
    db: Session = Depends(get_db),
) -> ApiResponse[dict[str, str]]:
    AuthService(db).change_password(user=current_user, new_password=payload.new_password)
    return ApiResponse(message="密码修改成功，请重新登录", data={})


@router.get("/me", response_model=ApiResponse[UserRead])
def me(current_user: User = Depends(get_session_user)) -> ApiResponse[UserRead]:
    return ApiResponse(data=UserRead.model_validate(current_user))


@router.get("/users", response_model=ApiResponse[list[UserRead]])
def list_users(_: User = Depends(require_roles("admin")), db: Session = Depends(get_db)) -> ApiResponse[list[UserRead]]:
    users = db.scalars(select(User).order_by(User.created_time.desc(), User.id.desc())).all()
    return ApiResponse(data=[UserRead.model_validate(item) for item in users])


@router.get("/password-reset/pending", response_model=ApiResponse[list[PasswordResetRequestRead]])
def pending_password_reset_requests(
    _: User = Depends(require_roles("admin")), db: Session = Depends(get_db)
) -> ApiResponse[list[PasswordResetRequestRead]]:
    rows = db.execute(
        select(PasswordResetRequestModel, User)
        .join(User, User.id == PasswordResetRequestModel.user_id)
        .where(PasswordResetRequestModel.status == "pending")
        .order_by(PasswordResetRequestModel.requested_at)
    ).all()
    return ApiResponse(data=[PasswordResetRequestRead(
        id=request.id, user_id=user.id, username=user.username, email=user.email,
        requested_at=request.requested_at, request_ip=request.request_ip,
    ) for request, user in rows])


@router.post("/users/{user_id}/temporary-password", response_model=ApiResponse[AdminTemporaryPasswordRead])
def admin_temporary_password(
    user_id: int,
    request: Request,
    admin: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> ApiResponse[AdminTemporaryPasswordRead]:
    temporary_password = AuthService(db).admin_temporary_password(
        user_id=user_id, admin_id=admin.id, request_ip=request.client.host if request.client else None
    )
    return ApiResponse(
        message="临时密码已生成，请通过安全渠道交给用户",
        data=AdminTemporaryPasswordRead(user_id=user_id, temporary_password=temporary_password),
    )


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

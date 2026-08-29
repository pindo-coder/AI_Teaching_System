from collections.abc import Callable

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.services.auth_service import teacher_authentication_block_reason


bearer_scheme = HTTPBearer(auto_error=False)


def get_session_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Resolve a session, including a pending teacher who may only inspect it."""
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="登录状态无效或已过期",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized
    try:
        subject, token_version = decode_access_token(credentials.credentials)
        user_id = int(subject)
    except (jwt.InvalidTokenError, ValueError):
        raise unauthorized from None
    user = UserRepository(db).get_by_id(user_id)
    if user is None or teacher_authentication_block_reason(user) or user.auth_version != token_version:
        raise unauthorized
    return user


def get_current_user(current_user: User = Depends(get_session_user)) -> User:
    """Require an active account for every business endpoint."""

    if current_user.role == "teacher" and current_user.approval_status != "approved":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="教师账号尚未通过管理员审核",
        )
    return current_user


def require_roles(*roles: str) -> Callable[[User], User]:
    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前账号无权执行此操作")
        return current_user

    return role_checker

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.repositories.user_repository import UserRepository


_BLOCKED_TEACHER_MESSAGES = {
    "rejected": "教师账号审核未通过",
    "disabled": "教师账号已被禁用",
}


def teacher_authentication_block_reason(user: User) -> str | None:
    """Return the reason a teacher account must not receive or use a session."""
    if user.role != "teacher":
        return None
    return _BLOCKED_TEACHER_MESSAGES.get(user.approval_status)


class AuthService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.users = UserRepository(db)

    def register(self, *, username: str, password: str, role: str = "student", identity_no: str = "") -> User:
        normalized_username = username.strip()
        normalized_identity = identity_no.strip().upper()
        if self.users.get_by_username(normalized_username):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已存在")
        if self.db.query(User).filter(User.identity_no == normalized_identity).first():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="学号或工号已注册")
        try:
            return self.users.create(
                username=normalized_username,
                password_hash=hash_password(password),
                role=role,
                identity_no=normalized_identity,
                approval_status="pending" if role == "teacher" else "approved",
            )
        except IntegrityError:
            self.db.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名、学号或工号已存在") from None

    def login(self, *, username: str, password: str) -> tuple[str, User]:
        user = self.users.get_by_username(username.strip())
        if user is None or not verify_password(password, user.password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
        blocked_reason = teacher_authentication_block_reason(user)
        if blocked_reason:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=blocked_reason)
        return create_access_token(str(user.id)), user

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.repositories.user_repository import UserRepository


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
        return create_access_token(str(user.id)), user

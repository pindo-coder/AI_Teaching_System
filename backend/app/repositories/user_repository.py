from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User


class UserRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, user_id: int) -> User | None:
        return self.db.get(User, user_id)

    def get_by_username(self, username: str) -> User | None:
        return self.db.scalar(select(User).where(User.username == username))

    def create(self, *, username: str, password_hash: str, role: str = "student", identity_no: str | None = None) -> User:
        user = User(username=username, password_hash=password_hash, role=role, identity_no=identity_no)
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

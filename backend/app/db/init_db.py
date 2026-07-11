from pathlib import Path

from app.core.config import BACKEND_DIR, settings
from app.core.security import hash_password
from app.db.base import Base
from app.db import models  # noqa: F401  # 注册全部 SQLAlchemy 模型
from app.db.session import SessionLocal, engine
from app.repositories.user_repository import UserRepository


def init_db() -> None:
    """为 MVP 创建数据目录和数据表；生产环境将替换为迁移工具。"""

    if settings.database_url.startswith("sqlite:///./"):
        relative_path = settings.database_url.removeprefix("sqlite:///./")
        (BACKEND_DIR / relative_path).parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    create_bootstrap_admin()


def create_bootstrap_admin() -> None:
    """仅在显式配置账号和密码时创建首个管理员。"""

    username = settings.bootstrap_admin_username
    password = settings.bootstrap_admin_password
    if not username or not password:
        return
    with SessionLocal() as db:
        users = UserRepository(db)
        if users.get_by_username(username) is None:
            users.create(username=username, password_hash=hash_password(password), role="admin")

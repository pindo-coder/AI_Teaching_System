"""为已有部署补充注册身份字段和课堂互动表。"""

from sqlalchemy import inspect, text

from app.core.config import settings
from app.db.base import Base
from app.db.models import ClassroomActivity, ClassroomResponse  # noqa: F401
from app.db.session import engine


def migrate() -> None:
    inspector = inspect(engine)
    with engine.begin() as connection:
        user_columns = {column["name"] for column in inspector.get_columns("users")}
        if "identity_no" not in user_columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN identity_no VARCHAR(32) NULL"))
        if engine.dialect.name != "sqlite":
            try:
                connection.execute(text("CREATE UNIQUE INDEX ix_users_identity_no ON users (identity_no)"))
            except Exception:
                pass
    Base.metadata.create_all(engine)
    print(f"数据库结构升级完成：{settings.database_url.split('@')[-1]}")


if __name__ == "__main__":
    migrate()

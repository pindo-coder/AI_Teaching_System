"""根据 backend/.env 初始化数据库表。适用于 SQLite 和 MySQL。"""

from app.core.config import settings
from app.db.init_db import init_db


if __name__ == "__main__":
    init_db()
    print(f"数据库初始化完成：{settings.database_url.split('@')[-1]}")

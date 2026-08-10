"""根据 backend/.env 将数据库升级到最新 Alembic revision。"""

from alembic import command

from app.core.config import settings
from app.db.init_db import _alembic_config, create_bootstrap_admin


if __name__ == "__main__":
    command.upgrade(_alembic_config(), "head")
    create_bootstrap_admin()
    print(f"数据库迁移完成：{settings.database_url.split('@')[-1]}")

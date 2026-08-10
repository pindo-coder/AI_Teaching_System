from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Engine

from app.core.config import BACKEND_DIR, settings
from app.core.security import hash_password
from app.db.base import Base
from app.db import models  # noqa: F401  # 注册全部 SQLAlchemy 模型
from app.db.session import SessionLocal, engine
from app.repositories.user_repository import UserRepository


def _alembic_config() -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    # 使用绝对路径，确保从 systemd、宝塔或任意工作目录启动时均能定位迁移。
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return config


def database_revision_state(db_engine: Engine = engine) -> tuple[set[str], set[str]]:
    """返回数据库当前 revision 与代码期望的 Alembic head。"""

    expected_heads = set(ScriptDirectory.from_config(_alembic_config()).get_heads())
    with db_engine.connect() as connection:
        current_heads = set(MigrationContext.configure(connection).get_current_heads())
    return current_heads, expected_heads


def validate_database_revision(db_engine: Engine = engine) -> None:
    """阻止未迁移的持久数据库带病启动。"""

    current_heads, expected_heads = database_revision_state(db_engine)
    if current_heads == expected_heads:
        return
    current_label = ", ".join(sorted(current_heads)) or "未初始化"
    expected_label = ", ".join(sorted(expected_heads)) or "无可用迁移"
    raise RuntimeError(
        "数据库结构版本未就绪："
        f"当前={current_label}，期望={expected_label}。"
        "请在 backend 目录执行 `PYTHONPATH=. alembic upgrade head` 后重新启动。"
    )


def init_db() -> None:
    """初始化开发库，并校验生产数据库的迁移状态。"""

    if settings.database_url.startswith("sqlite:///./"):
        relative_path = settings.database_url.removeprefix("sqlite:///./")
        (BACKEND_DIR / relative_path).parent.mkdir(parents=True, exist_ok=True)
    auto_create_sqlite = engine.dialect.name == "sqlite" and settings.app_env != "production"
    if auto_create_sqlite:
        Base.metadata.create_all(bind=engine)
    elif settings.database_schema_check_enabled:
        validate_database_revision(engine)
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

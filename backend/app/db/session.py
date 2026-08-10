from collections.abc import Generator
import sqlite3
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


def _engine_options(database_url: str) -> dict[str, Any]:
    """Return conservative connection options for the configured database.

    MySQL can close an idle connection before SQLAlchemy tries to reuse it.
    ``pool_pre_ping`` discards those stale connections, while ``pool_recycle``
    keeps long-running API processes below a typical server ``wait_timeout``.
    SQLite does not use the network pool settings; its timeout gives concurrent
    background jobs a short window to wait for another writer instead.
    """

    backend = make_url(database_url).get_backend_name()
    if backend == "sqlite":
        return {
            "connect_args": {
                "check_same_thread": False,
                "timeout": 5,
            },
        }
    if backend == "mysql":
        return {
            "connect_args": {
                "connect_timeout": 10,
            },
            "pool_pre_ping": True,
            "pool_recycle": 1800,
            "pool_timeout": 30,
        }
    return {}


engine = create_engine(settings.database_url, **_engine_options(settings.database_url))


@event.listens_for(Engine, "connect")
def enable_sqlite_foreign_keys(dbapi_connection: object, _: object) -> None:
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")

        # WAL materially improves local read/write concurrency, but it is only
        # meaningful for a file-backed database. In-memory and read-only SQLite
        # connections keep their native journal mode.
        database_row = cursor.execute("PRAGMA database_list").fetchone()
        database_path = str(database_row[2]) if database_row and database_row[2] else ""
        if database_path:
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
            except sqlite3.OperationalError:
                # A read-only filesystem may reject journal changes. Foreign
                # keys and busy_timeout are still valid in that environment.
                pass
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

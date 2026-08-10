from sqlalchemy import create_engine, text

from app.db.session import _engine_options


def test_mysql_engine_options_recycle_stale_connections() -> None:
    options = _engine_options("mysql+pymysql://user:password@db.example/app")

    assert options["pool_pre_ping"] is True
    assert options["pool_recycle"] == 1800
    assert options["pool_timeout"] == 30
    # Do not change the database session timezone globally: legacy func.now()
    # columns have no per-row time-basis marker and must keep their old basis.
    assert options["connect_args"] == {"connect_timeout": 10}


def test_sqlite_engine_options_allow_background_threads_to_wait() -> None:
    options = _engine_options("sqlite:///./data/test.db")

    assert options == {
        "connect_args": {
            "check_same_thread": False,
            "timeout": 5,
        },
    }


def test_file_backed_sqlite_enables_foreign_keys_busy_timeout_and_wal(tmp_path) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'session-options.db'}",
        **_engine_options(f"sqlite:///{tmp_path / 'session-options.db'}"),
    )
    try:
        with engine.connect() as connection:
            foreign_keys = connection.scalar(text("PRAGMA foreign_keys"))
            busy_timeout = connection.scalar(text("PRAGMA busy_timeout"))
            journal_mode = connection.scalar(text("PRAGMA journal_mode"))
    finally:
        engine.dispose()

    assert foreign_keys == 1
    assert busy_timeout == 5000
    assert str(journal_mode).lower() == "wal"

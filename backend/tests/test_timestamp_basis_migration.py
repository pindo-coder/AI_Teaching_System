from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path

import sqlalchemy as sa
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "20260810_04_timestamp_basis.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("timestamp_basis_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_timestamp_basis_migration_marks_existing_rows_without_rewriting_time() -> None:
    migration = _load_migration()
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    news = sa.Table(
        "news_items",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("published_time", sa.DateTime()),
    )
    assignments = sa.Table(
        "teacher_assignments",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("due_time", sa.DateTime(), nullable=False),
    )
    metadata.create_all(engine)
    legacy_news_time = datetime(2026, 7, 15, 8, 30)
    legacy_due_time = datetime(2026, 8, 20, 18, 0)

    with engine.begin() as connection:
        connection.execute(news.insert().values(id=1, published_time=legacy_news_time))
        connection.execute(assignments.insert().values(id=1, due_time=legacy_due_time))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

        news_row = connection.execute(sa.select(news)).mappings().one()
        assignment_row = connection.execute(sa.select(assignments)).mappings().one()
        news_columns = {column["name"] for column in sa.inspect(connection).get_columns("news_items")}
        assignment_columns = {
            column["name"] for column in sa.inspect(connection).get_columns("teacher_assignments")
        }

    assert migration.down_revision == "20260810_03"
    assert "published_time_is_utc" in news_columns
    assert "due_time_is_utc" in assignment_columns
    assert news_row["published_time"] == legacy_news_time
    assert assignment_row["due_time"] == legacy_due_time

    with engine.connect() as connection:
        assert connection.scalar(sa.text("SELECT published_time_is_utc FROM news_items WHERE id=1")) == 0
        assert connection.scalar(sa.text("SELECT due_time_is_utc FROM teacher_assignments WHERE id=1")) == 0

    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.downgrade()
        assert "published_time_is_utc" not in {
            column["name"] for column in sa.inspect(connection).get_columns("news_items")
        }
        assert "due_time_is_utc" not in {
            column["name"] for column in sa.inspect(connection).get_columns("teacher_assignments")
        }


def test_timestamp_basis_migration_fails_when_required_table_is_missing() -> None:
    migration = _load_migration()
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE news_items (id INTEGER PRIMARY KEY, published_time DATETIME)"
        )
        migration.op = Operations(MigrationContext.configure(connection))
        with pytest.raises(RuntimeError, match="teacher_assignments"):
            migration.upgrade()

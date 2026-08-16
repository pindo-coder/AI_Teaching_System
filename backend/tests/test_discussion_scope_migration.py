from __future__ import annotations

import importlib.util
from io import StringIO
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa


VERSIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _load_migration(filename: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, VERSIONS_DIR / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sqlite_upgrade_preserves_rows_and_makes_scope_nullable() -> None:
    migration = _load_migration(
        "20260816_02_discussion_nullable_scope.py", "discussion_nullable_sqlite",
    )
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    threads = sa.Table(
        "discussion_threads", metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("teaching_class_id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("chapter_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
    )
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(threads.insert().values(
            id=1, teaching_class_id=1, course_id=1, chapter_id=1, title="existing",
        ))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

        columns = {item["name"]: item for item in sa.inspect(connection).get_columns("discussion_threads")}
        row = connection.execute(sa.text("SELECT id, title FROM discussion_threads")).mappings().one()
        connection.execute(sa.text(
            "INSERT INTO discussion_threads (id, teaching_class_id, course_id, chapter_id, title) "
            "VALUES (2, NULL, NULL, NULL, 'global')"
        ))

    assert migration.down_revision == "20260816_01"
    assert all(columns[name]["nullable"] for name in migration.SCOPE_COLUMNS)
    assert row == {"id": 1, "title": "existing"}


def test_mysql_upgrade_emits_nullable_modify_statements(monkeypatch) -> None:
    migration = _load_migration(
        "20260816_02_discussion_nullable_scope.py", "discussion_nullable_mysql",
    )

    class Inspector:
        @staticmethod
        def has_table(name: str) -> bool:
            return name == "discussion_threads"

        @staticmethod
        def get_columns(_: str) -> list[dict[str, object]]:
            return [
                {"name": name, "nullable": False}
                for name in migration.SCOPE_COLUMNS
            ]

    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="mysql",
        opts={"as_sql": True, "output_buffer": output},
    )
    migration.op = Operations(context)
    monkeypatch.setattr(migration.sa, "inspect", lambda _: Inspector())
    migration.upgrade()

    sql = output.getvalue()
    for name in migration.SCOPE_COLUMNS:
        assert f"ALTER TABLE discussion_threads MODIFY {name} INTEGER NULL" in sql


def test_initial_migration_accepts_tables_precreated_by_sqlite_create_all() -> None:
    migration = _load_migration(
        "20260816_01_discussions.py", "discussion_initial_idempotent",
    )
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table("discussion_threads", metadata, sa.Column("id", sa.Integer(), primary_key=True))
    sa.Table("discussion_replies", metadata, sa.Column("id", sa.Integer(), primary_key=True))
    metadata.create_all(engine)

    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

    assert set(sa.inspect(engine).get_table_names()) == {
        "discussion_replies", "discussion_threads",
    }

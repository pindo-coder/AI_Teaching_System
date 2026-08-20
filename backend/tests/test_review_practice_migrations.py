from __future__ import annotations

import importlib.util
from io import StringIO
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


VERSIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _load_migration(filename: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, VERSIONS_DIR / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_review_practice_migrations_backfill_without_database_defaults() -> None:
    answers = _load_migration(
        "20260820_01_review_practice_answers.py", "review_practice_answers_migration"
    )
    cache = _load_migration(
        "20260820_02_review_reference_cache.py", "review_reference_cache_migration"
    )
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    practices = sa.Table(
        "review_practices",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
    )
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(practices.insert().values(id=1))
        operations = Operations(MigrationContext.configure(connection))
        answers.op = operations
        answers.upgrade()
        cache.op = operations
        cache.upgrade()

        row = connection.execute(sa.text(
            "SELECT student_answer, ai_reference_answer, reference_knowledge_points, "
            "reference_cache_key FROM review_practices WHERE id = 1"
        )).one()
        columns = {item["name"]: item for item in sa.inspect(connection).get_columns("review_practices")}

    assert tuple(row) == ("", "", "[]", "")
    for name in (
        "student_answer", "ai_reference_answer", "reference_knowledge_points", "reference_cache_key"
    ):
        assert columns[name]["nullable"] is False
        assert columns[name]["default"] is None


def test_review_practice_migrations_emit_mysql57_compatible_ddl() -> None:
    answers = _load_migration(
        "20260820_01_review_practice_answers.py", "review_practice_answers_mysql_migration"
    )
    cache = _load_migration(
        "20260820_02_review_reference_cache.py", "review_reference_cache_mysql_migration"
    )
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="mysql",
        opts={"as_sql": True, "output_buffer": output},
    )
    operations = Operations(context)
    answers.op = operations
    cache.op = operations

    answers.upgrade()
    cache.upgrade()

    ddl = output.getvalue().upper()
    add_column_statements = [line for line in ddl.splitlines() if "ADD COLUMN" in line]
    assert len(add_column_statements) == 4
    assert all("DEFAULT" not in statement for statement in add_column_statements)

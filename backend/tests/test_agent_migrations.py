from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _load(filename: str):
    path = MIGRATIONS_DIR / filename
    spec = importlib.util.spec_from_file_location(filename.removesuffix(".py"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_upgrade(connection: sa.Connection, migration) -> None:
    migration.op = Operations(MigrationContext.configure(connection))
    migration.upgrade()


def test_agent_execution_migration_does_not_modify_assignment_schema() -> None:
    migration = _load("20260901_01_agent_execution_reliability.py")
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table("agent_executions", metadata, sa.Column("id", sa.Integer, primary_key=True))
    sa.Table("teacher_assignments", metadata, sa.Column("id", sa.Integer, primary_key=True))
    metadata.create_all(engine)

    with engine.begin() as connection:
        _run_upgrade(connection, migration)
        assert "cancel_requested" in {
            column["name"] for column in sa.inspect(connection).get_columns("agent_executions")
        }
        assert "rubric" not in {
            column["name"] for column in sa.inspect(connection).get_columns("teacher_assignments")
        }


def test_assignment_rubric_migration_backfills_without_server_default() -> None:
    migration = _load("20260901_02_assignment_rubric.py")
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    assignments = sa.Table(
        "teacher_assignments",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("title", sa.String(20), nullable=False),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(assignments.insert().values(title="legacy"))
        _run_upgrade(connection, migration)
        row = connection.execute(sa.text("SELECT rubric FROM teacher_assignments")).one()
        column = next(
            item for item in sa.inspect(connection).get_columns("teacher_assignments")
            if item["name"] == "rubric"
        )

    assert row[0] in ({}, "{}")
    assert column["nullable"] is False
    assert column.get("default") is None

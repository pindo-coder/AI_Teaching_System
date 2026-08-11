from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "20260811_01_matching_confidence.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("matching_confidence_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_matching_confidence_migration_backfills_existing_policy_changes() -> None:
    migration = _load_migration()
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    changes = sa.Table(
        "policy_changes",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("similarity_score", sa.Float(), nullable=False),
        sa.Column("alert_recommended", sa.Boolean(), nullable=False),
    )
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(changes.insert().values(id=1, similarity_score=0.4, alert_recommended=True))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

        columns = {column["name"] for column in sa.inspect(connection).get_columns("policy_changes")}
        row = connection.execute(sa.text(
            "SELECT similarity_score, evidence_confidence, alert_recommended FROM policy_changes WHERE id = 1"
        )).mappings().one()

        assert migration.down_revision == "20260810_05"
        assert "evidence_confidence" in columns
        assert row == {
            "similarity_score": 0.4,
            "evidence_confidence": 0.0,
            "alert_recommended": 0,
        }

        migration.op = Operations(MigrationContext.configure(connection))
        migration.downgrade()
        remaining = {column["name"] for column in sa.inspect(connection).get_columns("policy_changes")}
        assert "evidence_confidence" not in remaining


def test_matching_confidence_migration_retry_clears_legacy_alerts() -> None:
    migration = _load_migration()
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    changes = sa.Table(
        "policy_changes",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("evidence_confidence", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("alert_recommended", sa.Boolean(), nullable=False),
    )
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(changes.insert().values(id=1, alert_recommended=True))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

        row = connection.execute(sa.text(
            "SELECT evidence_confidence, alert_recommended FROM policy_changes WHERE id = 1"
        )).mappings().one()

        assert row == {
            "evidence_confidence": 0.0,
            "alert_recommended": 0,
        }

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
    / "20260810_05_unified_ai_capabilities.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("unified_ai_capabilities_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_unified_ai_capability_migration_backfills_legacy_rows_and_downgrades() -> None:
    migration = _load_migration()
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    configs = sa.Table(
        "ai_provider_configs",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("model_name", sa.String(200), nullable=False),
        sa.Column("api_key_encrypted", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            configs.insert().values(
                id=1,
                base_url="https://model.example/v1",
                model_name="legacy-text-model",
                api_key_encrypted="encrypted",
                is_active=True,
            )
        )
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

        columns = {
            column["name"]: column
            for column in sa.inspect(connection).get_columns("ai_provider_configs")
        }
        row = connection.execute(
            sa.text(
                "SELECT capability, provider_name, enabled, dimensions "
                "FROM ai_provider_configs WHERE id = 1"
            )
        ).mappings().one()
        indexes = {
            index["name"]
            for index in sa.inspect(connection).get_indexes("ai_provider_configs")
        }

        assert migration.down_revision == "20260810_04"
        assert {"capability", "provider_name", "enabled", "dimensions"} <= set(columns)
        assert row["capability"] == "text"
        assert row["provider_name"] == "openai_compatible"
        assert bool(row["enabled"]) is True
        assert row["dimensions"] is None
        assert "ix_ai_provider_configs_capability" in indexes

        migration.op = Operations(MigrationContext.configure(connection))
        migration.downgrade()
        remaining = {
            column["name"]
            for column in sa.inspect(connection).get_columns("ai_provider_configs")
        }
        assert {"capability", "provider_name", "enabled", "dimensions"}.isdisjoint(remaining)
        assert connection.scalar(
            sa.text("SELECT is_active FROM ai_provider_configs WHERE id = 1")
        ) == 1


def test_downgrade_keeps_only_the_latest_text_config_active() -> None:
    migration = _load_migration()
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    configs = sa.Table(
        "ai_provider_configs",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("capability", sa.String(32), nullable=False),
        sa.Column("provider_name", sa.String(80), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("model_name", sa.String(200), nullable=False),
        sa.Column("api_key_encrypted", sa.Text(), nullable=False),
        sa.Column("dimensions", sa.Integer()),
        sa.Column("is_active", sa.Boolean(), nullable=False),
    )
    sa.Index("ix_ai_provider_configs_capability", configs.c.capability)
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(configs.insert(), [
            {
                "id": 1,
                "capability": "text",
                "provider_name": "dashscope",
                "enabled": True,
                "base_url": "https://model.example/v1",
                "model_name": "old-text",
                "api_key_encrypted": "encrypted-1",
                "dimensions": None,
                "is_active": True,
            },
            {
                "id": 2,
                "capability": "text",
                "provider_name": "dashscope",
                "enabled": True,
                "base_url": "https://model.example/v1",
                "model_name": "latest-text",
                "api_key_encrypted": "encrypted-2",
                "dimensions": None,
                "is_active": False,
            },
            {
                "id": 3,
                "capability": "image_generation",
                "provider_name": "dashscope",
                "enabled": True,
                "base_url": "https://image.example/v1",
                "model_name": "image-model",
                "api_key_encrypted": "encrypted-3",
                "dimensions": None,
                "is_active": True,
            },
            {
                "id": 4,
                "capability": "text",
                "provider_name": "dashscope",
                "enabled": False,
                "base_url": "https://disabled.example/v1",
                "model_name": "disabled-latest-text",
                "api_key_encrypted": "encrypted-4",
                "dimensions": None,
                "is_active": True,
            },
        ])

        migration.op = Operations(MigrationContext.configure(connection))
        migration.downgrade()

        active_rows = connection.execute(
            sa.text("SELECT id, is_active FROM ai_provider_configs ORDER BY id")
        ).mappings().all()
        remaining_columns = {
            column["name"]
            for column in sa.inspect(connection).get_columns("ai_provider_configs")
        }

    assert active_rows == [
        {"id": 1, "is_active": 0},
        {"id": 2, "is_active": 1},
        {"id": 3, "is_active": 0},
        {"id": 4, "is_active": 0},
    ]
    assert "capability" not in remaining_columns

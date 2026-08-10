from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "20260810_03_database_integrity_indexes.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("database_integrity_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _create_legacy_schema(
    engine: sa.Engine,
    *,
    identity_numbers: list[str | None],
    identity_index_unique: bool = False,
    legacy_url_index_name: str | None = "ix_material_candidates_canonical_url",
    unknown_url_index_names: tuple[str, ...] = (),
    include_hash_index: bool = True,
) -> None:
    metadata = sa.MetaData()
    users = sa.Table(
        "users",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("identity_no", sa.String(32), nullable=True),
    )
    sa.Index(
        "ix_users_identity_no",
        users.c.identity_no,
        unique=identity_index_unique,
    )

    candidates = sa.Table(
        "material_candidates",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("canonical_url", sa.String(1000), nullable=False),
        sa.Column("canonical_url_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
    )
    if legacy_url_index_name is not None:
        sa.Index(legacy_url_index_name, candidates.c.canonical_url)
    for index_name in unknown_url_index_names:
        sa.Index(index_name, candidates.c.canonical_url)
    if include_hash_index:
        sa.Index(
            "ix_material_candidates_canonical_url_hash",
            candidates.c.canonical_url_hash,
        )
    sa.Index(
        "ix_material_candidates_canonical_url_status",
        candidates.c.canonical_url,
        candidates.c.status,
    )
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            users.insert(),
            [
                {"id": index, "identity_no": identity_no}
                for index, identity_no in enumerate(identity_numbers, start=1)
            ],
        )


def _run_upgrade(connection: sa.Connection, migration) -> None:
    migration.op = Operations(MigrationContext.configure(connection))
    migration.upgrade()


def test_database_integrity_migration_follows_multimodal_head() -> None:
    migration = _load_migration()

    assert migration.revision == "20260810_03"
    assert migration.down_revision == "20260810_02"


def test_upgrade_replaces_non_unique_identity_index_and_drops_legacy_url_index() -> None:
    migration = _load_migration()
    engine = sa.create_engine("sqlite:///:memory:")
    _create_legacy_schema(
        engine,
        identity_numbers=["20260001", "20260002", None, None],
        legacy_url_index_name="IX_MATERIAL_CANDIDATES_CANONICAL_URL",
    )

    with engine.begin() as connection:
        _run_upgrade(connection, migration)

        users_indexes = {
            index["name"]: index for index in sa.inspect(connection).get_indexes("users")
        }
        candidate_indexes = {
            index["name"]
            for index in sa.inspect(connection).get_indexes("material_candidates")
        }

    assert "ix_users_identity_no" not in users_indexes
    assert users_indexes["ux_users_identity_no"]["column_names"] == ["identity_no"]
    assert bool(users_indexes["ux_users_identity_no"]["unique"]) is True
    assert "IX_MATERIAL_CANDIDATES_CANONICAL_URL" not in candidate_indexes
    assert "ix_material_candidates_canonical_url_hash" in candidate_indexes
    assert "ix_material_candidates_canonical_url_status" in candidate_indexes


def test_upgrade_is_idempotent_when_identity_index_is_already_unique() -> None:
    migration = _load_migration()
    engine = sa.create_engine("sqlite:///:memory:")
    _create_legacy_schema(
        engine,
        identity_numbers=["20260001", "20260002"],
        identity_index_unique=True,
    )

    with engine.begin() as connection:
        _run_upgrade(connection, migration)
        _run_upgrade(connection, migration)

        indexes = sa.inspect(connection).get_indexes("users")

    identity_indexes = [
        index for index in indexes if index["column_names"] == ["identity_no"]
    ]
    assert len(identity_indexes) == 1
    assert bool(identity_indexes[0]["unique"]) is True


def test_duplicate_identity_numbers_fail_before_any_index_ddl() -> None:
    migration = _load_migration()
    engine = sa.create_engine("sqlite:///:memory:")
    duplicate_identity_no = "110101200001011234"
    _create_legacy_schema(
        engine,
        identity_numbers=[duplicate_identity_no, duplicate_identity_no],
    )

    with engine.begin() as connection:
        with pytest.raises(RuntimeError) as exc_info:
            _run_upgrade(connection, migration)

        users_indexes = {
            index["name"]: index for index in sa.inspect(connection).get_indexes("users")
        }
        candidate_indexes = {
            index["name"]
            for index in sa.inspect(connection).get_indexes("material_candidates")
        }

    message = str(exc_info.value)
    assert "duplicate non-NULL values" in message
    assert "Resolve the duplicate users" in message
    assert duplicate_identity_no not in message
    assert bool(users_indexes["ix_users_identity_no"]["unique"]) is False
    assert "ix_material_candidates_canonical_url" in candidate_indexes


def test_unknown_canonical_url_index_blocks_before_any_ddl() -> None:
    migration = _load_migration()
    engine = sa.create_engine("sqlite:///:memory:")
    _create_legacy_schema(
        engine,
        identity_numbers=["20260001", "20260002"],
        unknown_url_index_names=("custom_canonical_url_lookup",),
    )

    with engine.begin() as connection:
        with pytest.raises(RuntimeError, match="unrecognized single-column canonical_url"):
            _run_upgrade(connection, migration)

        users_indexes = {
            index["name"]: index for index in sa.inspect(connection).get_indexes("users")
        }
        candidate_indexes = {
            index["name"]
            for index in sa.inspect(connection).get_indexes("material_candidates")
        }

    assert bool(users_indexes["ix_users_identity_no"]["unique"]) is False
    assert "ix_material_candidates_canonical_url" in candidate_indexes
    assert "custom_canonical_url_lookup" in candidate_indexes


def test_missing_hash_replacement_index_blocks_before_any_ddl() -> None:
    migration = _load_migration()
    engine = sa.create_engine("sqlite:///:memory:")
    _create_legacy_schema(
        engine,
        identity_numbers=["20260001", "20260002"],
        include_hash_index=False,
    )

    with engine.begin() as connection:
        with pytest.raises(RuntimeError, match="single-column replacement index"):
            _run_upgrade(connection, migration)

        users_indexes = {
            index["name"]: index for index in sa.inspect(connection).get_indexes("users")
        }
        candidate_indexes = {
            index["name"]
            for index in sa.inspect(connection).get_indexes("material_candidates")
        }

    assert bool(users_indexes["ix_users_identity_no"]["unique"]) is False
    assert "ix_material_candidates_canonical_url" in candidate_indexes


def test_retry_finishes_old_identity_index_cleanup_after_replacement_exists() -> None:
    migration = _load_migration()
    engine = sa.create_engine("sqlite:///:memory:")
    _create_legacy_schema(
        engine,
        identity_numbers=["20260001", "20260002"],
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX ux_users_identity_no ON users (identity_no)"
        )

    with engine.begin() as connection:
        _run_upgrade(connection, migration)
        users_indexes = {
            index["name"]: index for index in sa.inspect(connection).get_indexes("users")
        }

    assert "ix_users_identity_no" not in users_indexes
    assert bool(users_indexes["ux_users_identity_no"]["unique"]) is True

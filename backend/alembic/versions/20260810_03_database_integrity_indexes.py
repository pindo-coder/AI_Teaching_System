"""repair legacy URL indexes and enforce user identity uniqueness

Revision ID: 20260810_03
Revises: 20260810_02
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "20260810_03"
down_revision = "20260810_02"
branch_labels = None
depends_on = None


MATERIAL_CANDIDATE_TABLE = "material_candidates"
USERS_TABLE = "users"
IDENTITY_INDEX_NAME = "ix_users_identity_no"
IDENTITY_REPLACEMENT_INDEX_NAME = "ux_users_identity_no"
KNOWN_LEGACY_CANONICAL_URL_INDEX_NAME = "ix_material_candidates_canonical_url"


def _index_columns(index: Mapping[str, Any]) -> tuple[object, ...]:
    # Preserve ``None`` placeholders used by inspectors for expression indexes;
    # filtering them could mistake a composite expression index for a plain
    # single-column index and drop it accidentally.
    return tuple(
        column.casefold() if isinstance(column, str) else column
        for column in (index.get("column_names") or ())
    )


def _normalized_name(value: object) -> str:
    return str(value or "").casefold()


def _has_identity_uniqueness(
    indexes: list[dict[str, Any]],
    unique_constraints: list[dict[str, Any]],
) -> bool:
    if any(
        _index_columns(index) == ("identity_no",) and bool(index.get("unique"))
        for index in indexes
    ):
        return True

    # Some dialects expose a UNIQUE constraint separately from indexes.
    return any(
        tuple(
            column.casefold() if isinstance(column, str) else column
            for column in (constraint.get("column_names") or ())
        )
        == ("identity_no",)
        for constraint in unique_constraints
    )


def _masked_identity_no(value: object) -> str:
    text = str(value)
    if len(text) <= 4:
        return "*" * len(text)
    return f"{'*' * min(len(text) - 4, 8)}{text[-4:]}"


def _assert_identity_values_are_unique(bind: sa.Connection) -> None:
    duplicate = bind.execute(
        sa.text(
            "SELECT identity_no, COUNT(*) AS duplicate_count "
            "FROM users "
            "WHERE identity_no IS NOT NULL "
            "GROUP BY identity_no "
            "HAVING COUNT(*) > 1 "
            "ORDER BY duplicate_count DESC "
            "LIMIT 1"
        )
    ).mappings().first()
    if duplicate is None:
        return

    masked_value = _masked_identity_no(duplicate["identity_no"])
    raise RuntimeError(
        "Cannot enforce users.identity_no uniqueness: duplicate non-NULL values exist "
        f"(sample {masked_value!r} appears {duplicate['duplicate_count']} times). "
        "Resolve the duplicate users, then rerun `alembic upgrade head`."
    )


def _identity_index_plan(bind: sa.Connection) -> tuple[str, str | None]:
    inspector = sa.inspect(bind)
    if not inspector.has_table(USERS_TABLE):
        raise RuntimeError(
            "Cannot enforce users.identity_no uniqueness: the users table is missing. "
            "Restore the database schema, then rerun `alembic upgrade head`."
        )

    columns = {
        _normalized_name(column["name"])
        for column in inspector.get_columns(USERS_TABLE)
    }
    if "identity_no" not in columns:
        raise RuntimeError(
            "Cannot enforce users.identity_no uniqueness: the identity_no column is missing. "
            "Restore the database schema, then rerun `alembic upgrade head`."
        )

    indexes = inspector.get_indexes(USERS_TABLE)
    unique_constraints = inspector.get_unique_constraints(USERS_TABLE)
    named_indexes = [
        index
        for index in indexes
        if _normalized_name(index.get("name")) == IDENTITY_INDEX_NAME.casefold()
    ]
    if len(named_indexes) > 1:
        raise RuntimeError(
            f"Cannot repair {IDENTITY_INDEX_NAME}: multiple case-insensitive name matches exist. "
            "Resolve the conflicting indexes, then rerun `alembic upgrade head`."
        )

    named_index = named_indexes[0] if named_indexes else None
    if named_index is not None and _index_columns(named_index) != ("identity_no",):
        raise RuntimeError(
            f"Cannot create {IDENTITY_INDEX_NAME}: that index name is already used "
            "for different columns. Rename the conflicting index, then rerun "
            "`alembic upgrade head`."
        )

    has_unique_index = _has_identity_uniqueness(indexes, unique_constraints)
    if has_unique_index:
        if named_index is not None and not bool(named_index.get("unique")):
            # A prior run may have created the replacement unique index before
            # failing to remove the old non-unique index. Retrying only needs the
            # safe cleanup step.
            return "drop_redundant", str(named_index["name"])
        return "none", None

    # Check before any DDL. MySQL commits DDL implicitly, so a duplicate-data failure
    # must not leave the migration half-applied.
    _assert_identity_values_are_unique(bind)

    if named_index is not None:
        replacement_matches = [
            index
            for index in indexes
            if _normalized_name(index.get("name"))
            == IDENTITY_REPLACEMENT_INDEX_NAME.casefold()
        ]
        if replacement_matches:
            raise RuntimeError(
                f"Cannot create the replacement index {IDENTITY_REPLACEMENT_INDEX_NAME}: "
                "that name is already in use. Resolve the conflicting index, then rerun "
                "`alembic upgrade head`."
            )
        return "replace", str(named_index["name"])

    return "create", None


def _apply_identity_index_plan(plan: tuple[str, str | None]) -> None:
    action, old_index_name = plan
    if action == "none":
        return
    if action == "drop_redundant":
        assert old_index_name is not None
        op.drop_index(old_index_name, table_name=USERS_TABLE)
        return
    if action == "replace":
        assert old_index_name is not None
        # Build the unique replacement first. If MySQL commits it and the later
        # DROP fails, uniqueness remains protected and a rerun finishes cleanup.
        op.create_index(
            IDENTITY_REPLACEMENT_INDEX_NAME,
            USERS_TABLE,
            ["identity_no"],
            unique=True,
        )
        op.drop_index(old_index_name, table_name=USERS_TABLE)
        return
    if action != "create":  # pragma: no cover - internal plan invariant
        raise RuntimeError(f"Unknown identity index repair action: {action}")

    op.create_index(
        IDENTITY_INDEX_NAME,
        USERS_TABLE,
        ["identity_no"],
        unique=True,
    )


def _canonical_url_indexes_to_drop(bind: sa.Connection) -> list[str]:
    inspector = sa.inspect(bind)
    if not inspector.has_table(MATERIAL_CANDIDATE_TABLE):
        raise RuntimeError(
            "Cannot verify the canonical URL index replacement: the material_candidates "
            "table is missing. Restore the database schema, then rerun "
            "`alembic upgrade head`."
        )

    columns = {
        _normalized_name(column["name"])
        for column in inspector.get_columns(MATERIAL_CANDIDATE_TABLE)
    }
    missing_columns = {"canonical_url", "canonical_url_hash"} - columns
    if missing_columns:
        raise RuntimeError(
            "Cannot verify the canonical URL index replacement: missing column(s) "
            f"{', '.join(sorted(missing_columns))}. Restore the database schema, "
            "then rerun `alembic upgrade head`."
        )

    indexes = inspector.get_indexes(MATERIAL_CANDIDATE_TABLE)
    if not any(
        _index_columns(index) == ("canonical_url_hash",)
        for index in indexes
    ):
        raise RuntimeError(
            "Cannot remove the legacy canonical_url index: canonical_url_hash does not "
            "have a single-column replacement index. Create or restore the hash index, "
            "then rerun `alembic upgrade head`."
        )

    reserved_name_matches = [
        index
        for index in indexes
        if _normalized_name(index.get("name"))
        == KNOWN_LEGACY_CANONICAL_URL_INDEX_NAME.casefold()
    ]
    if any(
        _index_columns(index) != ("canonical_url",)
        for index in reserved_name_matches
    ):
        raise RuntimeError(
            f"Cannot remove {KNOWN_LEGACY_CANONICAL_URL_INDEX_NAME}: that name is used "
            "for an unexpected index definition. Rename the custom index, then rerun "
            "`alembic upgrade head`."
        )

    canonical_url_indexes = [
        index
        for index in indexes
        if _index_columns(index) == ("canonical_url",)
    ]
    unknown_indexes = [
        str(index.get("name") or "<unnamed>")
        for index in canonical_url_indexes
        if _normalized_name(index.get("name"))
        != KNOWN_LEGACY_CANONICAL_URL_INDEX_NAME.casefold()
    ]
    if unknown_indexes:
        raise RuntimeError(
            "Refusing to remove unrecognized single-column canonical_url index(es): "
            f"{', '.join(sorted(unknown_indexes, key=str.casefold))}. Review and remove "
            "or rename them explicitly, then rerun `alembic upgrade head`."
        )

    known_indexes = [
        index for index in canonical_url_indexes
        if _normalized_name(index.get("name"))
        == KNOWN_LEGACY_CANONICAL_URL_INDEX_NAME.casefold()
    ]
    if any(bool(index.get("unique")) for index in known_indexes):
        raise RuntimeError(
            f"Refusing to remove {KNOWN_LEGACY_CANONICAL_URL_INDEX_NAME}: the known "
            "legacy index was non-unique, but this installation has a unique index. "
            "Review it manually, then rerun `alembic upgrade head`."
        )
    return [str(index["name"]) for index in known_indexes]


def upgrade() -> None:
    bind = op.get_bind()
    # 早期通过 create_all 建立的开发库可能没有 identity_no；该字段可空，
    # 先补列再执行唯一性校验，避免整条迁移链被旧库阻断。
    inspector = sa.inspect(bind)
    if inspector.has_table(USERS_TABLE):
        user_columns = {str(column["name"]).casefold() for column in inspector.get_columns(USERS_TABLE)}
        if "identity_no" not in user_columns:
            op.add_column(USERS_TABLE, sa.Column("identity_no", sa.String(32), nullable=True))
    # Complete every structural/data validation before the first DDL statement.
    # This avoids a canonical-index error leaving MySQL after an unrelated partial
    # identity-index repair.
    identity_plan = _identity_index_plan(bind)
    canonical_url_indexes = _canonical_url_indexes_to_drop(bind)

    _apply_identity_index_plan(identity_plan)
    for index_name in canonical_url_indexes:
        op.drop_index(index_name, table_name=MATERIAL_CANDIDATE_TABLE)


def downgrade() -> None:
    # This is a data-integrity repair. Recreating a VARCHAR(1000) index can exceed
    # MySQL's utf8mb4 key limit, while removing identity uniqueness can reintroduce
    # ambiguous accounts. A downgrade intentionally keeps both safe outcomes.
    pass

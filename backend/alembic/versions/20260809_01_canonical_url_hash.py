"""index canonical material URLs through a fixed-length digest

Revision ID: 20260809_01
Revises: 20260807_01
"""

from __future__ import annotations

import hashlib

from alembic import op
import sqlalchemy as sa


revision = "20260809_01"
down_revision = "20260807_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("material_candidates")}
    indexes = {index["name"] for index in inspector.get_indexes("material_candidates")}

    if "canonical_url_hash" not in columns:
        op.add_column(
            "material_candidates",
            sa.Column("canonical_url_hash", sa.String(length=64), nullable=False, server_default=""),
        )

    rows = bind.execute(sa.text(
        "SELECT id, canonical_url FROM material_candidates "
        "WHERE canonical_url_hash IS NULL OR canonical_url_hash = ''"
    )).mappings()
    for row in rows:
        digest = hashlib.sha256((row["canonical_url"] or "").encode("utf-8")).hexdigest()
        bind.execute(
            sa.text("UPDATE material_candidates SET canonical_url_hash = :digest WHERE id = :id"),
            {"digest": digest, "id": row["id"]},
        )

    if "ix_material_candidates_canonical_url_hash" not in indexes:
        op.create_index(
            "ix_material_candidates_canonical_url_hash",
            "material_candidates",
            ["canonical_url_hash"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes("material_candidates")}
    columns = {column["name"] for column in inspector.get_columns("material_candidates")}
    if "ix_material_candidates_canonical_url_hash" in indexes:
        op.drop_index("ix_material_candidates_canonical_url_hash", table_name="material_candidates")
    if "canonical_url_hash" in columns:
        op.drop_column("material_candidates", "canonical_url_hash")

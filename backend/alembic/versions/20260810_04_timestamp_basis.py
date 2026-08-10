"""mark the storage basis of legacy wall-clock timestamps

Revision ID: 20260810_04
Revises: 20260810_03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260810_04"
down_revision = "20260810_03"
branch_labels = None
depends_on = None


TIME_BASIS_COLUMNS = (
    ("news_items", "published_time_is_utc"),
    ("teacher_assignments", "due_time_is_utc"),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    missing_tables = [
        table_name
        for table_name, _column_name in TIME_BASIS_COLUMNS
        if not inspector.has_table(table_name)
    ]
    if missing_tables:
        raise RuntimeError(
            "timestamp basis migration requires existing tables: "
            + ", ".join(missing_tables)
        )
    for table_name, column_name in TIME_BASIS_COLUMNS:
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        if column_name in columns:
            continue
        # Existing values remain byte-for-byte unchanged. False records the old
        # contract: a Chinese business wall time was stored without tzinfo.
        op.add_column(
            table_name,
            sa.Column(
                column_name,
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    missing_tables = [
        table_name
        for table_name, _column_name in TIME_BASIS_COLUMNS
        if not inspector.has_table(table_name)
    ]
    if missing_tables:
        raise RuntimeError(
            "timestamp basis migration requires existing tables: "
            + ", ".join(missing_tables)
        )
    for table_name, column_name in reversed(TIME_BASIS_COLUMNS):
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        if column_name in columns:
            op.drop_column(table_name, column_name)

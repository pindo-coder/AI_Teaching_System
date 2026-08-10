"""expand full-text snapshots for MySQL

Revision ID: 20260810_01
Revises: 20260809_01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260810_01"
down_revision = "20260809_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite TEXT 没有 MySQL TEXT 的 65KB 限制，无需变更。
    if op.get_bind().dialect.name != "mysql":
        return

    op.alter_column(
        "material_snapshots",
        "content",
        existing_type=sa.Text(),
        type_=mysql.LONGTEXT(),
        existing_nullable=False,
    )
    op.alter_column(
        "agent_runs",
        "context_snapshot",
        existing_type=sa.Text(),
        type_=mysql.LONGTEXT(),
        existing_nullable=True,
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "mysql":
        return

    op.alter_column(
        "agent_runs",
        "context_snapshot",
        existing_type=mysql.LONGTEXT(),
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.alter_column(
        "material_snapshots",
        "content",
        existing_type=mysql.LONGTEXT(),
        type_=sa.Text(),
        existing_nullable=False,
    )

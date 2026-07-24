"""expand document page text for long web materials

Revision ID: 20260722_01
Revises: 20260721_01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260722_01"
down_revision = "20260721_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite 的 TEXT 没有 65KB 限制，只有 MySQL 需要扩容。
    if op.get_bind().dialect.name == "mysql":
        op.alter_column(
            "document_pages",
            "text",
            existing_type=sa.Text(),
            type_=mysql.LONGTEXT(),
            existing_nullable=False,
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "mysql":
        op.alter_column(
            "document_pages",
            "text",
            existing_type=mysql.LONGTEXT(),
            type_=sa.Text(),
            existing_nullable=False,
        )

"""expand chapter content for OCR textbook text

Revision ID: 20260718_01
Revises: 20260717_01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260718_01"
down_revision = "20260717_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "mysql":
        op.alter_column(
            "chapters",
            "content",
            existing_type=sa.Text(),
            type_=mysql.LONGTEXT(),
            existing_nullable=True,
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "mysql":
        op.alter_column(
            "chapters",
            "content",
            existing_type=mysql.LONGTEXT(),
            type_=sa.Text(),
            existing_nullable=True,
        )

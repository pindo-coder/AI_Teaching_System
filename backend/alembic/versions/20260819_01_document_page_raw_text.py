"""preserve raw OCR text alongside cleaned document page text

Revision ID: 20260819_01
Revises: 20260816_02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "20260819_01"
down_revision = "20260816_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    column_type = mysql.LONGTEXT() if bind.dialect.name == "mysql" else sa.Text()
    op.add_column("document_pages", sa.Column("raw_text", column_type, nullable=True))
    op.execute(sa.text("UPDATE document_pages SET raw_text = text WHERE raw_text IS NULL"))
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("document_pages") as batch_op:
            batch_op.alter_column("raw_text", existing_type=sa.Text(), nullable=False)
    else:
        op.alter_column("document_pages", "raw_text", existing_type=column_type, nullable=False)


def downgrade() -> None:
    op.drop_column("document_pages", "raw_text")

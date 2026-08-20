"""Add cache keys for generated review references.

Revision ID: 20260820_02
Revises: 20260820_01
"""

from alembic import op
import sqlalchemy as sa


revision = "20260820_02"
down_revision = "20260820_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # MySQL 5.7 does not allow a DEFAULT on TEXT columns.
    op.add_column("review_practices", sa.Column("reference_cache_key", sa.Text(), nullable=True))
    op.execute(sa.text(
        "UPDATE review_practices SET reference_cache_key = '' WHERE reference_cache_key IS NULL"
    ))
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("review_practices") as batch_op:
            batch_op.alter_column("reference_cache_key", existing_type=sa.Text(), nullable=False)
    else:
        op.alter_column("review_practices", "reference_cache_key", existing_type=sa.Text(), nullable=False)


def downgrade() -> None:
    op.drop_column("review_practices", "reference_cache_key")

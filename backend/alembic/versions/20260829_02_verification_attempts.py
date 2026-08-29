"""Add verification code attempt counter to existing reset-token tables.

Revision ID: 20260829_02
Revises: 20260829_01
"""

from alembic import op
import sqlalchemy as sa


revision = "20260829_02"
down_revision = "20260829_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("password_reset_tokens"):
        return
    columns = {column["name"] for column in inspector.get_columns("password_reset_tokens")}
    if "attempts" not in columns:
        op.add_column(
            "password_reset_tokens",
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("password_reset_tokens"):
        return
    columns = {column["name"] for column in inspector.get_columns("password_reset_tokens")}
    if "attempts" not in columns:
        return
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("password_reset_tokens") as batch_op:
            batch_op.drop_column("attempts")
    else:
        op.drop_column("password_reset_tokens", "attempts")

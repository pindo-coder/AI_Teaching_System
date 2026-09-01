"""Add cancellation marker for workspace Agent executions.

Revision ID: 20260901_01
Revises: 20260829_02
"""

from alembic import op
import sqlalchemy as sa


revision = "20260901_01"
down_revision = "20260829_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("agent_executions"):
        return
    columns = {column["name"] for column in inspector.get_columns("agent_executions")}
    if "cancel_requested" not in columns:
        op.add_column(
            "agent_executions",
            sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("agent_executions"):
        columns = {column["name"] for column in inspector.get_columns("agent_executions")}
        if "cancel_requested" in columns:
            if bind.dialect.name == "sqlite":
                with op.batch_alter_table("agent_executions") as batch_op:
                    batch_op.drop_column("cancel_requested")
            else:
                op.drop_column("agent_executions", "cancel_requested")

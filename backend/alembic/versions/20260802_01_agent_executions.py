"""persist workspace agent executions

Revision ID: 20260802_01
Revises: 20260731_01
"""

from alembic import op
import sqlalchemy as sa

from app.db.base import Base
import app.db.models  # noqa: F401


revision = "20260802_01"
down_revision = "20260731_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.tables["agent_executions"].create(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("agent_executions"):
        op.drop_table("agent_executions")

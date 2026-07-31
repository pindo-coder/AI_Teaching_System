"""agent run and step persistence

Revision ID: 20260728_01
Revises: 20260722_01
"""

from alembic import op
import sqlalchemy as sa

from app.db.base import Base
import app.db.models  # noqa: F401


revision = "20260728_01"
down_revision = "20260722_01"
branch_labels = None
depends_on = None


TABLES = ["agent_runs", "agent_steps"]


def upgrade() -> None:
    bind = op.get_bind()
    for table_name in TABLES:
        Base.metadata.tables[table_name].create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in reversed(TABLES):
        if sa.inspect(bind).has_table(table_name):
            op.drop_table(table_name)

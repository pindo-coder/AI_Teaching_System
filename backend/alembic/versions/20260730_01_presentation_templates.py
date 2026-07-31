"""presentation template persistence

Revision ID: 20260730_01
Revises: 20260728_01
"""

from alembic import op
import sqlalchemy as sa

from app.db.base import Base
import app.db.models  # noqa: F401


revision = "20260730_01"
down_revision = "20260728_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.tables["presentation_templates"].create(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("presentation_templates"):
        op.drop_table("presentation_templates")

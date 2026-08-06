"""authority source discovery and candidate archive

Revision ID: 20260803_01
Revises: 20260802_01
"""

from alembic import op
import sqlalchemy as sa

from app.db.base import Base
import app.db.models  # noqa: F401


revision = "20260803_01"
down_revision = "20260802_01"
branch_labels = None
depends_on = None


TABLES = [
    "source_registries",
    "discovery_jobs",
    "material_candidates",
    "material_snapshots",
]


def upgrade() -> None:
    bind = op.get_bind()
    for table_name in TABLES:
        Base.metadata.tables[table_name].create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in reversed(TABLES):
        if sa.inspect(bind).has_table(table_name):
            op.drop_table(table_name)

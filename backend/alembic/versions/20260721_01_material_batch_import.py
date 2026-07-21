"""central material batch import jobs

Revision ID: 20260721_01
Revises: 20260718_02
"""

from alembic import op
import sqlalchemy as sa

from app.db.base import Base
import app.db.models  # noqa: F401


revision = "20260721_01"
down_revision = "20260718_02"
branch_labels = None
depends_on = None


TABLES = ["material_import_batches", "material_import_items"]


def upgrade() -> None:
    bind = op.get_bind()
    for table_name in TABLES:
        Base.metadata.tables[table_name].create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in reversed(TABLES):
        if sa.inspect(bind).has_table(table_name):
            op.drop_table(table_name)

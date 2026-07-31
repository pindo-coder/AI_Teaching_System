"""add lesson publications

Revision ID: 20260731_01
Revises: 20260730_01
Create Date: 2026-07-31
"""

from alembic import op
import sqlalchemy as sa

from app.db.base import Base
import app.db.models  # noqa: F401


revision = "20260731_01"
down_revision = "20260730_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 早期基线迁移会按当前 SQLAlchemy 元数据为全新数据库创建全部表，
    # 因此后续迁移必须允许目标表已经存在；已有生产数据库则在这里补建。
    Base.metadata.tables["lesson_publications"].create(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("lesson_publications"):
        op.drop_table("lesson_publications")

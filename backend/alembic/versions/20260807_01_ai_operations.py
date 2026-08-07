"""AI provider configuration and call audit logs.

Revision ID: 20260807_01
Revises: 20260804_01
"""

from collections.abc import Sequence

from alembic import op

from app.db.base import Base
import app.db.models  # noqa: F401


revision: str = "20260807_01"
down_revision: str | None = "20260804_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    # 早期基线迁移会对全量 metadata 执行 create_all，因此这里必须兼容
    # 新数据库中表已提前建立、既有数据库中表尚不存在两种情况。
    Base.metadata.tables["ai_provider_configs"].create(bind, checkfirst=True)
    Base.metadata.tables["ai_call_logs"].create(bind, checkfirst=True)


def downgrade() -> None:
    op.drop_table("ai_call_logs")
    op.drop_table("ai_provider_configs")

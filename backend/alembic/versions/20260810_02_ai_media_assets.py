"""Private image and audio assets for the learning assistant.

Revision ID: 20260810_02
Revises: 20260810_01
"""

from collections.abc import Sequence

from alembic import op

from app.db.base import Base
import app.db.models  # noqa: F401


revision: str = "20260810_02"
down_revision: str | None = "20260810_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 复用模型声明，确保 SQLite 与 MySQL 的 LONGTEXT variant 和索引定义一致。
    # 基线迁移会 create_all，因此新库中该表可能已经存在。
    Base.metadata.tables["ai_media_assets"].create(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    Base.metadata.tables["ai_media_assets"].drop(op.get_bind(), checkfirst=True)

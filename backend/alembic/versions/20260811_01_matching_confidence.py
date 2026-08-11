"""separate policy evidence confidence from chapter association confidence

Revision ID: 20260811_01
Revises: 20260810_05
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260811_01"
down_revision = "20260810_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("policy_changes"):
        raise RuntimeError("matching confidence migration requires policy_changes")
    columns = {column["name"] for column in inspector.get_columns("policy_changes")}
    if "evidence_confidence" not in columns:
        op.add_column(
            "policy_changes",
            sa.Column(
                "evidence_confidence",
                sa.Float(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )
    # MySQL DDL 会隐式提交。即使先前执行在加列后失败，重跑时也必须再次清理
    # 历史提醒，避免“字段已存在”让旧算法生成的误报继续生效。
    if "alert_recommended" in columns:
        op.execute(sa.text(
            "UPDATE policy_changes SET alert_recommended = 0"
        ))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("policy_changes"):
        columns = {column["name"] for column in inspector.get_columns("policy_changes")}
        if "evidence_confidence" in columns:
            op.drop_column("policy_changes", "evidence_confidence")

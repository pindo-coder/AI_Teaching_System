"""policy change sync state and teacher notifications

Revision ID: 20260803_03
Revises: 20260803_02
"""

from alembic import op
import sqlalchemy as sa

from app.db.base import Base
import app.db.models  # noqa: F401


revision = "20260803_03"
down_revision = "20260803_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {item["name"] for item in inspector.get_columns("policy_changes")}
    indexes = {item["name"] for item in inspector.get_indexes("policy_changes")}
    if "kb_sync_status" not in columns:
        op.add_column("policy_changes", sa.Column("kb_sync_status", sa.String(length=24), nullable=False, server_default="pending"))
    if "ix_policy_changes_kb_sync_status" not in indexes:
        op.create_index("ix_policy_changes_kb_sync_status", "policy_changes", ["kb_sync_status"])
    if "kb_synced_time" not in columns:
        op.add_column("policy_changes", sa.Column("kb_synced_time", sa.DateTime(), nullable=True))
    if "kb_error" not in columns:
        op.add_column("policy_changes", sa.Column("kb_error", sa.Text(), nullable=True))
    Base.metadata.tables["teaching_notifications"].create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("teaching_notifications"):
        op.drop_table("teaching_notifications")
    inspector = sa.inspect(bind)
    columns = {item["name"] for item in inspector.get_columns("policy_changes")}
    indexes = {item["name"] for item in inspector.get_indexes("policy_changes")}
    if "ix_policy_changes_kb_sync_status" in indexes:
        op.drop_index("ix_policy_changes_kb_sync_status", table_name="policy_changes")
    for name in ("kb_error", "kb_synced_time", "kb_sync_status"):
        if name in columns:
            op.drop_column("policy_changes", name)

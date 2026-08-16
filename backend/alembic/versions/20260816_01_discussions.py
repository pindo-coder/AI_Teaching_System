"""add teacher and student discussion threads and replies

Revision ID: 20260816_01
Revises: 20260811_01
"""

from alembic import op
import sqlalchemy as sa

revision = "20260816_01"
down_revision = "20260811_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    # SQLite 开发环境会由 create_all 预建新模型表；迁移必须能接管这类数据库。
    if not inspector.has_table("discussion_threads"):
        op.create_table(
            "discussion_threads",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("teaching_class_id", sa.Integer(), sa.ForeignKey("teaching_classes.id", ondelete="CASCADE")),
            sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id", ondelete="CASCADE")),
            sa.Column("chapter_id", sa.Integer(), sa.ForeignKey("chapters.id", ondelete="CASCADE")),
            sa.Column("activity_id", sa.Integer(), sa.ForeignKey("classroom_activities.id", ondelete="SET NULL")),
            sa.Column("author_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="published"),
            sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("reply_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_replied_time", sa.DateTime()),
            sa.Column("created_time", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_time", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        for column in ("teaching_class_id", "course_id", "chapter_id", "activity_id", "author_id", "status", "is_pinned", "created_time"):
            op.create_index(f"ix_discussion_threads_{column}", "discussion_threads", [column])
    inspector = sa.inspect(bind)
    if not inspector.has_table("discussion_replies"):
        op.create_table(
            "discussion_replies",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("thread_id", sa.Integer(), sa.ForeignKey("discussion_threads.id", ondelete="CASCADE"), nullable=False),
            sa.Column("author_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("parent_reply_id", sa.Integer(), sa.ForeignKey("discussion_replies.id", ondelete="CASCADE")),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="published"),
            sa.Column("created_time", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_time", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        for column in ("thread_id", "author_id", "parent_reply_id", "status"):
            op.create_index(f"ix_discussion_replies_{column}", "discussion_replies", [column])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("discussion_replies"):
        op.drop_table("discussion_replies")
    if inspector.has_table("discussion_threads"):
        op.drop_table("discussion_threads")

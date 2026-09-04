"""Add private textbook annotations.

Revision ID: 20260904_01
Revises: 20260901_02
"""

from alembic import op
import sqlalchemy as sa


revision = "20260904_01"
down_revision = "20260901_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("textbook_annotations"):
        return
    op.create_table(
        "textbook_annotations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("chapter_id", sa.Integer(), nullable=False),
        sa.Column("block_index", sa.Integer(), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("selected_text", sa.Text(), nullable=False),
        sa.Column("prefix_text", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("suffix_text", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("annotation_type", sa.String(length=20), nullable=False, server_default="key_point"),
        sa.Column("comment", sa.Text(), nullable=False, server_default=""),
        sa.Column("chapter_content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_time", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_time", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "annotation_type IN ('key_point', 'concept', 'question')",
            name="ck_textbook_annotation_type",
        ),
        sa.CheckConstraint("start_offset >= 0", name="ck_textbook_annotation_start_offset"),
        sa.CheckConstraint("end_offset > start_offset", name="ck_textbook_annotation_offset_order"),
        sa.ForeignKeyConstraint(["chapter_id"], ["chapters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_textbook_annotations_user_id", "textbook_annotations", ["user_id"])
    op.create_index("ix_textbook_annotations_course_id", "textbook_annotations", ["course_id"])
    op.create_index("ix_textbook_annotations_chapter_id", "textbook_annotations", ["chapter_id"])
    op.create_index(
        "ix_textbook_annotations_user_chapter",
        "textbook_annotations",
        ["user_id", "chapter_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("textbook_annotations"):
        op.drop_table("textbook_annotations")

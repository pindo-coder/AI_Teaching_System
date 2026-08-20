"""Persist review answers and AI references.

Revision ID: 20260820_01
Revises: 20260819_01
"""

from alembic import op
import sqlalchemy as sa


revision = "20260820_01"
down_revision = "20260819_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # MySQL 5.7 rejects defaults on TEXT and JSON columns. Add the columns as
    # nullable, backfill existing rows, then enforce the model's NOT NULL
    # invariant without leaving a database-level default behind.
    op.add_column("review_practices", sa.Column("student_answer", sa.Text(), nullable=True))
    op.add_column("review_practices", sa.Column("ai_reference_answer", sa.Text(), nullable=True))
    op.add_column("review_practices", sa.Column("reference_knowledge_points", sa.JSON(), nullable=True))
    op.execute(sa.text("UPDATE review_practices SET student_answer = '' WHERE student_answer IS NULL"))
    op.execute(sa.text("UPDATE review_practices SET ai_reference_answer = '' WHERE ai_reference_answer IS NULL"))
    op.execute(sa.text(
        "UPDATE review_practices SET reference_knowledge_points = '[]' "
        "WHERE reference_knowledge_points IS NULL"
    ))
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("review_practices") as batch_op:
            batch_op.alter_column("student_answer", existing_type=sa.Text(), nullable=False)
            batch_op.alter_column("ai_reference_answer", existing_type=sa.Text(), nullable=False)
            batch_op.alter_column("reference_knowledge_points", existing_type=sa.JSON(), nullable=False)
    else:
        op.alter_column("review_practices", "student_answer", existing_type=sa.Text(), nullable=False)
        op.alter_column("review_practices", "ai_reference_answer", existing_type=sa.Text(), nullable=False)
        op.alter_column(
            "review_practices", "reference_knowledge_points", existing_type=sa.JSON(), nullable=False
        )


def downgrade() -> None:
    op.drop_column("review_practices", "reference_knowledge_points")
    op.drop_column("review_practices", "ai_reference_answer")
    op.drop_column("review_practices", "student_answer")

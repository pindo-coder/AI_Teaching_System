"""allow global discussions without class, course, or chapter scope

Revision ID: 20260816_02
Revises: 20260816_01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260816_02"
down_revision = "20260816_01"
branch_labels = None
depends_on = None

SCOPE_COLUMNS = ("teaching_class_id", "course_id", "chapter_id")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("discussion_threads"):
        raise RuntimeError("discussion nullable-scope migration requires discussion_threads")
    columns = {item["name"]: item for item in inspector.get_columns("discussion_threads")}
    required = [name for name in SCOPE_COLUMNS if name not in columns]
    if required:
        raise RuntimeError(f"discussion_threads is missing columns: {', '.join(required)}")
    pending = [name for name in SCOPE_COLUMNS if not columns[name].get("nullable", True)]
    if not pending:
        return
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("discussion_threads") as batch_op:
            for name in pending:
                batch_op.alter_column(name, existing_type=sa.Integer(), nullable=True)
    else:
        for name in pending:
            op.alter_column("discussion_threads", name, existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    bind = op.get_bind()
    null_count = bind.scalar(sa.text(
        "SELECT COUNT(*) FROM discussion_threads "
        "WHERE teaching_class_id IS NULL OR course_id IS NULL OR chapter_id IS NULL"
    ))
    if null_count:
        raise RuntimeError("cannot restore required discussion scope while global discussions exist")
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("discussion_threads") as batch_op:
            for name in SCOPE_COLUMNS:
                batch_op.alter_column(name, existing_type=sa.Integer(), nullable=False)
    else:
        for name in SCOPE_COLUMNS:
            op.alter_column("discussion_threads", name, existing_type=sa.Integer(), nullable=False)

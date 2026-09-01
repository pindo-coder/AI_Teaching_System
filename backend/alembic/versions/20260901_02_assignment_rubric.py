"""Add persisted rubric data to teacher assignments.

Revision ID: 20260901_02
Revises: 20260901_01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.exc import NoInspectionAvailable


revision = "20260901_02"
down_revision = "20260901_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # MySQL 5.7 rejects DEFAULT expressions on JSON columns. Add the field as
    # nullable, backfill existing rows, then enforce NOT NULL without a default.
    try:
        inspector = sa.inspect(bind)
        if not inspector.has_table("teacher_assignments"):
            return
        columns = {column["name"] for column in inspector.get_columns("teacher_assignments")}
    except NoInspectionAvailable:
        # Offline SQL generation has no inspector; emit the full migration.
        columns = set()
    if "rubric" not in columns:
        op.add_column(
            "teacher_assignments",
            sa.Column("rubric", sa.JSON(), nullable=True),
        )
    op.execute(sa.text("UPDATE teacher_assignments SET rubric = '{}' WHERE rubric IS NULL"))
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("teacher_assignments") as batch_op:
            batch_op.alter_column("rubric", existing_type=sa.JSON(), nullable=False)
    else:
        op.alter_column("teacher_assignments", "rubric", existing_type=sa.JSON(), nullable=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("teacher_assignments"):
        return
    columns = {column["name"] for column in inspector.get_columns("teacher_assignments")}
    if "rubric" not in columns:
        return
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("teacher_assignments") as batch_op:
            batch_op.drop_column("rubric")
    else:
        op.drop_column("teacher_assignments", "rubric")

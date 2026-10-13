"""add structured assignment completion policies and evidence progress

Revision ID: 20261013_01
Revises: 20260906_01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.exc import NoInspectionAvailable


revision = "20261013_01"
down_revision = "20260906_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    try:
        inspector = sa.inspect(bind)
    except NoInspectionAvailable:
        inspector = None

    if inspector is None or inspector.has_table("teacher_assignments"):
        columns = {
            column["name"]
            for column in inspector.get_columns("teacher_assignments")
        } if inspector is not None else set()
        if "completion_policy" not in columns:
            # MySQL rejects defaults on JSON. Add nullable, backfill, then enforce.
            op.add_column(
                "teacher_assignments",
                sa.Column("completion_policy", sa.JSON(), nullable=True),
            )
            op.execute(sa.text(
                "UPDATE teacher_assignments SET completion_policy = '{}' "
                "WHERE completion_policy IS NULL"
            ))
            if bind.dialect.name == "sqlite":
                with op.batch_alter_table("teacher_assignments") as batch_op:
                    batch_op.alter_column(
                        "completion_policy", existing_type=sa.JSON(), nullable=False
                    )
            else:
                op.alter_column(
                    "teacher_assignments",
                    "completion_policy",
                    existing_type=sa.JSON(),
                    nullable=False,
                )

    if inspector is not None and inspector.has_table("assignment_requirement_progress"):
        return
    op.create_table(
        "assignment_requirement_progress",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("assignment_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("requirement_key", sa.String(length=64), nullable=False),
        sa.Column("current_value", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("target_value", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("progress_value", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="not_started"),
        sa.Column("evidence_summary", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("completed_time", sa.DateTime(), nullable=True),
        sa.Column("updated_time", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["assignment_id"], ["teacher_assignments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "assignment_id", "user_id", "requirement_key",
            name="uq_assignment_user_requirement",
        ),
    )
    op.create_index(
        "ix_assignment_requirement_progress_assignment_id",
        "assignment_requirement_progress",
        ["assignment_id"],
    )
    op.create_index(
        "ix_assignment_requirement_progress_user_id",
        "assignment_requirement_progress",
        ["user_id"],
    )
    op.create_index(
        "ix_assignment_requirement_progress_status",
        "assignment_requirement_progress",
        ["status"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("assignment_requirement_progress"):
        op.drop_table("assignment_requirement_progress")
    if inspector.has_table("teacher_assignments"):
        columns = {column["name"] for column in inspector.get_columns("teacher_assignments")}
        if "completion_policy" in columns:
            if bind.dialect.name == "sqlite":
                with op.batch_alter_table("teacher_assignments") as batch_op:
                    batch_op.drop_column("completion_policy")
            else:
                op.drop_column("teacher_assignments", "completion_policy")

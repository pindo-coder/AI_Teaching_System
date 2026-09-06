"""extend classroom activities with typed submissions, groups, and reviews

Revision ID: 20260906_01
Revises: 20260904_01
"""

from collections import defaultdict

from alembic import op
import sqlalchemy as sa


revision = "20260906_01"
down_revision = "20260904_01"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _add(table: str, column: sa.Column) -> None:
    if column.name not in _columns(table):
        op.add_column(table, column)


def _index(name: str, table: str, columns: list[str], *, unique: bool = False) -> None:
    existing = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, columns, unique=unique)


def _foreign_key(name: str, source: str, referent: str, local: list[str], remote: list[str], ondelete: str) -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return
    existing = sa.inspect(bind).get_foreign_keys(source)
    if any(item.get("referred_table") == referent and item.get("constrained_columns") == local for item in existing):
        return
    op.create_foreign_key(name, source, referent, local, remote, ondelete=ondelete)


def _number_existing_attempts() -> None:
    bind = op.get_bind()
    rows = sa.table(
        "classroom_responses",
        sa.column("id", sa.Integer()),
        sa.column("activity_id", sa.Integer()),
        sa.column("user_id", sa.Integer()),
        sa.column("attempt_no", sa.Integer()),
    )
    grouped: dict[tuple[int, int], int] = defaultdict(int)
    result = bind.execute(sa.select(rows).order_by(rows.c.activity_id, rows.c.user_id, rows.c.id))
    for row in result:
        key = (row.activity_id, row.user_id)
        grouped[key] += 1
        if grouped[key] != 1:
            bind.execute(
                sa.update(rows).where(rows.c.id == row.id).values(attempt_no=grouped[key])
            )


def _backfill_group_leaders() -> None:
    bind = op.get_bind()
    groups = sa.table(
        "class_groups",
        sa.column("id", sa.Integer()),
        sa.column("leader_user_id", sa.Integer()),
    )
    members = sa.table(
        "class_group_members",
        sa.column("group_id", sa.Integer()),
        sa.column("user_id", sa.Integer()),
    )
    for group_id, in bind.execute(sa.select(groups.c.id).where(groups.c.leader_user_id.is_(None))):
        leader_id = bind.scalar(sa.select(members.c.user_id).where(
            members.c.group_id == group_id
        ).order_by(members.c.user_id).limit(1))
        if leader_id is not None:
            bind.execute(sa.update(groups).where(groups.c.id == group_id).values(leader_user_id=leader_id))


def upgrade() -> None:
    _add("classroom_activities", sa.Column("activity_type", sa.String(20), nullable=False, server_default="qa"))
    _add("classroom_activities", sa.Column("response_limit", sa.Integer(), nullable=False, server_default="1"))
    _add("classroom_activities", sa.Column("config", sa.JSON(), nullable=True))
    _add("classroom_activities", sa.Column("deadline_time", sa.DateTime(), nullable=True))
    _add("classroom_activities", sa.Column("grouping_mode", sa.String(20), nullable=True))
    _index("ix_classroom_activities_activity_type", "classroom_activities", ["activity_type"])

    _add("classroom_responses", sa.Column("attempt_no", sa.Integer(), nullable=False, server_default="1"))
    _add("classroom_responses", sa.Column("group_id", sa.Integer(), nullable=True))
    _add("classroom_responses", sa.Column("teacher_comment", sa.Text(), nullable=True))
    _add("classroom_responses", sa.Column("ai_comment", sa.Text(), nullable=True))
    _add("classroom_responses", sa.Column("commented_by", sa.Integer(), nullable=True))
    _add("classroom_responses", sa.Column("commented_time", sa.DateTime(), nullable=True))
    _number_existing_attempts()
    _index("ix_classroom_responses_group_id", "classroom_responses", ["group_id"])
    _index(
        "uq_classroom_response_activity_user_attempt",
        "classroom_responses",
        ["activity_id", "user_id", "attempt_no"],
        unique=True,
    )
    _foreign_key("fk_classroom_responses_group", "classroom_responses", "class_groups", ["group_id"], ["id"], "SET NULL")
    _foreign_key("fk_classroom_responses_commented_by", "classroom_responses", "users", ["commented_by"], ["id"], "SET NULL")

    _add("class_groups", sa.Column("leader_user_id", sa.Integer(), nullable=True))
    _index("ix_class_groups_leader_user_id", "class_groups", ["leader_user_id"])
    _backfill_group_leaders()
    _foreign_key("fk_class_groups_leader", "class_groups", "users", ["leader_user_id"], ["id"], "SET NULL")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table, name in (
        ("classroom_responses", "uq_classroom_response_activity_user_attempt"),
        ("classroom_responses", "ix_classroom_responses_group_id"),
        ("classroom_activities", "ix_classroom_activities_activity_type"),
        ("class_groups", "ix_class_groups_leader_user_id"),
    ):
        if any(item["name"] == name for item in inspector.get_indexes(table)):
            op.drop_index(name, table_name=table)
    if bind.dialect.name != "sqlite":
        for table, referent, column in (
            ("classroom_responses", "class_groups", "group_id"),
            ("classroom_responses", "users", "commented_by"),
            ("class_groups", "users", "leader_user_id"),
        ):
            for constraint in sa.inspect(bind).get_foreign_keys(table):
                if constraint.get("referred_table") == referent and constraint.get("constrained_columns") == [column] and constraint.get("name"):
                    op.drop_constraint(constraint["name"], table, type_="foreignkey")
    for table, column in (
        ("classroom_responses", "commented_time"), ("classroom_responses", "commented_by"),
        ("classroom_responses", "ai_comment"), ("classroom_responses", "teacher_comment"),
        ("classroom_responses", "group_id"), ("classroom_responses", "attempt_no"),
        ("classroom_activities", "grouping_mode"), ("classroom_activities", "deadline_time"),
        ("classroom_activities", "config"), ("classroom_activities", "response_limit"),
        ("classroom_activities", "activity_type"), ("class_groups", "leader_user_id"),
    ):
        if column in _columns(table):
            op.drop_column(table, column)

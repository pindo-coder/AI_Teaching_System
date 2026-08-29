"""Add email verification and password recovery data.

Revision ID: 20260829_01
Revises: 20260820_02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.exc import NoInspectionAvailable


revision = "20260829_01"
down_revision = "20260820_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    try:
        inspector = sa.inspect(bind)
        user_columns = {column["name"] for column in inspector.get_columns("users")}
    except NoInspectionAvailable:
        inspector = None
        user_columns = set()
    additions = [
        ("email", sa.Column("email", sa.String(length=254), nullable=True)),
        ("email_hash", sa.Column("email_hash", sa.String(length=64), nullable=True)),
        ("email_verified_at", sa.Column("email_verified_at", sa.DateTime(), nullable=True)),
        ("password_changed_at", sa.Column("password_changed_at", sa.DateTime(), nullable=True)),
        ("auth_version", sa.Column("auth_version", sa.Integer(), nullable=False, server_default="0")),
        ("must_change_password", sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false())),
    ]
    for name, column in additions:
        if name not in user_columns:
            op.add_column("users", column)

    user_indexes = inspector.get_indexes("users") if inspector else []
    user_constraints = inspector.get_unique_constraints("users") if inspector else []
    has_email_uniqueness = any(
        tuple(index.get("column_names") or ()) == ("email_hash",) and index.get("unique")
        for index in user_indexes
    ) or any(tuple(constraint.get("column_names") or ()) == ("email_hash",) for constraint in user_constraints)
    if not has_email_uniqueness:
        op.create_index("ux_users_email_hash", "users", ["email_hash"], unique=True)

    if inspector is None or not inspector.has_table("password_reset_tokens"):
        op.create_table(
            "password_reset_tokens",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("purpose", sa.String(length=32), nullable=False, server_default="password_reset"),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("used_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("request_ip", sa.String(length=64), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("token_hash", name="uq_password_reset_tokens_token_hash"),
        )
    else:
        token_columns = {column["name"] for column in sa.inspect(bind).get_columns("password_reset_tokens")}
        if "attempts" not in token_columns:
            op.add_column(
                "password_reset_tokens",
                sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            )
    token_indexes = (
        {str(index.get("name")) for index in sa.inspect(bind).get_indexes("password_reset_tokens")}
        if inspector else set()
    )
    for name, columns in (
        ("ix_password_reset_tokens_user_id", ["user_id"]),
        ("ix_password_reset_tokens_purpose", ["purpose"]),
        ("ix_password_reset_tokens_expires_at", ["expires_at"]),
    ):
        if name not in token_indexes:
            op.create_index(name, "password_reset_tokens", columns)

    if not inspector or not inspector.has_table("admin_password_reset_audits"):
        op.create_table(
            "admin_password_reset_audits",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("admin_id", sa.Integer(), nullable=True),
            sa.Column("target_user_id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("request_ip", sa.String(length=64), nullable=True),
            sa.ForeignKeyConstraint(["admin_id"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["target_user_id"], ["users.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_admin_password_reset_audits_admin_id", "admin_password_reset_audits", ["admin_id"])
        op.create_index("ix_admin_password_reset_audits_target_user_id", "admin_password_reset_audits", ["target_user_id"])

    if not inspector or not inspector.has_table("password_reset_requests"):
        op.create_table(
            "password_reset_requests",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
            sa.Column("requested_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("handled_at", sa.DateTime(), nullable=True),
            sa.Column("handled_by", sa.Integer(), nullable=True),
            sa.Column("request_ip", sa.String(length=64), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["handled_by"], ["users.id"], ondelete="SET NULL"),
        )
        op.create_index("ix_password_reset_requests_user_id", "password_reset_requests", ["user_id"])
        op.create_index("ix_password_reset_requests_status", "password_reset_requests", ["status"])


def downgrade() -> None:
    op.drop_index("ix_password_reset_requests_status", table_name="password_reset_requests")
    op.drop_index("ix_password_reset_requests_user_id", table_name="password_reset_requests")
    op.drop_table("password_reset_requests")
    op.drop_index("ix_admin_password_reset_audits_target_user_id", table_name="admin_password_reset_audits")
    op.drop_index("ix_admin_password_reset_audits_admin_id", table_name="admin_password_reset_audits")
    op.drop_table("admin_password_reset_audits")
    op.drop_index("ix_password_reset_tokens_expires_at", table_name="password_reset_tokens")
    op.drop_index("ix_password_reset_tokens_purpose", table_name="password_reset_tokens")
    op.drop_index("ix_password_reset_tokens_user_id", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")
    op.drop_index("ux_users_email_hash", table_name="users")
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("users") as batch_op:
            for name in ("must_change_password", "auth_version", "password_changed_at", "email_verified_at", "email_hash", "email"):
                batch_op.drop_column(name)
    else:
        for name in ("must_change_password", "auth_version", "password_changed_at", "email_verified_at", "email_hash", "email"):
            op.drop_column("users", name)

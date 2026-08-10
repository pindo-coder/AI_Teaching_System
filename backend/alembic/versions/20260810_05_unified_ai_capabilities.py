"""store independently active configurations for every AI capability

Revision ID: 20260810_05
Revises: 20260810_04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260810_05"
down_revision = "20260810_04"
branch_labels = None
depends_on = None


TABLE_NAME = "ai_provider_configs"
CAPABILITY_INDEX = "ix_ai_provider_configs_capability"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(TABLE_NAME):
        raise RuntimeError("unified AI capability migration requires ai_provider_configs")

    columns = {column["name"] for column in inspector.get_columns(TABLE_NAME)}
    if "capability" not in columns:
        # The server default both backfills legacy rows as text and keeps raw SQL
        # inserts compatible with the pre-capability table contract.
        op.add_column(
            TABLE_NAME,
            sa.Column(
                "capability",
                sa.String(length=32),
                nullable=False,
                server_default=sa.text("'text'"),
            ),
        )
    if "provider_name" not in columns:
        op.add_column(
            TABLE_NAME,
            sa.Column(
                "provider_name",
                sa.String(length=80),
                nullable=False,
                server_default=sa.text("'openai_compatible'"),
            ),
        )
    if "enabled" not in columns:
        op.add_column(
            TABLE_NAME,
            sa.Column(
                "enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
        )
    if "dimensions" not in columns:
        op.add_column(TABLE_NAME, sa.Column("dimensions", sa.Integer(), nullable=True))

    indexes = {index["name"] for index in sa.inspect(bind).get_indexes(TABLE_NAME)}
    if CAPABILITY_INDEX not in indexes:
        op.create_index(CAPABILITY_INDEX, TABLE_NAME, ["capability"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(TABLE_NAME):
        raise RuntimeError("unified AI capability migration requires ai_provider_configs")

    columns = {column["name"] for column in inspector.get_columns(TABLE_NAME)}
    required_selection_columns = {"id", "capability", "enabled", "is_active"}
    if "capability" in columns and not required_selection_columns <= columns:
        missing = ", ".join(sorted(required_selection_columns - columns))
        raise RuntimeError(
            "cannot safely downgrade unified AI capabilities; missing columns: " + missing
        )
    if required_selection_columns <= columns:
        configs = sa.table(
            TABLE_NAME,
            sa.column("id", sa.Integer()),
            sa.column("capability", sa.String(length=32)),
            sa.column("enabled", sa.Boolean()),
            sa.column("is_active", sa.Boolean()),
        )
        latest_text_id = bind.scalar(
            sa.select(sa.func.max(configs.c.id)).where(
                configs.c.capability == "text",
                configs.c.enabled.is_(True),
            )
        )
        # The pre-capability resolver selects the newest active row without a
        # capability predicate.  Normalize active state before dropping the
        # discriminator so a vision/ASR/image row can never become the LLM.
        bind.execute(sa.update(configs).values(is_active=sa.false()))
        if latest_text_id is not None:
            bind.execute(
                sa.update(configs)
                .where(configs.c.id == latest_text_id)
                .values(is_active=sa.true())
            )

    indexes = {index["name"] for index in sa.inspect(bind).get_indexes(TABLE_NAME)}
    if CAPABILITY_INDEX in indexes:
        op.drop_index(CAPABILITY_INDEX, table_name=TABLE_NAME)

    columns = {column["name"] for column in sa.inspect(bind).get_columns(TABLE_NAME)}
    for column_name in ("dimensions", "enabled", "provider_name", "capability"):
        if column_name in columns:
            op.drop_column(TABLE_NAME, column_name)

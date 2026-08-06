"""candidate association fields and policy change evidence

Revision ID: 20260803_02
Revises: 20260803_01
"""

from alembic import op
import sqlalchemy as sa

from app.db.base import Base
import app.db.models  # noqa: F401


revision = "20260803_02"
down_revision = "20260803_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {item["name"] for item in inspector.get_columns("material_candidates")}
    additions = [
        ("suggested_course_ids", sa.JSON(), None),
        ("suggested_chapter_ids", sa.JSON(), None),
        ("suggested_knowledge_tags", sa.JSON(), None),
        ("association_confidence", sa.Float(), "0"),
        ("association_reason", sa.Text(), None),
    ]
    for name, column_type, default in additions:
        if name not in columns:
            kwargs = {"nullable": name != "association_confidence"}
            if default is not None:
                kwargs["server_default"] = sa.text(default)
            op.add_column("material_candidates", sa.Column(name, column_type, **kwargs))
    Base.metadata.tables["policy_changes"].create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("policy_changes"):
        op.drop_table("policy_changes")
    inspector = sa.inspect(bind)
    columns = {item["name"] for item in inspector.get_columns("material_candidates")}
    for name in ("association_reason", "association_confidence", "suggested_knowledge_tags", "suggested_chapter_ids", "suggested_course_ids"):
        if name in columns:
            op.drop_column("material_candidates", name)

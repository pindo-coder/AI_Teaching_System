"""add discovery quality, importance and filtering counters

Revision ID: 20260804_01
Revises: 20260803_03
"""

from alembic import op
import sqlalchemy as sa


revision = "20260804_01"
down_revision = "20260803_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    job_columns = {column["name"] for column in inspector.get_columns("discovery_jobs")}
    candidate_columns = {column["name"] for column in inspector.get_columns("material_candidates")}
    if "filtered_count" not in job_columns:
        op.add_column("discovery_jobs", sa.Column("filtered_count", sa.Integer(), nullable=False, server_default="0"))
    if "extraction_failed_count" not in job_columns:
        op.add_column("discovery_jobs", sa.Column("extraction_failed_count", sa.Integer(), nullable=False, server_default="0"))
    additions = [
        ("extraction_quality_score", sa.Float(), "0"),
        ("importance_score", sa.Float(), "0"),
        ("importance_level", sa.String(length=20), "observe"),
        ("importance_reason", sa.Text(), None),
    ]
    for name, column_type, default in additions:
        if name not in candidate_columns:
            kwargs = {"nullable": False} if name != "importance_reason" else {"nullable": True}
            if default is not None:
                kwargs["server_default"] = default
            op.add_column("material_candidates", sa.Column(name, column_type, **kwargs))
    op.create_index("ix_material_candidates_importance_score", "material_candidates", ["importance_score"], unique=False, if_not_exists=True)
    op.create_index("ix_material_candidates_importance_level", "material_candidates", ["importance_level"], unique=False, if_not_exists=True)
    # 首次启用自动巡检时，系统初始化的三个默认来源按每日一次执行；
    # 管理员已经改过周期的来源不覆盖其配置。
    op.execute(sa.text(
        "UPDATE source_registries SET fetch_interval_minutes = 1440 "
        "WHERE domain IN ('gov.cn', 'moe.gov.cn', 'qstheory.cn') AND fetch_interval_minutes = 360"
    ))


def downgrade() -> None:
    op.drop_index("ix_material_candidates_importance_level", table_name="material_candidates")
    op.drop_index("ix_material_candidates_importance_score", table_name="material_candidates")
    for name in ("importance_reason", "importance_level", "importance_score", "extraction_quality_score"):
        op.drop_column("material_candidates", name)
    op.drop_column("discovery_jobs", "extraction_failed_count")
    op.drop_column("discovery_jobs", "filtered_count")

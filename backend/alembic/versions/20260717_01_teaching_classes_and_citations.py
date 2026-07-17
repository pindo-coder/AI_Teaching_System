"""教学班、教师审核与精确引用数据底座。

Revision ID: 20260717_01
Revises: None
"""
from alembic import op
import sqlalchemy as sa

from app.db.base import Base
import app.db.models  # noqa: F401


revision = "20260717_01"
down_revision = None
branch_labels = None
depends_on = None


NEW_TABLES = [
    "course_subjects", "academic_terms", "teaching_classes", "teaching_class_teachers",
    "teaching_class_materials", "class_roster_entries", "class_memberships",
    "student_course_seats", "class_groups", "class_group_members", "class_join_requests",
    "class_transfer_logs", "textbook_versions", "document_pages", "page_number_ranges",
    "document_outline_nodes", "knowledge_chunks", "index_versions", "citation_feedback",
]


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _add(table: str, column: sa.Column) -> None:
    if column.name not in _columns(table):
        op.add_column(table, column)


def _index(name: str, table: str, columns: list[str]) -> None:
    existing = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, columns)


def _foreign_key(name: str, source: str, referent: str, local: list[str], remote: list[str], ondelete: str) -> None:
    if op.get_bind().dialect.name == "sqlite":
        return
    existing = sa.inspect(op.get_bind()).get_foreign_keys(source)
    if any(item.get("referred_table") == referent and item.get("constrained_columns") == local for item in existing):
        return
    op.create_foreign_key(name, source, referent, local, remote, ondelete=ondelete)


def upgrade() -> None:
    bind = op.get_bind()
    # 新数据库可直接由本迁移建立完整结构；已有数据库只创建缺失表，随后补列。
    Base.metadata.create_all(bind, checkfirst=True)
    for table_name in NEW_TABLES:
        Base.metadata.tables[table_name].create(bind, checkfirst=True)

    _add("users", sa.Column("approval_status", sa.String(20), nullable=False, server_default="approved"))
    _add("users", sa.Column("approval_note", sa.String(500), nullable=True))
    _add("users", sa.Column("approved_time", sa.DateTime(), nullable=True))
    _add("users", sa.Column("approved_by", sa.Integer(), nullable=True))
    _add("teacher_assignments", sa.Column("teaching_class_id", sa.Integer(), nullable=True))
    _add("teacher_assignments", sa.Column("target_group_ids", sa.JSON(), nullable=True))
    _add("classroom_activities", sa.Column("teaching_class_id", sa.Integer(), nullable=True))
    _add("knowledge_documents", sa.Column("textbook_version_id", sa.Integer(), nullable=True))
    _add("knowledge_documents", sa.Column("source_role", sa.String(20), nullable=False, server_default="primary"))
    _add("knowledge_documents", sa.Column("access_policy", sa.String(30), nullable=False, server_default="full_preview"))
    _add("knowledge_documents", sa.Column("calibration_status", sa.String(20), nullable=False, server_default="pending"))
    _add("knowledge_chunks", sa.Column("paragraph_index", sa.Integer(), nullable=True))

    bind.execute(sa.text("UPDATE teacher_assignments SET target_group_ids='[]' WHERE target_group_ids IS NULL"))
    if bind.dialect.name != "sqlite":
        op.alter_column("teacher_assignments", "target_group_ids", existing_type=sa.JSON(), nullable=False)
    _index("ix_users_approval_status", "users", ["approval_status"])
    _index("ix_teacher_assignments_teaching_class_id", "teacher_assignments", ["teaching_class_id"])
    _index("ix_classroom_activities_teaching_class_id", "classroom_activities", ["teaching_class_id"])
    _index("ix_knowledge_documents_textbook_version_id", "knowledge_documents", ["textbook_version_id"])
    _index("ix_knowledge_documents_calibration_status", "knowledge_documents", ["calibration_status"])
    _foreign_key("fk_users_approved_by", "users", "users", ["approved_by"], ["id"], "SET NULL")
    _foreign_key("fk_assignments_teaching_class", "teacher_assignments", "teaching_classes", ["teaching_class_id"], ["id"], "SET NULL")
    _foreign_key("fk_activities_teaching_class", "classroom_activities", "teaching_classes", ["teaching_class_id"], ["id"], "SET NULL")
    _foreign_key("fk_documents_textbook_version", "knowledge_documents", "textbook_versions", ["textbook_version_id"], ["id"], "SET NULL")

    # 既有教师视为已审核，避免升级后中断现有测试账号；新注册教师由应用写入 pending。
    bind.execute(sa.text("UPDATE users SET approval_status='approved' WHERE approval_status IS NULL OR role IN ('student','admin')"))


def downgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        for table, column in [
            ("knowledge_documents", "textbook_version_id"),
            ("classroom_activities", "teaching_class_id"),
            ("teacher_assignments", "teaching_class_id"),
            ("users", "approved_by"),
        ]:
            for constraint in sa.inspect(op.get_bind()).get_foreign_keys(table):
                if constraint.get("constrained_columns") == [column] and constraint.get("name"):
                    op.drop_constraint(constraint["name"], table, type_="foreignkey")
    for table, column in [
        ("knowledge_documents", "calibration_status"), ("knowledge_documents", "access_policy"),
        ("knowledge_documents", "source_role"), ("knowledge_documents", "textbook_version_id"),
        ("classroom_activities", "teaching_class_id"), ("teacher_assignments", "target_group_ids"),
        ("teacher_assignments", "teaching_class_id"), ("users", "approved_by"),
        ("users", "approved_time"), ("users", "approval_note"), ("users", "approval_status"),
    ]:
        if column in _columns(table):
            op.drop_column(table, column)
    for table_name in reversed(NEW_TABLES):
        if sa.inspect(op.get_bind()).has_table(table_name):
            op.drop_table(table_name)

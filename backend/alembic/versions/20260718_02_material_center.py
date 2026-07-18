"""three-tier material center and retrieval scopes

Revision ID: 20260718_02
Revises: 20260718_01
"""

from alembic import op
import sqlalchemy as sa

from app.db.base import Base
import app.db.models  # noqa: F401


revision = "20260718_02"
down_revision = "20260718_01"
branch_labels = None
depends_on = None


NEW_TABLES = [
    "document_course_scopes",
    "document_chapter_scopes",
    "document_class_scopes",
    "document_knowledge_tags",
]


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _add(column: sa.Column) -> None:
    if column.name not in _columns("knowledge_documents"):
        op.add_column("knowledge_documents", column)


def _index(name: str, columns: list[str]) -> None:
    existing = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("knowledge_documents")}
    if name not in existing:
        op.create_index(name, "knowledge_documents", columns)


def _foreign_key(name: str, referent: str, local: list[str], remote: list[str], ondelete: str) -> None:
    if op.get_bind().dialect.name == "sqlite":
        return
    existing = sa.inspect(op.get_bind()).get_foreign_keys("knowledge_documents")
    if any(item.get("referred_table") == referent and item.get("constrained_columns") == local for item in existing):
        return
    op.create_foreign_key(name, "knowledge_documents", referent, local, remote, ondelete=ondelete)


def upgrade() -> None:
    bind = op.get_bind()
    _add(sa.Column("material_type", sa.String(20), nullable=False, server_default="unclassified"))
    _add(sa.Column("publisher", sa.String(255), nullable=True))
    _add(sa.Column("published_date", sa.Date(), nullable=True))
    _add(sa.Column("source_url", sa.String(1000), nullable=True))
    _add(sa.Column("applicable_scope", sa.String(500), nullable=True))
    _add(sa.Column("owner_user_id", sa.Integer(), nullable=True))
    _add(sa.Column("review_status", sa.String(20), nullable=False, server_default="pending"))
    _add(sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    _add(sa.Column("verified_by", sa.Integer(), nullable=True))
    _add(sa.Column("verified_time", sa.DateTime(), nullable=True))
    _add(sa.Column("content_hash", sa.String(64), nullable=True))
    _add(sa.Column("snapshot_time", sa.DateTime(), nullable=True))
    _add(sa.Column("version_label", sa.String(100), nullable=True))
    _add(sa.Column("supersedes_document_id", sa.Integer(), nullable=True))

    bind.execute(sa.text(
        "UPDATE knowledge_documents SET material_type='textbook', review_status='published' "
        "WHERE textbook_version_id IS NOT NULL"
    ))
    bind.execute(sa.text(
        "UPDATE knowledge_documents SET material_type='unclassified', review_status='pending' "
        "WHERE textbook_version_id IS NULL"
    ))
    course_column = next(
        (item for item in sa.inspect(bind).get_columns("knowledge_documents") if item["name"] == "course_id"),
        None,
    )
    if bind.dialect.name == "sqlite" and course_column and not course_column.get("nullable", True):
        # 旧版 SQLite 也可能存在 NOT NULL course_id。中央材料允许先入库再确认
        # 关联范围，因此用 batch 模式安全重建表结构。
        with op.batch_alter_table("knowledge_documents") as batch_op:
            batch_op.alter_column("course_id", existing_type=sa.Integer(), nullable=True)
    elif bind.dialect.name == "mysql":
        for constraint in sa.inspect(bind).get_foreign_keys("knowledge_documents"):
            if constraint.get("constrained_columns") == ["course_id"] and constraint.get("name"):
                op.drop_constraint(constraint["name"], "knowledge_documents", type_="foreignkey")
        op.alter_column(
            "knowledge_documents",
            "course_id",
            existing_type=sa.Integer(),
            nullable=True,
        )
        op.create_foreign_key(
            "fk_documents_course_nullable", "knowledge_documents", "courses",
            ["course_id"], ["id"], ondelete="SET NULL",
        )

    for name, columns in [
        ("ix_knowledge_documents_material_type", ["material_type"]),
        ("ix_knowledge_documents_owner_user_id", ["owner_user_id"]),
        ("ix_knowledge_documents_review_status", ["review_status"]),
        ("ix_knowledge_documents_is_active", ["is_active"]),
        ("ix_knowledge_documents_verified_by", ["verified_by"]),
        ("ix_knowledge_documents_content_hash", ["content_hash"]),
        ("ix_knowledge_documents_supersedes_document_id", ["supersedes_document_id"]),
    ]:
        _index(name, columns)

    _foreign_key("fk_documents_owner_user", "users", ["owner_user_id"], ["id"], "SET NULL")
    _foreign_key("fk_documents_verified_by", "users", ["verified_by"], ["id"], "SET NULL")
    _foreign_key(
        "fk_documents_supersedes",
        "knowledge_documents",
        ["supersedes_document_id"],
        ["id"],
        "SET NULL",
    )

    for table_name in NEW_TABLES:
        Base.metadata.tables[table_name].create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in reversed(NEW_TABLES):
        if sa.inspect(bind).has_table(table_name):
            op.drop_table(table_name)
    if bind.dialect.name != "sqlite":
        for constraint in sa.inspect(bind).get_foreign_keys("knowledge_documents"):
            if constraint.get("constrained_columns") in [
                ["owner_user_id"], ["verified_by"], ["supersedes_document_id"]
            ] and constraint.get("name"):
                op.drop_constraint(constraint["name"], "knowledge_documents", type_="foreignkey")
    for column in [
        "supersedes_document_id", "version_label", "snapshot_time", "content_hash",
        "verified_time", "verified_by", "is_active", "review_status", "owner_user_id",
        "applicable_scope", "source_url", "published_date", "publisher", "material_type",
    ]:
        if column in _columns("knowledge_documents"):
            op.drop_column("knowledge_documents", column)

from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "20260819_01_document_page_raw_text.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("document_page_raw_text_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_raw_text_migration_backfills_existing_page_text_on_sqlite() -> None:
    migration = _load_migration()
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    pages = sa.Table(
        "document_pages", metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("text", sa.Text(), nullable=False),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(pages.insert().values(id=1, text="OCR 原始正文"))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

        columns = {item["name"]: item for item in sa.inspect(connection).get_columns("document_pages")}
        raw_text = connection.scalar(sa.text("SELECT raw_text FROM document_pages WHERE id = 1"))

    assert columns["raw_text"]["nullable"] is False
    assert raw_text == "OCR 原始正文"


def test_raw_text_migration_revision_follows_current_head() -> None:
    migration = _load_migration()

    assert migration.revision == "20260819_01"
    assert migration.down_revision == "20260816_02"

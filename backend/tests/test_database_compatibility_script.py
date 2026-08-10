from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

from app.db.base import Base
from app.db.init_db import _alembic_config
from scripts.check_database_compatibility import compatibility_issues


def _stamp_current_head(test_engine) -> None:
    script = ScriptDirectory.from_config(_alembic_config())
    head = script.get_current_head()
    assert head is not None
    with test_engine.begin() as connection:
        MigrationContext.configure(connection).stamp(script, head)


def test_compatibility_check_accepts_migrated_sqlite_database() -> None:
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(test_engine)
    _stamp_current_head(test_engine)

    assert compatibility_issues(test_engine) == []


def test_compatibility_check_reports_missing_revision_and_unique_index() -> None:
    test_engine = create_engine("sqlite:///:memory:")
    with test_engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, identity_no VARCHAR(32))"
        )

    issues = compatibility_issues(test_engine)

    assert any("Alembic 版本不一致" in issue for issue in issues)
    assert "users.identity_no 缺少唯一索引" in issues


def test_compatibility_check_rejects_empty_database_stamped_at_head() -> None:
    test_engine = create_engine("sqlite:///:memory:")
    _stamp_current_head(test_engine)

    issues = compatibility_issues(test_engine)

    assert "缺少数据表：users" in issues
    assert "缺少数据表：learning_progress" in issues
    assert "缺少数据表：material_candidates" in issues
    assert "缺少数据表：news_items" in issues
    assert "缺少数据表：teacher_assignments" in issues


def test_compatibility_check_requires_learning_progress_unique_key() -> None:
    test_engine = create_engine("sqlite:///:memory:")
    with test_engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE learning_progress ("
            "id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, "
            "chapter_id INTEGER NOT NULL, learning_stage VARCHAR(20) NOT NULL)"
        )
    _stamp_current_head(test_engine)

    issues = compatibility_issues(test_engine)

    assert (
        "learning_progress 缺少唯一约束："
        "(user_id, chapter_id, learning_stage)"
    ) in issues


def test_compatibility_check_detects_structural_url_and_missing_hash_indexes() -> None:
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(test_engine)
    _stamp_current_head(test_engine)
    with test_engine.begin() as connection:
        connection.exec_driver_sql(
            "DROP INDEX ix_material_candidates_canonical_url_hash"
        )
        connection.exec_driver_sql(
            "CREATE INDEX custom_canonical_url_lookup "
            "ON material_candidates (canonical_url)"
        )

    issues = compatibility_issues(test_engine)

    assert "material_candidates.canonical_url_hash 缺少单列索引" in issues
    assert "仍存在 canonical_url 单列旧索引：custom_canonical_url_lookup" in issues


def test_compatibility_check_detects_reserved_legacy_name_conflict_case_insensitively() -> None:
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(test_engine)
    _stamp_current_head(test_engine)
    with test_engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE INDEX IX_MATERIAL_CANDIDATES_CANONICAL_URL "
            "ON material_candidates (status)"
        )

    issues = compatibility_issues(test_engine)

    assert (
        "保留旧索引名 ix_material_candidates_canonical_url 被用于异常索引定义"
    ) in issues

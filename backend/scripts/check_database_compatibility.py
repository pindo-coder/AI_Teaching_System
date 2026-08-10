"""只读检查当前数据库是否满足应用运行所需的兼容性条件。"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.db.init_db import database_revision_state
from app.db.session import engine


REQUIRED_TABLES = (
    "users",
    "learning_progress",
    "material_candidates",
    "material_snapshots",
    "agent_runs",
    "news_items",
    "teacher_assignments",
)
KNOWN_LEGACY_CANONICAL_URL_INDEX_NAME = "ix_material_candidates_canonical_url"


def _normalized_columns(item: dict) -> tuple[object, ...]:
    return tuple(
        column.casefold() if isinstance(column, str) else column
        for column in (item.get("column_names") or ())
    )


def _table_columns(inspector, table_name: str) -> set[str]:
    return {
        str(column["name"]).casefold()
        for column in inspector.get_columns(table_name)
    }


def _has_unique_columns(inspector, table_name: str, columns: tuple[str, ...]) -> bool:
    return any(
        bool(item.get("unique")) and _normalized_columns(item) == columns
        for item in inspector.get_indexes(table_name)
    ) or any(
        _normalized_columns(item) == columns
        for item in inspector.get_unique_constraints(table_name)
    )


def _has_unique_identity_index(db_engine: Engine) -> bool:
    inspector = inspect(db_engine)
    if not inspector.has_table("users"):
        return False
    return _has_unique_columns(inspector, "users", ("identity_no",))


def compatibility_issues(db_engine: Engine) -> list[str]:
    """返回可操作的兼容性问题；函数本身不修改数据库。"""

    issues: list[str] = []
    try:
        with db_engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - 命令行诊断需要保留驱动错误摘要
        return [f"数据库连接失败：{exc}"]

    current_heads, expected_heads = database_revision_state(db_engine)
    if current_heads != expected_heads:
        issues.append(
            "Alembic 版本不一致："
            f"当前={sorted(current_heads) or ['未初始化']}，"
            f"期望={sorted(expected_heads) or ['无迁移']}"
        )

    inspector = inspect(db_engine)
    existing_tables = {
        table_name
        for table_name in REQUIRED_TABLES
        if inspector.has_table(table_name)
    }
    for table_name in REQUIRED_TABLES:
        if table_name not in existing_tables:
            issues.append(f"缺少数据表：{table_name}")

    if "users" in existing_tables:
        user_columns = _table_columns(inspector, "users")
        if "identity_no" not in user_columns:
            issues.append("users 缺少字段：identity_no")
        elif not _has_unique_identity_index(db_engine):
            issues.append("users.identity_no 缺少唯一索引")

    if "learning_progress" in existing_tables:
        progress_key = ("user_id", "chapter_id", "learning_stage")
        progress_columns = _table_columns(inspector, "learning_progress")
        missing_progress_columns = set(progress_key) - progress_columns
        if missing_progress_columns:
            issues.append(
                "learning_progress 缺少字段："
                + ", ".join(sorted(missing_progress_columns))
            )
        elif not _has_unique_columns(inspector, "learning_progress", progress_key):
            issues.append(
                "learning_progress 缺少唯一约束："
                "(user_id, chapter_id, learning_stage)"
            )

    for table_name, marker_column in (
        ("news_items", "published_time_is_utc"),
        ("teacher_assignments", "due_time_is_utc"),
    ):
        if table_name not in existing_tables:
            continue
        if marker_column not in _table_columns(inspector, table_name):
            issues.append(f"{table_name} 缺少字段：{marker_column}")

    if "material_candidates" in existing_tables:
        candidate_columns = _table_columns(inspector, "material_candidates")
        for column_name in ("canonical_url", "canonical_url_hash"):
            if column_name not in candidate_columns:
                issues.append(f"material_candidates 缺少字段：{column_name}")

        candidate_indexes = inspector.get_indexes("material_candidates")
        if "canonical_url_hash" in candidate_columns and not any(
            _normalized_columns(index) == ("canonical_url_hash",)
            for index in candidate_indexes
        ):
            issues.append("material_candidates.canonical_url_hash 缺少单列索引")

        legacy_indexes = [
            str(index.get("name") or "<unnamed>")
            for index in candidate_indexes
            if _normalized_columns(index) == ("canonical_url",)
        ]
        if legacy_indexes:
            issues.append(
                "仍存在 canonical_url 单列旧索引："
                + ", ".join(sorted(legacy_indexes, key=str.casefold))
            )

        reserved_name_conflicts = [
            str(index.get("name") or "<unnamed>")
            for index in candidate_indexes
            if str(index.get("name") or "").casefold()
            == KNOWN_LEGACY_CANONICAL_URL_INDEX_NAME.casefold()
            and _normalized_columns(index) != ("canonical_url",)
        ]
        if reserved_name_conflicts:
            issues.append(
                f"保留旧索引名 {KNOWN_LEGACY_CANONICAL_URL_INDEX_NAME} "
                "被用于异常索引定义"
            )

    if db_engine.dialect.name == "mysql":
        for table_name, column_name in (
            ("material_snapshots", "content"),
            ("agent_runs", "context_snapshot"),
        ):
            if table_name not in existing_tables:
                continue
            column = next(
                (item for item in inspector.get_columns(table_name) if item["name"] == column_name),
                None,
            )
            if column is None or "LONGTEXT" not in str(column["type"]).upper():
                issues.append(f"{table_name}.{column_name} 尚未升级为 LONGTEXT")

        with db_engine.connect() as connection:
            charset = connection.scalar(text("SELECT @@character_set_database"))
            if str(charset).lower() != "utf8mb4":
                issues.append(f"数据库字符集不是 utf8mb4：{charset}")

    return issues


def main() -> int:
    issues = compatibility_issues(engine)
    print(f"dialect={engine.dialect.name}")
    if issues:
        print("status=failed")
        for index, issue in enumerate(issues, start=1):
            print(f"{index}. {issue}")
        return 1
    print("status=ok")
    print("数据库连接、迁移版本、关键索引与字段类型均符合要求。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

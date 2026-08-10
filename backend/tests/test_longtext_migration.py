from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy.dialects import mysql


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "20260810_01_expand_snapshot_text.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("expand_snapshot_text_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_longtext_migration_upgrades_both_mysql_columns(monkeypatch) -> None:
    migration = _load_migration()
    calls: list[tuple[str, str, dict]] = []
    monkeypatch.setattr(
        migration.op,
        "get_bind",
        lambda: SimpleNamespace(dialect=SimpleNamespace(name="mysql")),
    )
    monkeypatch.setattr(
        migration.op,
        "alter_column",
        lambda table, column, **kwargs: calls.append((table, column, kwargs)),
    )

    migration.upgrade()

    assert [(table, column) for table, column, _ in calls] == [
        ("material_snapshots", "content"),
        ("agent_runs", "context_snapshot"),
    ]
    assert all(isinstance(kwargs["type_"], mysql.LONGTEXT) for _, _, kwargs in calls)
    assert calls[0][2]["existing_nullable"] is False
    assert calls[1][2]["existing_nullable"] is True


def test_longtext_migration_is_noop_on_sqlite(monkeypatch) -> None:
    migration = _load_migration()
    calls: list[object] = []
    monkeypatch.setattr(
        migration.op,
        "get_bind",
        lambda: SimpleNamespace(dialect=SimpleNamespace(name="sqlite")),
    )
    monkeypatch.setattr(migration.op, "alter_column", lambda *args, **kwargs: calls.append(args))

    migration.upgrade()

    assert calls == []

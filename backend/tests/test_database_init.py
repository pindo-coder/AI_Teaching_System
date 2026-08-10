import pytest
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

from app.core.config import settings
from app.db import init_db as init_db_module
from app.db.init_db import _alembic_config, database_revision_state, validate_database_revision


def test_database_revision_check_rejects_unversioned_database() -> None:
    test_engine = create_engine("sqlite:///:memory:")

    with pytest.raises(RuntimeError, match="alembic upgrade head"):
        validate_database_revision(test_engine)


def test_database_revision_check_accepts_current_head() -> None:
    test_engine = create_engine("sqlite:///:memory:")
    script = ScriptDirectory.from_config(_alembic_config())
    expected_head = script.get_current_head()
    assert expected_head is not None

    with test_engine.begin() as connection:
        MigrationContext.configure(connection).stamp(script, expected_head)

    current_heads, expected_heads = database_revision_state(test_engine)

    assert current_heads == expected_heads == {expected_head}
    validate_database_revision(test_engine)


def test_production_sqlite_requires_alembic_revision(monkeypatch) -> None:
    test_engine = create_engine("sqlite:///:memory:")
    monkeypatch.setattr(init_db_module, "engine", test_engine)
    monkeypatch.setattr(init_db_module, "create_bootstrap_admin", lambda: None)
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "database_url", "sqlite:///:memory:")

    with pytest.raises(RuntimeError, match="alembic upgrade head"):
        init_db_module.init_db()

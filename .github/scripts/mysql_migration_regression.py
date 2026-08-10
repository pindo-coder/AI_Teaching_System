"""Exercise the legacy-to-head Alembic path against an isolated MySQL database."""

from __future__ import annotations

import os
from pathlib import Path
import sys

from alembic import command
from alembic.config import Config
import sqlalchemy as sa
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError


ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "backend"
IDENTITY_NO = "110101200001019999"


def _alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("prepend_sys_path", str(BACKEND_DIR))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def _quote_identifier(identifier: str) -> str:
    return f"`{identifier.replace('`', '``')}`"


def _indexes_for_column(inspector: sa.Inspector, table: str, column: str) -> list[dict]:
    return [
        index
        for index in inspector.get_indexes(table)
        if index.get("column_names") == [column]
    ]


def _exercise_learning_repository_upsert(engine: sa.Engine) -> None:
    """Run the real repository twice and verify the database-level outcome."""

    backend_path = str(BACKEND_DIR)
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

    # Import after Alembic has loaded the complete model registry. This keeps the
    # regression focused on the text learning repository without adding any media
    # module dependency to this script.
    from sqlalchemy.orm import Session

    from app.repositories.learning_repository import LearningRepository

    with engine.begin() as connection:
        user_result = connection.execute(
            sa.text(
                "INSERT INTO users "
                "(username, password_hash, role, approval_status) "
                "VALUES ('ci-learning-upsert', 'not-a-real-password', "
                "'student', 'approved')"
            )
        )
        course_result = connection.execute(
            sa.text("INSERT INTO courses (name) VALUES ('CI learning upsert course')")
        )
        user_id = int(user_result.lastrowid)
        course_id = int(course_result.lastrowid)
        chapter_result = connection.execute(
            sa.text(
                "INSERT INTO chapters (course_id, title, sort_order) "
                "VALUES (:course_id, 'CI learning upsert chapter', 1)"
            ),
            {"course_id": course_id},
        )
        chapter_id = int(chapter_result.lastrowid)

    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        repository = LearningRepository(session)
        first = repository.upsert(
            user_id=user_id,
            course_id=course_id,
            chapter_id=chapter_id,
            learning_stage="preview",
            progress=20,
        )
        updated = repository.upsert(
            user_id=user_id,
            course_id=course_id,
            chapter_id=chapter_id,
            learning_stage="preview",
            progress=75,
        )
        if first.id != updated.id or updated.progress != 75:
            raise AssertionError(
                "LearningRepository.upsert did not refresh the existing MySQL row"
            )

    with engine.connect() as connection:
        stored = connection.execute(
            sa.text(
                "SELECT COUNT(*) AS row_count, MAX(progress) AS progress "
                "FROM learning_progress "
                "WHERE user_id = :user_id AND chapter_id = :chapter_id "
                "AND learning_stage = 'preview'"
            ),
            {"user_id": user_id, "chapter_id": chapter_id},
        ).mappings().one()
    if int(stored["row_count"]) != 1 or int(stored["progress"]) != 75:
        raise AssertionError(
            "LearningRepository.upsert did not leave exactly one row at progress 75"
        )
    print(
        f"{engine.dialect.name} LearningRepository.upsert: one row updated to progress 75"
    )


def main() -> int:
    database_url = os.environ.get("DATABASE_URL", "")
    url = make_url(database_url)
    if url.get_backend_name() != "mysql":
        raise RuntimeError("DATABASE_URL must point to MySQL for this regression check")
    if not url.database or not url.database.endswith("_test"):
        raise RuntimeError("Refusing to mutate a database whose name does not end in '_test'")

    engine = sa.create_engine(database_url, pool_pre_ping=True)
    database_name = _quote_identifier(url.database)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            f"ALTER DATABASE {database_name} "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )

    config = _alembic_config(database_url)
    command.upgrade(config, "20260810_02")

    # Reproduce the two legacy states repaired by 20260810_03. A prefix is used
    # for the URL index because MySQL correctly rejects a full utf8mb4 VARCHAR(1000)
    # key before the repair migration has a chance to remove it.
    with engine.begin() as connection:
        inspector = sa.inspect(connection)
        for index in _indexes_for_column(inspector, "users", "identity_no"):
            if index.get("unique"):
                connection.exec_driver_sql(
                    f"DROP INDEX {_quote_identifier(index['name'])} ON `users`"
                )
        connection.exec_driver_sql(
            "CREATE INDEX `ix_users_identity_no` ON `users` (`identity_no`)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX `ix_material_candidates_canonical_url` "
            "ON `material_candidates` (`canonical_url`(191))"
        )
        connection.execute(
            sa.text(
                "INSERT INTO users "
                "(username, identity_no, password_hash, role, approval_status) "
                "VALUES (:username, :identity_no, :password_hash, 'student', 'approved')"
            ),
            [
                {
                    "username": "ci-duplicate-1",
                    "identity_no": IDENTITY_NO,
                    "password_hash": "not-a-real-password",
                },
                {
                    "username": "ci-duplicate-2",
                    "identity_no": IDENTITY_NO,
                    "password_hash": "not-a-real-password",
                },
            ],
        )

    try:
        command.upgrade(config, "head")
    except RuntimeError as exc:
        message = str(exc)
        if "duplicate non-NULL values" not in message or "Resolve the duplicate users" not in message:
            raise AssertionError(f"migration failed without an actionable duplicate error: {exc}") from exc
    else:
        raise AssertionError("migration unexpectedly accepted duplicate users.identity_no values")

    # The duplicate preflight must run before either index DDL operation.
    inspector = sa.inspect(engine)
    identity_indexes = _indexes_for_column(inspector, "users", "identity_no")
    canonical_indexes = _indexes_for_column(
        inspector, "material_candidates", "canonical_url"
    )
    if not any(not index.get("unique") for index in identity_indexes):
        raise AssertionError("failed migration unexpectedly changed the identity index")
    if not canonical_indexes:
        raise AssertionError("failed migration unexpectedly removed the canonical URL index")

    with engine.begin() as connection:
        connection.execute(
            sa.text("DELETE FROM users WHERE username = 'ci-duplicate-2'")
        )
    command.upgrade(config, "head")

    inspector = sa.inspect(engine)
    identity_indexes = _indexes_for_column(inspector, "users", "identity_no")
    canonical_indexes = _indexes_for_column(
        inspector, "material_candidates", "canonical_url"
    )
    if not any(index.get("unique") for index in identity_indexes):
        raise AssertionError("users.identity_no is not protected by a unique index")
    if any(not index.get("unique") for index in canonical_indexes):
        raise AssertionError("legacy material_candidates.canonical_url index still exists")

    try:
        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    "INSERT INTO users "
                    "(username, identity_no, password_hash, role, approval_status) "
                    "VALUES ('ci-duplicate-3', :identity_no, 'not-a-real-password', "
                    "'student', 'approved')"
                ),
                {"identity_no": IDENTITY_NO},
            )
    except IntegrityError:
        pass
    else:
        raise AssertionError("MySQL accepted a duplicate users.identity_no after migration")

    _exercise_learning_repository_upsert(engine)

    print(f"MySQL {engine.dialect.server_version_info}: legacy-to-head migration passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

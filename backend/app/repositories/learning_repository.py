from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from sqlalchemy.sql.dml import Insert

from app.core.time import utc_now
from app.models.learning_progress import LearningProgress


_PROGRESS_KEY_COLUMNS = (
    LearningProgress.user_id,
    LearningProgress.chapter_id,
    LearningProgress.learning_stage,
)


def _build_upsert_statement(dialect_name: str, values: Mapping[str, Any]) -> Insert:
    """Build one atomic insert-or-update statement for a supported database."""

    if dialect_name == "sqlite":
        statement = sqlite_insert(LearningProgress).values(**values)
        return statement.on_conflict_do_update(
            index_elements=_PROGRESS_KEY_COLUMNS,
            set_={
                "progress": statement.excluded.progress,
                "last_study_time": statement.excluded.last_study_time,
            },
        )
    if dialect_name == "mysql":
        statement = mysql_insert(LearningProgress).values(**values)
        return statement.on_duplicate_key_update(
            progress=statement.inserted.progress,
            last_study_time=statement.inserted.last_study_time,
        )
    raise RuntimeError(f"Unsupported learning-progress database dialect: {dialect_name}")


class LearningRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_for_user(self, user_id: int) -> list[LearningProgress]:
        query = (
            select(LearningProgress)
            .where(LearningProgress.user_id == user_id)
            .order_by(LearningProgress.last_study_time.desc())
        )
        return list(self.db.scalars(query).all())

    def upsert(
        self, *, user_id: int, course_id: int, chapter_id: int, learning_stage: str, progress: int
    ) -> LearningProgress:
        """Atomically store progress and return the value written by this call.

        Reading before commit keeps the write lock until our value has been
        loaded, so a concurrent caller cannot replace it between the upsert and
        this method's result. A later committed call may still become the final
        database value, as expected for last-writer-wins progress updates.
        """

        query = select(LearningProgress).where(
            LearningProgress.user_id == user_id,
            LearningProgress.chapter_id == chapter_id,
            LearningProgress.learning_stage == learning_stage,
        )
        statement = _build_upsert_statement(
            self.db.get_bind().dialect.name,
            {
                "user_id": user_id,
                "course_id": course_id,
                "chapter_id": chapter_id,
                "learning_stage": learning_stage,
                "progress": progress,
                # Do not depend on the MySQL server/session timezone. SQLite
                # and MySQL receive the same explicit UTC-naive timestamp.
                "last_study_time": utc_now(),
            },
        )

        # SessionLocal disables autoflush. Flush tracked changes first so a
        # dirty or pending LearningProgress cannot be flushed during commit and
        # overwrite (or conflict with) the native statement below.
        self.db.flush()
        self.db.execute(statement)

        # The native statement bypasses ORM state synchronization. Refresh an
        # already-loaded identity inside the same transaction, before releasing
        # the row/write lock at commit.
        record = self.db.scalar(query.execution_options(populate_existing=True))
        if record is None:  # pragma: no cover - a successful upsert guarantees this row
            self.db.rollback()
            raise RuntimeError("Learning progress upsert completed without a stored row")
        self.db.commit()
        return record

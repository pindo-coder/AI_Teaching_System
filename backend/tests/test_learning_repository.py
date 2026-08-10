from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock, get_ident

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.dialects import mysql, sqlite
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models.chapter import Chapter
from app.models.course import Course
from app.models.learning_progress import LearningProgress
from app.models.user import User
from app.repositories.learning_repository import LearningRepository, _build_upsert_statement


@pytest.mark.parametrize(
    ("dialect_name", "dialect", "conflict_clause", "progress_update"),
    [
        (
            "sqlite",
            sqlite.dialect(),
            "ON CONFLICT (user_id, chapter_id, learning_stage) DO UPDATE",
            "progress = excluded.progress",
        ),
        ("mysql", mysql.dialect(), "ON DUPLICATE KEY UPDATE", "progress = VALUES(progress)"),
    ],
)
def test_learning_progress_upsert_uses_native_database_conflict_handling(
    dialect_name: str, dialect: object, conflict_clause: str, progress_update: str
) -> None:
    statement = _build_upsert_statement(
        dialect_name,
        {
            "user_id": 1,
            "course_id": 2,
            "chapter_id": 3,
            "learning_stage": "preview",
            "progress": 60,
        },
    )

    sql = str(statement.compile(dialect=dialect, compile_kwargs={"literal_binds": True}))

    assert conflict_clause in sql
    assert progress_update in sql
    assert "last_study_time" in sql


def test_learning_progress_upsert_updates_and_refreshes_existing_row(db: Session) -> None:
    user = User(username="upsert_student", password_hash="test", role="student")
    course = Course(name="进度更新测试课程")
    db.add_all([user, course])
    db.flush()
    chapter = Chapter(course_id=course.id, title="进度更新测试章节", sort_order=1)
    db.add(chapter)
    db.commit()

    repository = LearningRepository(db)
    first = repository.upsert(
        user_id=user.id,
        course_id=course.id,
        chapter_id=chapter.id,
        learning_stage="preview",
        progress=20,
    )
    updated = repository.upsert(
        user_id=user.id,
        course_id=course.id,
        chapter_id=chapter.id,
        learning_stage="preview",
        progress=75,
    )

    assert updated is first
    assert updated.progress == 75
    assert db.scalar(select(func.count(LearningProgress.id))) == 1


def test_learning_progress_upsert_wins_over_dirty_instance_with_autoflush_disabled(
    db: Session,
) -> None:
    user = User(username="dirty_progress_student", password_hash="test", role="student")
    course = Course(name="脏状态回归测试课程")
    db.add_all([user, course])
    db.flush()
    chapter = Chapter(course_id=course.id, title="脏状态回归测试章节", sort_order=1)
    db.add(chapter)
    db.commit()

    repository = LearningRepository(db)
    record = repository.upsert(
        user_id=user.id,
        course_id=course.id,
        chapter_id=chapter.id,
        learning_stage="preview",
        progress=20,
    )
    record.progress = 5
    assert db.is_modified(record)

    updated = repository.upsert(
        user_id=user.id,
        course_id=course.id,
        chapter_id=chapter.id,
        learning_stage="preview",
        progress=75,
    )

    assert updated is record
    assert updated.progress == 75
    assert not db.is_modified(updated)
    db.expire_all()
    assert db.scalar(select(LearningProgress.progress)) == 75


def test_learning_progress_upsert_is_atomic_under_sqlite_concurrency(tmp_path) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'learning-progress.db'}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    Base.metadata.create_all(
        engine,
        tables=[User.__table__, Course.__table__, Chapter.__table__, LearningProgress.__table__],
    )
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    with session_factory() as db:
        user = User(username="concurrent_student", password_hash="test", role="student")
        course = Course(name="并发测试课程")
        db.add_all([user, course])
        db.flush()
        chapter = Chapter(course_id=course.id, title="并发测试章节", sort_order=1)
        db.add(chapter)
        db.commit()
        user_id, course_id, chapter_id = user.id, course.id, chapter.id

    # Synchronize a legacy SELECT-before-INSERT implementation to expose its
    # race deterministically. Native upserts mark their connection as a writer
    # before their same-transaction SELECT and therefore skip this barrier.
    legacy_progress_select = Barrier(2)
    write_start = Barrier(2)
    progress_write_connections: set[int] = set()
    progress_statement_lock = Lock()
    test_thread_id = get_ident()

    @event.listens_for(engine, "before_cursor_execute")
    def synchronize_first_progress_select(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if get_ident() == test_thread_id:
            return
        normalized = statement.lstrip().upper()
        connection_id = id(_connection)
        if normalized.startswith("INSERT INTO learning_progress".upper()):
            with progress_statement_lock:
                progress_write_connections.add(connection_id)
            return
        if normalized.startswith("SELECT") and "FROM learning_progress" in statement:
            with progress_statement_lock:
                follows_native_write = connection_id in progress_write_connections
            if follows_native_write:
                return
            legacy_progress_select.wait(timeout=5)

    def write_progress(value: int) -> int:
        with session_factory() as db:
            write_start.wait(timeout=5)
            record = LearningRepository(db).upsert(
                user_id=user_id,
                course_id=course_id,
                chapter_id=chapter_id,
                learning_stage="preview",
                progress=value,
            )
            return record.progress

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(write_progress, (35, 80)))

        with session_factory() as db:
            rows = list(db.scalars(select(LearningProgress)).all())

        assert len(rows) == 1
        assert rows[0].progress in {35, 80}
        # Each caller observes its own atomic write, even when the other caller
        # commits later and becomes the final database value.
        assert results == [35, 80]
    finally:
        event.remove(engine, "before_cursor_execute", synchronize_first_progress_select)
        engine.dispose()

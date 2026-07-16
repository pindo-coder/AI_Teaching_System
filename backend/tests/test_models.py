from sqlalchemy import create_engine, inspect

from app.db.base import Base


def test_all_mvp_tables_are_registered() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    assert set(inspect(engine).get_table_names()) == {
        "users",
        "courses",
        "chapters",
        "learning_progress",
        "knowledge_documents",
        "news_items",
        "classroom_activities",
        "classroom_responses",
        "study_notes",
        "review_schedules",
        "review_practices",
        "learning_task_points",
        "user_task_progress",
        "learning_events",
        "study_chat_messages",
        "news_study_notes",
        "teacher_assignments",
        "assignment_recipients",
    }

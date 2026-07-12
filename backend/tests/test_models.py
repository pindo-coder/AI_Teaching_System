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
    }

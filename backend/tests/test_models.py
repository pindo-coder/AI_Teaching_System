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
            "course_subjects",
            "academic_terms",
            "teaching_classes",
            "teaching_class_teachers",
            "teaching_class_materials",
            "class_roster_entries",
            "class_memberships",
            "student_course_seats",
            "class_groups",
            "class_group_members",
            "class_join_requests",
            "class_transfer_logs",
            "textbook_versions",
            "document_pages",
            "page_number_ranges",
            "document_outline_nodes",
            "knowledge_chunks",
            "index_versions",
            "citation_feedback",
            "document_course_scopes",
            "document_chapter_scopes",
            "document_class_scopes",
            "document_knowledge_tags",
            "material_import_batches",
            "material_import_items",
        }

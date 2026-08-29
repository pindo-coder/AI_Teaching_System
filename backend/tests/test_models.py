from sqlalchemy import Text, create_engine, inspect
from sqlalchemy.dialects import mysql, sqlite
from sqlalchemy.schema import CreateIndex, CreateTable

from app.db.base import Base
from app.models.agent_run import AgentRun
from app.models.authority_discovery import MaterialSnapshot
from app.models.citation import DocumentPage
from app.models.ai_media_asset import AiMediaAsset


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
        "discussion_threads",
        "discussion_replies",
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
            "agent_runs",
            "agent_steps",
            "agent_executions",
            "presentation_templates",
            "lesson_publications",
            "source_registries",
            "discovery_jobs",
                "material_candidates",
                    "material_snapshots",
                    "policy_changes",
                        "teaching_notifications",
                            "ai_provider_configs",
                            "ai_call_logs",
                            "ai_media_assets",
                            "password_reset_tokens",
                            "admin_password_reset_audits",
                            "password_reset_requests",
                        }


def test_document_page_uses_longtext_on_mysql() -> None:
    for column in (DocumentPage.__table__.c.text, DocumentPage.__table__.c.raw_text):
        assert isinstance(column.type.dialect_impl(mysql.dialect()), mysql.LONGTEXT)


def test_ai_media_error_text_uses_longtext_on_mysql() -> None:
    column_type = AiMediaAsset.__table__.c.error_message.type.dialect_impl(mysql.dialect())
    assert isinstance(column_type, mysql.LONGTEXT)


def test_ai_media_table_and_indexes_compile_for_sqlite_and_mysql() -> None:
    for dialect in (sqlite.dialect(), mysql.dialect()):
        table_ddl = str(CreateTable(AiMediaAsset.__table__).compile(dialect=dialect))
        assert "ai_media_assets" in table_ddl
        for index in AiMediaAsset.__table__.indexes:
            assert str(CreateIndex(index).compile(dialect=dialect))


def test_full_text_snapshots_use_longtext_only_on_mysql() -> None:
    columns = (
        MaterialSnapshot.__table__.c.content,
        AgentRun.__table__.c.context_snapshot,
    )

    for column in columns:
        assert isinstance(column.type.dialect_impl(mysql.dialect()), mysql.LONGTEXT)
        assert isinstance(column.type.dialect_impl(sqlite.dialect()), Text)

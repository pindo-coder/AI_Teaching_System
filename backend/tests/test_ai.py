from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.models.chapter import Chapter
from app.models.citation import DocumentOutlineNode, DocumentPage
from app.models.course import Course
from app.models.knowledge_document import KnowledgeDocument
from app.models.user import User


def prepare_context(db: Session, *, content: str | None = "理想信念是精神之钙。") -> tuple[dict[str, str], int, int]:
    user = User(username="ai_student", password_hash=hash_password("secure-pass-123"), role="student")
    course = Course(name="思想道德与法治", description="测试课程")
    db.add_all([user, course])
    db.flush()
    chapter = Chapter(course_id=course.id, title="坚定理想信念", content=content, sort_order=1)
    db.add(chapter)
    db.commit()
    db.refresh(user)
    db.refresh(course)
    db.refresh(chapter)
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}, course.id, chapter.id


def test_ai_assist_uses_course_context_in_mock_mode(client: TestClient, db: Session) -> None:
    headers, course_id, chapter_id = prepare_context(db)
    response = client.post(
        "/api/v1/ai/assist",
        headers=headers,
        json={
            "course_id": course_id,
            "chapter_id": chapter_id,
            "learning_stage": "preview",
            "task_type": "chapter_summary",
            "question": "帮我总结本章重点",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["grounded"] is True
    assert data["model"] == "mock"
    assert "坚定理想信念" in data["answer"]
    assert len(data["sources"]) == 1


def test_chapter_content_source_includes_clickable_pdf_location(client: TestClient, db: Session) -> None:
    headers, course_id, chapter_id = prepare_context(db)
    document = KnowledgeDocument(
        source_title="测试教材", source_type="pdf", original_filename="测试教材.pdf",
        stored_path="/tmp/test-textbook.pdf", course_id=course_id, chapter_id=None,
        vector_collection="test", source_role="primary", access_policy="full_preview",
            calibration_status="published", status="ready", chunk_count=0,
    )
    db.add(document); db.flush()
    db.add_all([
        DocumentPage(document_id=document.id, pdf_page=12, printed_page_label="3", text="章节正文", text_blocks=[]),
        DocumentPage(document_id=document.id, pdf_page=14, printed_page_label="5", text="章节正文", text_blocks=[]),
        DocumentOutlineNode(
            document_id=document.id, chapter_id=chapter_id, node_type="chapter", title="坚定理想信念",
            sort_order=1, pdf_page_start=12, pdf_page_end=14, retrieval_enabled=True,
            calibration_status="auto",
        ),
    ]); db.commit()

    response = client.post(
        "/api/v1/ai/assist", headers=headers,
        json={"course_id": course_id, "chapter_id": chapter_id, "learning_stage": "preview",
              "task_type": "chapter_summary", "question": "帮我总结本章重点"},
    )
    source = response.json()["data"]["sources"][0]
    assert source["document_id"] == document.id
    assert source["pdf_page_start"] == 12
    assert source["pdf_page_end"] == 14
    assert source["printed_page_start"] == "3"
    assert source["position"] == "教材第 3—5 页"


def test_ai_assist_refuses_when_chapter_has_no_content(client: TestClient, db: Session) -> None:
    headers, course_id, chapter_id = prepare_context(db, content=None)
    response = client.post(
        "/api/v1/ai/assist",
        headers=headers,
        json={
            "course_id": course_id,
            "chapter_id": chapter_id,
            "learning_stage": "review",
            "task_type": "review_outline",
            "question": "生成复习提纲",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["grounded"] is False
    assert response.json()["data"]["sources"] == []


def test_ai_assist_streams_sse_chunks(client: TestClient, db: Session) -> None:
    headers, course_id, chapter_id = prepare_context(db)
    response = client.post(
        "/api/v1/ai/assist/stream",
        headers=headers,
        json={
            "course_id": course_id,
            "chapter_id": chapter_id,
            "learning_stage": "preview",
            "task_type": "preview_questions",
            "question": "生成预习问题",
        },
    )
    assert response.status_code == 200
    assert "event: chunk" in response.text
    assert "event: sources" in response.text
    assert "event: done" in response.text

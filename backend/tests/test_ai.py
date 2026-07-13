from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.models.chapter import Chapter
from app.models.course import Course
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

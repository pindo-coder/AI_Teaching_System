from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.models.chapter import Chapter
from app.models.course import Course
from app.models.user import User


def test_learning_events_update_task_progress(client: TestClient, db: Session) -> None:
    user = User(username="task_student", password_hash=hash_password("secure-pass-123"), role="student")
    course = Course(name="习概", description="测试")
    db.add_all([user, course]); db.flush()
    chapter = Chapter(course_id=course.id, title="第一章", content="教材正文", sort_order=1)
    db.add(chapter); db.commit()
    headers = {"Authorization": f"Bearer {create_access_token(str(user.id))}"}

    initial = client.get(f"/api/v1/learning/task-points?course_id={course.id}&chapter_id={chapter.id}&learning_stage=preview", headers=headers)
    assert initial.status_code == 200
    assert initial.json()["data"]["progress"] == 0
    assert initial.json()["data"]["total_count"] == 4

    opened = client.post("/api/v1/learning/events", headers=headers, json={
        "course_id": course.id, "chapter_id": chapter.id, "learning_stage": "preview",
        "event_type": "chapter_opened", "event_data": {},
    })
    assert opened.status_code == 200
    assert opened.json()["data"]["completed_count"] == 1
    assert opened.json()["data"]["progress"] == 20

    read = client.post("/api/v1/learning/events", headers=headers, json={
        "course_id": course.id, "chapter_id": chapter.id, "learning_stage": "preview",
        "event_type": "reading_progress", "event_data": {"percent": 80},
    })
    assert read.status_code == 200
    assert read.json()["data"]["progress"] == 55


def test_sensitive_learning_evidence_cannot_be_forged_through_telemetry_endpoint(
    client: TestClient, db: Session
) -> None:
    user = User(username="evidence_student", password_hash=hash_password("secure-pass-123"), role="student")
    course = Course(name="证据课程", description="测试")
    db.add_all([user, course]); db.flush()
    chapter = Chapter(course_id=course.id, title="证据专题", content="教材正文", sort_order=1)
    db.add(chapter); db.commit()
    headers = {"Authorization": f"Bearer {create_access_token(str(user.id))}"}

    for event_type in (
        "ai_assist_used",
        "question_submitted",
        "note_saved",
        "activity_submitted",
        "quiz_completed",
    ):
        response = client.post(
            "/api/v1/learning/events",
            headers=headers,
            json={
                "course_id": course.id,
                "chapter_id": chapter.id,
                "learning_stage": "preview",
                "event_type": event_type,
                "event_data": {"count": 1, "task_type": "preview_questions"},
            },
        )
        assert response.status_code == 422

    summary = client.get(
        "/api/v1/learning/task-points",
        headers=headers,
        params={
            "course_id": course.id,
            "chapter_id": chapter.id,
            "learning_stage": "preview",
        },
    )
    assert summary.status_code == 200
    assert summary.json()["data"]["progress"] == 0


def test_learning_question_endpoint_persists_validated_question_evidence(
    client: TestClient, db: Session
) -> None:
    user = User(username="question_student", password_hash=hash_password("secure-pass-123"), role="student")
    course = Course(name="问题课程", description="测试")
    db.add_all([user, course]); db.flush()
    chapter = Chapter(course_id=course.id, title="问题专题", content="教材正文", sort_order=1)
    db.add(chapter); db.commit()
    headers = {"Authorization": f"Bearer {create_access_token(str(user.id))}"}

    response = client.post(
        "/api/v1/learning/questions",
        headers=headers,
        json={
            "course_id": course.id,
            "chapter_id": chapter.id,
            "learning_stage": "preview",
            "content": "为什么理想信念具有重要作用？",
        },
    )

    assert response.status_code == 200
    question_task = next(
        item for item in response.json()["data"]["tasks"]
        if item["task_type"] == "preview_question"
    )
    assert question_task["status"] == "completed"


def test_learning_telemetry_rejects_non_finite_and_oversized_data(
    client: TestClient, db: Session
) -> None:
    user = User(username="invalid_event_student", password_hash=hash_password("secure-pass-123"), role="student")
    course = Course(name="遥测课程", description="测试")
    db.add_all([user, course]); db.flush()
    chapter = Chapter(course_id=course.id, title="遥测专题", content="教材正文", sort_order=1)
    db.add(chapter); db.commit()
    headers = {"Authorization": f"Bearer {create_access_token(str(user.id))}"}
    base = {
        "course_id": course.id,
        "chapter_id": chapter.id,
        "learning_stage": "preview",
    }

    invalid_percent = client.post(
        "/api/v1/learning/events",
        headers=headers,
        json={**base, "event_type": "reading_progress", "event_data": {"percent": "nan"}},
    )
    oversized = client.post(
        "/api/v1/learning/events",
        headers=headers,
        json={**base, "event_type": "chapter_opened", "event_data": {"padding": "x" * 20_000}},
    )

    assert invalid_percent.status_code == 422
    assert oversized.status_code == 422

from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.models.chapter import Chapter
from app.models.course import Course
from app.models.user import User


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


def test_teacher_assignment_is_visible_and_auto_completed_by_learning_event(client: TestClient, db: Session) -> None:
    teacher = User(username="assignment_teacher", password_hash=hash_password("secure-pass-123"), role="teacher", identity_no="T20260101")
    student = User(username="assignment_student", password_hash=hash_password("secure-pass-123"), role="student", identity_no="S20260101")
    course = Course(name="习概", description="测试教材")
    db.add_all([teacher, student, course]); db.flush()
    chapter = Chapter(course_id=course.id, title="生态文明建设", content="推动绿色发展。", sort_order=1)
    db.add(chapter); db.commit()

    created = client.post("/api/v1/assignments", headers=_headers(teacher), json={
        "course_id": course.id, "chapter_id": chapter.id, "learning_stage": "preview",
        "task_kind": "reading", "title": "完成本章教材预读", "description": "阅读达到80%",
        "due_time": (datetime.utcnow() + timedelta(days=2)).isoformat(), "target_scope": "all_students",
    })
    assert created.status_code == 201
    assignment_id = created.json()["data"]["id"]

    pending = client.get("/api/v1/assignments/student", headers=_headers(student)).json()["data"]
    assert pending[0]["status"] == "not_started"
    assert pending[0]["chapter_title"] == "生态文明建设"

    event = client.post("/api/v1/learning/events", headers=_headers(student), json={
        "course_id": course.id, "chapter_id": chapter.id, "learning_stage": "preview",
        "event_type": "reading_progress", "event_data": {"percent": 80},
    })
    assert event.status_code == 200
    completed = client.get("/api/v1/assignments/student", headers=_headers(student)).json()["data"]
    assert completed[0]["status"] == "completed"
    assert completed[0]["progress_value"] == 100

    teacher_list = client.get("/api/v1/assignments", headers=_headers(teacher)).json()["data"]
    assert teacher_list[0]["completed_count"] == 1
    assert teacher_list[0]["total_count"] == 1

    forbidden = client.post("/api/v1/assignments", headers=_headers(student), json={
        "course_id": course.id, "chapter_id": chapter.id, "learning_stage": "preview",
        "task_kind": "reading", "title": "无权发布", "due_time": (datetime.utcnow() + timedelta(days=1)).isoformat(),
    })
    assert forbidden.status_code == 403

    cancelled = client.delete(f"/api/v1/assignments/{assignment_id}", headers=_headers(teacher))
    assert cancelled.status_code == 200
    assert client.get("/api/v1/assignments/student", headers=_headers(student)).json()["data"] == []

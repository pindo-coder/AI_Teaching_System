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

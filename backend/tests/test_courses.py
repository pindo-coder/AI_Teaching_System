from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.models.user import User


def create_user_token(db: Session, *, username: str, role: str) -> str:
    user = User(username=username, password_hash=hash_password("secure-pass-123"), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return create_access_token(str(user.id))


def test_admin_course_chapter_and_student_learning_flow(client: TestClient, db: Session) -> None:
    admin_token = create_user_token(db, username="admin01", role="admin")
    student_token = create_user_token(db, username="student01", role="student")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    student_headers = {"Authorization": f"Bearer {student_token}"}

    course_response = client.post(
        "/api/v1/courses",
        headers=admin_headers,
        json={"name": "思想道德与法治", "description": "MVP 示例课程"},
    )
    assert course_response.status_code == 201
    course_id = course_response.json()["data"]["id"]

    forbidden = client.post(
        "/api/v1/courses",
        headers=student_headers,
        json={"name": "无权限课程"},
    )
    assert forbidden.status_code == 403

    chapter_response = client.post(
        f"/api/v1/courses/{course_id}/chapters",
        headers=admin_headers,
        json={"title": "第一章 担当复兴大任 成就时代新人", "content": "章节正文", "sort_order": 1},
    )
    assert chapter_response.status_code == 201
    chapter_id = chapter_response.json()["data"]["id"]

    detail = client.get(f"/api/v1/courses/{course_id}", headers=student_headers)
    assert detail.status_code == 200
    assert len(detail.json()["data"]["chapters"]) == 1

    progress = client.put(
        "/api/v1/learning/progress",
        headers=student_headers,
        json={
            "course_id": course_id,
            "chapter_id": chapter_id,
            "learning_stage": "preview",
            "progress": 60,
        },
    )
    assert progress.status_code == 200

    dashboard = client.get("/api/v1/dashboard", headers=student_headers)
    assert dashboard.status_code == 200
    assert dashboard.json()["data"]["current_course"]["id"] == course_id
    assert dashboard.json()["data"]["overall_progress"] == 60

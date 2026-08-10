from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.models.chapter import Chapter
from app.models.course import Course
from app.models.learning_progress import LearningProgress
from app.models.user import User


def _headers_for(db: Session, *, username: str, role: str) -> dict[str, str]:
    user = User(username=username, password_hash=hash_password("secure-pass-123"), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


def test_deleting_chapter_cascades_loaded_learning_progress(
    client: TestClient, db: Session
) -> None:
    admin_headers = _headers_for(db, username="cascade-admin", role="admin")
    student = User(
        username="cascade-student",
        password_hash=hash_password("secure-pass-123"),
        role="student",
    )
    course = Course(name="级联删除测试教材")
    chapter = Chapter(course=course, title="测试专题", sort_order=1)
    db.add_all([student, course])
    db.flush()
    progress = LearningProgress(
        user=student,
        course=course,
        chapter=chapter,
        learning_stage="preview",
        progress=60,
    )
    db.add(progress)
    db.commit()

    chapter_id = chapter.id
    assert progress.id is not None

    response = client.delete(f"/api/v1/chapters/{chapter_id}", headers=admin_headers)

    assert response.status_code == 200
    assert db.scalar(select(func.count(Chapter.id)).where(Chapter.id == chapter_id)) == 0
    assert (
        db.scalar(
            select(func.count(LearningProgress.id)).where(
                LearningProgress.chapter_id == chapter_id
            )
        )
        == 0
    )


def test_registration_rejects_role_and_identity_values_not_enforced_by_mysql_57(
    client: TestClient,
) -> None:
    invalid_role = client.post(
        "/api/v1/auth/register",
        json={
            "username": "invalid-role-user",
            "password": "secure-pass-123",
            "role": "admin",
            "identity_no": "S20260009",
        },
    )
    invalid_identity = client.post(
        "/api/v1/auth/register",
        json={
            "username": "invalid-identity-user",
            "password": "secure-pass-123",
            "role": "student",
            "identity_no": "学号 2026/009",
        },
    )

    assert invalid_role.status_code == 422
    assert invalid_identity.status_code == 422


def test_learning_progress_rejects_invalid_stage_and_range_before_database(
    client: TestClient, db: Session
) -> None:
    student_headers = _headers_for(db, username="validation-student", role="student")
    course = Course(name="应用层校验测试教材")
    chapter = Chapter(course=course, title="测试专题", sort_order=1)
    db.add(course)
    db.commit()

    invalid_stage = client.put(
        "/api/v1/learning/progress",
        headers=student_headers,
        json={
            "course_id": course.id,
            "chapter_id": chapter.id,
            "learning_stage": "finished",
            "progress": 50,
        },
    )
    invalid_progress = client.put(
        "/api/v1/learning/progress",
        headers=student_headers,
        json={
            "course_id": course.id,
            "chapter_id": chapter.id,
            "learning_stage": "preview",
            "progress": 101,
        },
    )

    assert invalid_stage.status_code == 422
    assert invalid_progress.status_code == 422
    assert db.scalar(select(func.count(LearningProgress.id))) == 0

from datetime import datetime, timezone
from io import BytesIO
from zipfile import ZipFile

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.models.chapter import Chapter
from app.models.course import Course
from app.models.learning_task import LearningEvent
from app.models.teaching_class import AcademicTerm, ClassMembership, CourseSubject, TeachingClass, TeachingClassTeacher
from app.models.user import User


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user.id), user.auth_version)}"}


def test_teacher_dashboard_scopes_student_activity_to_own_classes(client: TestClient, db: Session) -> None:
    admin = User(username="dash_admin", password_hash=hash_password("pass-123456"), role="admin", approval_status="approved")
    teacher_a = User(username="dash_teacher_a", password_hash=hash_password("pass-123456"), role="teacher", approval_status="approved")
    teacher_b = User(username="dash_teacher_b", password_hash=hash_password("pass-123456"), role="teacher", approval_status="approved")
    student_a = User(username="dash_student_a", identity_no="S-DA-01", password_hash=hash_password("pass-123456"), role="student", approval_status="approved")
    student_b = User(username="dash_student_b", identity_no="S-DB-01", password_hash=hash_password("pass-123456"), role="student", approval_status="approved")
    course = Course(name="思政看板测试课", description="test")
    subject = CourseSubject(name="思政看板学科", code="SUB-DASH")
    term = AcademicTerm(name="2026秋", start_date=datetime(2026, 9, 1).date(), end_date=datetime(2027, 1, 15).date())
    db.add_all([admin, teacher_a, teacher_b, student_a, student_b, course, subject, term])
    db.flush()
    chapter = Chapter(course_id=course.id, title="第一章", content="正文", sort_order=1)
    class_a = TeachingClass(subject_id=subject.id, term_id=term.id, name="A班", code="CLS-A", owner_id=teacher_a.id, join_code="JOINA001", status="active")
    class_b = TeachingClass(subject_id=subject.id, term_id=term.id, name="B班", code="CLS-B", owner_id=teacher_b.id, join_code="JOINB001", status="active")
    db.add_all([chapter, class_a, class_b])
    db.flush()
    db.add_all([
        TeachingClassTeacher(teaching_class_id=class_a.id, user_id=teacher_a.id, teacher_role="owner"),
        TeachingClassTeacher(teaching_class_id=class_b.id, user_id=teacher_b.id, teacher_role="owner"),
        ClassMembership(teaching_class_id=class_a.id, user_id=student_a.id, status="active"),
        ClassMembership(teaching_class_id=class_b.id, user_id=student_b.id, status="active"),
        LearningEvent(
            user_id=student_a.id, course_id=course.id, chapter_id=chapter.id,
            learning_stage="preview", event_type="reading_progress",
            created_time=datetime(2026, 10, 5, 4, 0, 0, tzinfo=timezone.utc).replace(tzinfo=None),
        ),
        LearningEvent(
            user_id=student_b.id, course_id=course.id, chapter_id=chapter.id,
            learning_stage="preview", event_type="reading_progress",
            created_time=datetime(2026, 10, 5, 5, 0, 0, tzinfo=timezone.utc).replace(tzinfo=None),
        ),
    ])
    db.commit()

    resp_a = client.get("/api/v1/teacher/dashboard?month=2026-10", headers=_headers(teacher_a))
    assert resp_a.status_code == 200
    day5_a = next(item for item in resp_a.json()["data"]["activity_series"] if item["date"] == "2026-10-05")
    assert day5_a["total_students"] == 1
    assert day5_a["active_students"] == 1
    assert resp_a.json()["data"]["courses"][0]["student_count"] == 1

    resp_admin = client.get("/api/v1/teacher/dashboard?month=2026-10", headers=_headers(admin))
    assert resp_admin.status_code == 200
    day5_admin = next(item for item in resp_admin.json()["data"]["activity_series"] if item["date"] == "2026-10-05")
    assert day5_admin["total_students"] == 2
    assert day5_admin["active_students"] == 2


def test_pptx_template_rejects_zip_bomb_entry_count(client: TestClient, db: Session) -> None:
    teacher = User(username="zip_teacher", password_hash=hash_password("pass-123456"), role="teacher", approval_status="approved")
    db.add(teacher)
    db.commit()
    buf = BytesIO()
    with ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("ppt/presentation.xml", "<p:presentation xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main'/>")
        for idx in range(1005):
            zf.writestr(f"junk/f{idx}.txt", "x")
    resp = client.post(
        "/api/v1/agent/ppt-templates",
        headers=_headers(teacher),
        data={"name": "异常模板"},
        files={"file": ("bomb.pptx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
    )
    assert resp.status_code == 400
    assert "超限" in resp.json()["message"]

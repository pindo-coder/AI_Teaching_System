from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.models.chapter import Chapter
from app.models.course import Course
from app.models.user import User
from app.models.teaching_class import AcademicTerm, ClassMembership, CourseSubject, TeachingClass, TeachingClassMaterial, TeachingClassTeacher
from datetime import date


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


def test_class_wide_assignment_never_leaks_to_other_class_student(client: TestClient, db: Session) -> None:
    teacher = User(username="scoped_teacher", identity_no="T-SCOPE", password_hash=hash_password("secure-pass-123"), role="teacher", approval_status="approved")
    member = User(username="class_member", identity_no="S-MEMBER", password_hash=hash_password("secure-pass-123"), role="student")
    outsider = User(username="class_outsider", identity_no="S-OUT", password_hash=hash_password("secure-pass-123"), role="student")
    course = Course(name="教学班教材")
    subject = CourseSubject(name="教学班课程", code="SCOPE")
    term = AcademicTerm(name="2026秋", start_date=date(2026, 9, 1), end_date=date(2027, 1, 31), is_current=True)
    db.add_all([teacher, member, outsider, course, subject, term]); db.flush()
    chapter = Chapter(course_id=course.id, title="第一章", content="教材内容", sort_order=1)
    klass = TeachingClass(subject_id=subject.id, term_id=term.id, name="一班", code="01", owner_id=teacher.id, status="active", join_code="SCOPE001")
    db.add_all([chapter, klass]); db.flush()
    db.add_all([
        TeachingClassTeacher(teaching_class_id=klass.id, user_id=teacher.id, teacher_role="primary"),
        TeachingClassMaterial(teaching_class_id=klass.id, course_id=course.id, material_role="primary"),
        ClassMembership(teaching_class_id=klass.id, user_id=member.id, status="active", join_method="roster"),
    ]); db.commit()

    created = client.post("/api/v1/assignments", headers=_headers(teacher), json={
        "teaching_class_id": klass.id, "course_id": course.id, "chapter_id": chapter.id,
        "learning_stage": "preview", "task_kind": "reading", "title": "班内预习任务",
        "due_time": (datetime.utcnow() + timedelta(days=1)).isoformat(), "target_scope": "all_students",
    })
    assert created.status_code == 201
    assert len(client.get("/api/v1/assignments/student", headers=_headers(member)).json()["data"]) == 1
    assert client.get("/api/v1/assignments/student", headers=_headers(outsider)).json()["data"] == []

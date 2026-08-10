from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.core.time import BUSINESS_TIMEZONE, to_utc_naive, utc_iso, utc_now
from app.models.chapter import Chapter
from app.models.course import Course
from app.models.learning_task import UserTaskProgress
from app.models.teacher_assignment import AssignmentRecipient, TeacherAssignment
from app.models.user import User
from app.models.teaching_class import AcademicTerm, ClassMembership, CourseSubject, TeachingClass, TeachingClassMaterial, TeachingClassTeacher
from app.services.student_learning_summary_service import StudentLearningSummaryService
from app.services.task_service import TaskService


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


def test_teacher_assignment_is_visible_and_auto_completed_by_learning_event(client: TestClient, db: Session) -> None:
    teacher = User(username="assignment_teacher", password_hash=hash_password("secure-pass-123"), role="teacher", identity_no="T20260101")
    student = User(username="assignment_student", password_hash=hash_password("secure-pass-123"), role="student", identity_no="S20260101")
    course = Course(name="习概", description="测试教材")
    db.add_all([teacher, student, course]); db.flush()
    chapter = Chapter(course_id=course.id, title="生态文明建设", content="推动绿色发展。", sort_order=1)
    db.add(chapter); db.commit()
    due_time = (datetime.now(UTC) + timedelta(days=2)).astimezone(BUSINESS_TIMEZONE)

    created = client.post("/api/v1/assignments", headers=_headers(teacher), json={
        "course_id": course.id, "chapter_id": chapter.id, "learning_stage": "preview",
        "task_kind": "reading", "title": "完成本章教材预读", "description": "阅读达到80%",
        "due_time": due_time.isoformat(), "target_scope": "all_students",
    })
    assert created.status_code == 201
    created_data = created.json()["data"]
    assignment_id = created_data["id"]
    assert created_data["due_time"] == utc_iso(to_utc_naive(due_time))
    assert db.get(TeacherAssignment, assignment_id).due_time_is_utc is True

    ambiguous = client.post("/api/v1/assignments", headers=_headers(teacher), json={
        "course_id": course.id,
        "chapter_id": chapter.id,
        "learning_stage": "preview",
        "task_kind": "reading",
        "title": "缺少时区的任务",
        "due_time": due_time.replace(tzinfo=None).isoformat(),
        "target_scope": "all_students",
    })
    assert ambiguous.status_code == 422

    pending = client.get("/api/v1/assignments/student", headers=_headers(student)).json()["data"]
    assert pending[0]["status"] == "not_started"
    assert pending[0]["chapter_title"] == "生态文明建设"
    recipient_detail = client.get(
        f"/api/v1/assignments/{assignment_id}/recipients",
        headers=_headers(teacher),
    )
    assert recipient_detail.status_code == 200
    assert recipient_detail.json()["data"] == [{
        "user_id": student.id,
        "username": "assignment_student",
        "identity_no": "S20260101",
        "group_name": None,
        "status": "not_started",
        "progress_value": 0,
        "completed_time": None,
        "last_activity_time": None,
    }]
    assert client.get(
        f"/api/v1/assignments/{assignment_id}/recipients",
        headers=_headers(student),
    ).status_code == 403

    event = client.post("/api/v1/learning/events", headers=_headers(student), json={
        "course_id": course.id, "chapter_id": chapter.id, "learning_stage": "preview",
        "event_type": "reading_progress", "event_data": {"percent": 80},
    })
    assert event.status_code == 200
    completed = client.get("/api/v1/assignments/student", headers=_headers(student)).json()["data"]
    assert completed[0]["status"] == "completed"
    assert completed[0]["progress_value"] == 100
    assert completed[0]["completed_time"].endswith("Z")

    teacher_list = client.get("/api/v1/assignments", headers=_headers(teacher)).json()["data"]
    assert teacher_list[0]["completed_count"] == 1
    assert teacher_list[0]["total_count"] == 1
    completed_detail = client.get(
        f"/api/v1/assignments/{assignment_id}/recipients",
        headers=_headers(teacher),
    ).json()["data"][0]
    assert completed_detail["status"] == "completed"
    assert completed_detail["progress_value"] == 100
    assert completed_detail["last_activity_time"] is not None

    forbidden = client.post("/api/v1/assignments", headers=_headers(student), json={
        "course_id": course.id, "chapter_id": chapter.id, "learning_stage": "preview",
        "task_kind": "reading", "title": "无权发布", "due_time": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
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
        "due_time": (datetime.now(UTC) + timedelta(days=1)).isoformat(), "target_scope": "all_students",
    })
    assert created.status_code == 201
    assert len(client.get("/api/v1/assignments/student", headers=_headers(member)).json()["data"]) == 1
    assert client.get("/api/v1/assignments/student", headers=_headers(outsider)).json()["data"] == []


def test_legacy_local_due_time_is_read_as_business_time(client: TestClient, db: Session) -> None:
    teacher = User(
        username="legacy_due_teacher",
        identity_no="T-LEGACY-DUE",
        password_hash=hash_password("secure-pass-123"),
        role="teacher",
    )
    student = User(
        username="legacy_due_student",
        identity_no="S-LEGACY-DUE",
        password_hash=hash_password("secure-pass-123"),
        role="student",
    )
    course = Course(name="历史截止时间教材")
    db.add_all([teacher, student, course]); db.flush()
    chapter = Chapter(course_id=course.id, title="历史任务章节", content="正文", sort_order=1)
    db.add(chapter); db.flush()
    expected_utc = (utc_now() + timedelta(days=2)).replace(microsecond=0)
    legacy_local = (
        expected_utc.replace(tzinfo=UTC)
        .astimezone(BUSINESS_TIMEZONE)
        .replace(tzinfo=None)
    )
    reading_task = next(
        task
        for task in TaskService(db).ensure_tasks(course.id, chapter.id, "preview")
        if task.task_type == "reading_preview"
    )
    assignment = TeacherAssignment(
        created_by=teacher.id,
        course_id=course.id,
        chapter_id=chapter.id,
        learning_stage="preview",
        task_kind="reading",
        title="历史本地时间任务",
        description="",
        due_time=legacy_local,
        due_time_is_utc=False,
        status="published",
        target_scope="all_students",
        target_group_ids=[],
        required_task_types=[reading_task.task_type],
    )
    db.add(assignment); db.flush()
    recipient = AssignmentRecipient(assignment_id=assignment.id, user_id=student.id)
    db.add_all([
        recipient,
        UserTaskProgress(
            user_id=student.id,
            task_point_id=reading_task.id,
            status="completed",
            progress_value=100,
            evidence_summary="历史任务已完成",
        ),
    ])
    db.commit()

    before_sync = utc_now()
    response = client.get("/api/v1/assignments/student", headers=_headers(student))
    after_sync = utc_now()
    assert response.status_code == 200
    item = response.json()["data"][0]
    assert item["due_time"] == utc_iso(expected_utc)
    assert item["status"] == "completed"
    assert item["completed_time"].endswith("Z")

    db.refresh(recipient)
    assert recipient.completed_time is not None
    normalized_completed = to_utc_naive(
        recipient.completed_time,
        naive_timezone=BUSINESS_TIMEZONE,
    )
    assert before_sync <= normalized_completed <= after_sync
    assert item["completed_time"] == utc_iso(normalized_completed)

    summary_now = after_sync.replace(tzinfo=UTC).astimezone(BUSINESS_TIMEZONE)
    summary = StudentLearningSummaryService(db).summarize(student.id, now=summary_now)
    assert summary["assignments"]["completed_in_period"] == 1

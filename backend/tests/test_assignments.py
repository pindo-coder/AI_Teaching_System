from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.core.time import BUSINESS_TIMEZONE, to_utc_naive, utc_iso, utc_now
from app.models.chapter import Chapter
from app.models.course import Course
from app.models.learning_task import UserTaskProgress
from app.models.classroom import DiscussionThread
from app.models.teacher_assignment import AssignmentRecipient, AssignmentRequirementProgress, TeacherAssignment
from app.schemas.task import LearningEventCreate
from app.models.user import User
from app.models.teaching_class import AcademicTerm, ClassMembership, CourseSubject, TeachingClass, TeachingClassMaterial, TeachingClassTeacher
from app.services.student_learning_summary_service import StudentLearningSummaryService
from app.services.assignment_service import AssignmentService
from app.services.task_service import TaskService


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


def test_quiz_requirement_routes_to_exam_practice(db: Session) -> None:
    assignment = TeacherAssignment(
        created_by=1,
        course_id=7,
        chapter_id=9,
        learning_stage="review",
        task_kind="composite",
        title="组合任务",
        description="",
        due_time=datetime.now(UTC),
        status="published",
        target_scope="selected_students",
        target_group_ids=[],
        required_task_types=[],
        completion_policy={},
    )

    assert AssignmentService(db)._next_path(assignment, "quiz_completed") == (
        "/courses/7/chapters/9/exam?focus=practice"
    )


def test_generic_ai_requirement_counts_successful_ai_use_from_any_stage(
    client: TestClient,
    db: Session,
) -> None:
    teacher = User(
        username="ai_policy_teacher",
        identity_no="T-AI-POLICY",
        password_hash=hash_password("secure-pass-123"),
        role="teacher",
    )
    student = User(
        username="ai_policy_student",
        identity_no="S-AI-POLICY",
        password_hash=hash_password("secure-pass-123"),
        role="student",
    )
    course = Course(name="AI 条件教材")
    db.add_all([teacher, student, course]); db.flush()
    chapter = Chapter(course_id=course.id, title="AI 条件章节", content="正文", sort_order=1)
    db.add(chapter); db.commit()

    created = client.post("/api/v1/assignments", headers=_headers(teacher), json={
        "course_id": course.id,
        "chapter_id": chapter.id,
        "learning_stage": "exam",
        "task_kind": "ai_assist",
        "title": "使用一次 AI 学习辅助",
        "due_time": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        "target_scope": "all_students",
        # Mirrors policies created before generic AI evidence was stage-independent.
        "completion_policy": {
            "mode": "all_required",
            "items": [{
                "key": "ai",
                "label": "使用 AI 学习辅助",
                "event": "ai_assist_used",
                "metric": "count",
                "target": 1,
                "weight": 100,
                "required": True,
                "stage": "assignment",
                "task_types": ["mock_questions", "review_outline"],
            }],
        },
    })
    assert created.status_code == 201

    TaskService(db).record(student.id, LearningEventCreate(
        course_id=course.id,
        chapter_id=chapter.id,
        learning_stage="review",
        event_type="ai_assist_used",
        event_data={"task_type": "chapter_summary"},
    ))

    task = client.get(
        "/api/v1/assignments/student",
        headers=_headers(student),
    ).json()["data"][0]
    assert task["status"] == "completed"
    assert task["requirements"][0]["current_value"] == 1


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
        "completion_status": "not_started",
        "is_overdue": False,
        "requirements": [],
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


def test_composite_assignment_uses_explicit_evidence_and_backfills_discussions(
    client: TestClient,
    db: Session,
) -> None:
    teacher = User(
        username="policy_teacher", identity_no="T-POLICY",
        password_hash=hash_password("secure-pass-123"), role="teacher",
    )
    student = User(
        username="policy_student", identity_no="S-POLICY",
        password_hash=hash_password("secure-pass-123"), role="student",
    )
    course = Course(name="组合任务教材")
    db.add_all([teacher, student, course]); db.flush()
    chapter = Chapter(course_id=course.id, title="组合任务章节", content="正文", sort_order=1)
    db.add(chapter); db.commit()
    policy = {
        "mode": "all_required",
        "items": [
            {"key": "reading", "label": "阅读教材原文", "event": "reading_progress", "metric": "percent", "target": 80, "weight": 34, "required": True, "stage": "assignment", "task_types": []},
            {"key": "note", "label": "保存个人笔记", "event": "note_saved", "metric": "length", "target": 30, "weight": 33, "required": True, "stage": "any", "task_types": []},
            {"key": "discussion", "label": "发布讨论主题", "event": "discussion_created", "metric": "count", "target": 1, "weight": 33, "required": True, "stage": "any", "task_types": []},
        ],
    }
    response = client.post("/api/v1/assignments", headers=_headers(teacher), json={
        "course_id": course.id,
        "chapter_id": chapter.id,
        "learning_stage": "exam",
        "task_kind": "composite",
        "title": "完成组合复习任务",
        "due_time": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        "target_scope": "all_students",
        "completion_policy": policy,
    })
    assert response.status_code == 201
    assignment_id = response.json()["data"]["id"]

    TaskService(db).record(student.id, LearningEventCreate(
        course_id=course.id, chapter_id=chapter.id, learning_stage="exam",
        event_type="reading_progress", event_data={"percent": 80},
    ))
    TaskService(db).record(student.id, LearningEventCreate(
        course_id=course.id, chapter_id=chapter.id, learning_stage="review",
        event_type="note_saved", event_data={"content_length": 45},
    ))
    partial = client.get("/api/v1/assignments/student", headers=_headers(student)).json()["data"][0]
    assert partial["status"] == "in_progress"
    assert partial["progress_value"] == 67
    assert [item["status"] for item in partial["requirements"]] == ["completed", "completed", "not_started"]
    assert partial["next_path"] == "/interaction"

    # Source-table fallback makes discussions created before event instrumentation count too.
    db.add(DiscussionThread(
        course_id=course.id, chapter_id=chapter.id, author_id=student.id,
        title="我的讨论", content="结合教材讨论", status="published",
    ))
    db.commit()
    completed = client.get("/api/v1/assignments/student", headers=_headers(student)).json()["data"][0]
    assert completed["status"] == "completed"
    assert completed["progress_value"] == 100
    rows = db.query(AssignmentRequirementProgress).filter_by(
        assignment_id=assignment_id, user_id=student.id,
    ).all()
    assert len(rows) == 3

    invalid = client.put(
        f"/api/v1/assignments/{assignment_id}/completion-policy",
        headers=_headers(teacher),
        json={"completion_policy": {"mode": "all_required", "items": [
            {**policy["items"][0], "weight": 99},
        ]}},
    )
    assert invalid.status_code == 422

    updated_policy = {
        "mode": "all_required",
        "items": [
            {**policy["items"][2], "weight": 50},
            {"key": "reply", "label": "回复课堂讨论", "event": "discussion_reply_created", "metric": "count", "target": 1, "weight": 50, "required": True, "stage": "any", "task_types": []},
        ],
    }
    updated = client.put(
        f"/api/v1/assignments/{assignment_id}/completion-policy",
        headers=_headers(teacher),
        json={"completion_policy": updated_policy},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["task_kind"] == "composite"
    recalculated = client.get(
        "/api/v1/assignments/student", headers=_headers(student)
    ).json()["data"][0]
    assert recalculated["status"] == "in_progress"
    assert recalculated["progress_value"] == 50
    assert len(recalculated["requirements"]) == 2


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
    assert summary["assignments"]["completed_items"] == [{
        "assignment_id": assignment.id,
        "course_id": course.id,
        "course_name": course.name,
        "chapter_id": chapter.id,
        "chapter_title": chapter.title,
        "title": assignment.title,
        "completed_time": utc_iso(normalized_completed),
    }]
    assert summary["assignments"]["completed_items_truncated"] is False

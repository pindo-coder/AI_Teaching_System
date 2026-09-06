from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.models.chapter import Chapter
from app.models.classroom import ClassroomActivity
from app.models.course import Course
from app.models.teaching_class import (
    AcademicTerm, ClassGroup, ClassGroupMember, ClassMembership, TeachingClass,
    TeachingClassMaterial, TeachingClassTeacher, CourseSubject,
)
from app.models.user import User


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


def test_classroom_activity_limits_groups_counts_and_reviews(client: TestClient, db: Session) -> None:
    teacher = User(username="activity_teacher", identity_no="A-T1", password_hash=hash_password("secure-pass-123"), role="teacher", approval_status="approved")
    leader = User(username="activity_leader", identity_no="A-S1", password_hash=hash_password("secure-pass-123"), role="student", approval_status="approved")
    member = User(username="activity_member", identity_no="A-S2", password_hash=hash_password("secure-pass-123"), role="student", approval_status="approved")
    db.add_all([teacher, leader, member]); db.flush()
    subject = CourseSubject(name="课堂互动测试科目")
    term = AcademicTerm(name="课堂互动测试学期", start_date=datetime(2026, 1, 1).date(), end_date=datetime(2026, 12, 31).date(), is_current=True)
    course = Course(name="课堂互动测试课程")
    db.add_all([subject, term, course]); db.flush()
    chapter = Chapter(course_id=course.id, title="第一专题", content="这是用于 AI 点评的教材正文。")
    teaching_class = TeachingClass(subject_id=subject.id, term_id=term.id, name="互动测试班", code="ACT-01", owner_id=teacher.id, join_code="ACT001")
    db.add_all([chapter, teaching_class]); db.flush()
    db.add_all([
        TeachingClassMaterial(teaching_class_id=teaching_class.id, course_id=course.id, material_role="primary"),
        TeachingClassTeacher(teaching_class_id=teaching_class.id, user_id=teacher.id, teacher_role="primary"),
        ClassMembership(teaching_class_id=teaching_class.id, user_id=leader.id, status="active"),
        ClassMembership(teaching_class_id=teaching_class.id, user_id=member.id, status="active"),
    ])
    group = ClassGroup(teaching_class_id=teaching_class.id, name="第一组", leader_user_id=leader.id)
    db.add(group); db.flush()
    db.add_all([
        ClassGroupMember(teaching_class_id=teaching_class.id, group_id=group.id, user_id=leader.id),
        ClassGroupMember(teaching_class_id=teaching_class.id, group_id=group.id, user_id=member.id),
    ])
    db.commit()

    created = client.post("/api/v1/classroom/activities", headers=_headers(teacher), json={
        "teaching_class_id": teaching_class.id, "course_id": course.id, "chapter_id": chapter.id,
        "question": "请结合教材回答这个问题", "minutes": 8, "activity_type": "group",
        "response_limit": 2, "grouping_mode": "manual",
        "deadline_time": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    })
    assert created.status_code == 201, created.text
    activity_id = created.json()["data"]["id"]

    blocked = client.post(f"/api/v1/classroom/activities/{activity_id}/responses", headers=_headers(member), json={"answer": "成员不能直接提交"})
    assert blocked.status_code == 403
    for answer in ("第一份回答", "第二份回答"):
        response = client.post(f"/api/v1/classroom/activities/{activity_id}/responses", headers=_headers(leader), json={"answer": answer})
        assert response.status_code == 201, response.text
    limited = client.post(f"/api/v1/classroom/activities/{activity_id}/responses", headers=_headers(leader), json={"answer": "超出次数"})
    assert limited.status_code == 400

    student_view = client.get(f"/api/v1/classroom/activities/{activity_id}/responses", headers=_headers(leader))
    assert student_view.status_code == 200
    assert student_view.json()["data"]["response_count"] == 1
    assert {item["user_name"] for item in student_view.json()["data"]["responses"]} == {"我的回答"}

    teacher_view = client.get(f"/api/v1/classroom/activities/{activity_id}/responses", headers=_headers(teacher))
    assert teacher_view.status_code == 200
    assert teacher_view.json()["data"]["response_count"] == 1
    response_id = teacher_view.json()["data"]["responses"][0]["id"]
    comment = client.patch(f"/api/v1/classroom/activities/{activity_id}/responses/{response_id}", headers=_headers(teacher), json={"teacher_comment": "请补充教材依据"})
    assert comment.status_code == 200
    ai_review = client.post(f"/api/v1/classroom/activities/{activity_id}/responses/{response_id}/ai-review", headers=_headers(teacher))
    assert ai_review.status_code == 200, ai_review.text
    assert ai_review.json()["data"]["ai_comment"]

    persisted = db.get(ClassroomActivity, activity_id)
    assert persisted is not None
    assert persisted.response_limit == 2

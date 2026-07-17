from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.models.course import Course
from app.models.teaching_class import AcademicTerm, CourseSubject, TeachingClass
from app.models.user import User


def headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


def test_class_join_review_and_same_subject_transfer_rule(client: TestClient, db: Session) -> None:
    teacher = User(username="class_teacher", identity_no="T-CLASS", password_hash=hash_password("password-123"),
                   role="teacher", approval_status="approved")
    student = User(username="class_student", identity_no="S-CLASS", password_hash=hash_password("password-123"),
                   role="student", approval_status="approved")
    course = Course(name="主教材")
    subject = CourseSubject(name="习近平新时代中国特色社会主义思想概论", code="XG")
    term = AcademicTerm(name="2026秋季", start_date=date(2026, 9, 1), end_date=date(2027, 1, 31), is_current=True)
    db.add_all([teacher, student, course, subject, term]); db.commit()

    created = client.post("/api/v1/teaching-classes", headers=headers(teacher), json={
        "subject_id": subject.id, "term_id": term.id, "name": "一班", "code": "01",
        "primary_course_id": course.id, "supplementary_course_ids": [],
    })
    assert created.status_code == 201
    first = created.json()["data"]

    requested = client.post("/api/v1/teaching-classes/join", headers=headers(student),
                            json={"join_code": first["join_code"]})
    assert requested.status_code == 200
    assert requested.json()["data"]["status"] == "pending"

    from app.models.teaching_class import ClassJoinRequest
    request = db.query(ClassJoinRequest).filter_by(user_id=student.id).one()
    reviewed = client.post(f"/api/v1/teaching-classes/join-requests/{request.id}/review",
                           headers=headers(teacher), json={"approved": True})
    assert reviewed.status_code == 200
    assert client.get("/api/v1/teaching-classes", headers=headers(student)).json()["data"][0]["membership_status"] == "active"

    second = client.post("/api/v1/teaching-classes", headers=headers(teacher), json={
        "subject_id": subject.id, "term_id": term.id, "name": "二班", "code": "02",
        "primary_course_id": course.id,
    }).json()["data"]
    transfer = client.post("/api/v1/teaching-classes/join", headers=headers(student),
                           json={"join_code": second["join_code"]})
    assert transfer.json()["data"]["status"] == "pending"

    first_class = db.get(TeachingClass, first["id"])
    first_class.is_default = True; db.commit()
    # 删除上一条待审核转班申请后重新发起，默认班允许直接转入正式班。
    db.delete(db.query(ClassJoinRequest).filter_by(teaching_class_id=second["id"], user_id=student.id).one()); db.commit()
    direct = client.post("/api/v1/teaching-classes/join", headers=headers(student),
                         json={"join_code": second["join_code"]})
    assert direct.json()["data"]["status"] == "transferred"

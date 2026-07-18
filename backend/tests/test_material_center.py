import json
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.models.chapter import Chapter
from app.models.course import Course
from app.models.teaching_class import (
    AcademicTerm, ClassMembership, CourseSubject, TeachingClass, TeachingClassTeacher,
)
from app.models.user import User
from app.rag.retriever import RetrievedChunk, retrieve_layered
from app.repositories.knowledge_repository import KnowledgeRepository


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


def _context(db: Session) -> tuple[User, User, User, Course, Chapter, TeachingClass]:
    admin = User(username="material_admin", password_hash=hash_password("password-123"), role="admin")
    teacher = User(username="material_teacher", password_hash=hash_password("password-123"), role="teacher",
                   approval_status="approved")
    student = User(username="material_student", password_hash=hash_password("password-123"), role="student")
    course = Course(name="习近平新时代中国特色社会主义思想概论")
    subject = CourseSubject(name="思想政治理论课")
    term = AcademicTerm(name="2026秋", start_date=date(2026, 9, 1), end_date=date(2027, 1, 20), is_current=True)
    db.add_all([admin, teacher, student, course, subject, term]); db.flush()
    chapter = Chapter(course_id=course.id, title="全面建设社会主义现代化国家", content="中国式现代化是人口规模巨大的现代化。", sort_order=1)
    teaching_class = TeachingClass(subject_id=subject.id, term_id=term.id, name="思政一班", code="SZ01",
                                   owner_id=teacher.id, join_code="MATCLASS", status="active")
    db.add_all([chapter, teaching_class]); db.flush()
    db.add(TeachingClassTeacher(teaching_class_id=teaching_class.id, user_id=teacher.id, teacher_role="primary"))
    db.commit()
    return admin, teacher, student, course, chapter, teaching_class


def test_central_material_requires_admin_confirmation_before_retrieval(client: TestClient, db: Session) -> None:
    admin, teacher, student, course, chapter, _ = _context(db)
    denied = client.post(
        "/api/v1/knowledge/materials", headers=_headers(teacher),
        data={"material_type": "central", "source_title": "中央材料", "publisher": "中央有关部门",
              "published_date": "2026-07-01", "course_ids": json.dumps([course.id]),
              "chapter_ids": json.dumps([chapter.id])},
        files={"file": ("central.md", "中央材料真实正文。".encode(), "text/markdown")},
    )
    assert denied.status_code == 403

    uploaded = client.post(
        "/api/v1/knowledge/materials", headers=_headers(admin),
        data={"material_type": "central", "source_title": "中央现代化建设材料", "publisher": "中央有关部门",
              "published_date": "2026-07-01", "course_ids": json.dumps([course.id]),
              "chapter_ids": json.dumps([chapter.id]), "knowledge_tags": json.dumps(["中国式现代化"])},
        files={"file": ("central.md", "中国式现代化建设必须坚持党的领导。".encode(), "text/markdown")},
    )
    assert uploaded.status_code == 201, uploaded.text
    document = uploaded.json()["data"]
    assert document["review_status"] == "pending"
    assert KnowledgeRepository(db).eligible_layer_ids(course_id=course.id, chapter_id=chapter.id, user=student)["central"] == []

    scoped = client.put(
        f"/api/v1/knowledge/materials/{document['id']}/scopes", headers=_headers(admin),
        json={"course_ids": [course.id], "chapter_ids": [chapter.id], "teaching_class_ids": [],
              "knowledge_tags": ["中国式现代化"]},
    )
    assert scoped.status_code == 200, scoped.text
    published = client.post(f"/api/v1/knowledge/materials/{document['id']}/publish", headers=_headers(admin))
    assert published.status_code == 200, published.text
    assert KnowledgeRepository(db).eligible_layer_ids(course_id=course.id, chapter_id=chapter.id, user=student)["central"] == [document["id"]]


def test_local_material_is_limited_to_selected_teaching_class(client: TestClient, db: Session) -> None:
    admin, teacher, student, course, chapter, teaching_class = _context(db)
    uploaded = client.post(
        "/api/v1/knowledge/materials", headers=_headers(teacher),
        data={"material_type": "local", "source_title": "地方实践案例", "publisher": "本地教学单位",
              "published_date": "2026-06-01", "applicable_scope": "本教学班",
              "course_ids": json.dumps([course.id]), "chapter_ids": json.dumps([chapter.id]),
              "teaching_class_ids": json.dumps([teaching_class.id])},
        files={"file": ("local.md", "地方现代化建设实践案例。".encode(), "text/markdown")},
    )
    assert uploaded.status_code == 201, uploaded.text
    document_id = uploaded.json()["data"]["id"]
    repository = KnowledgeRepository(db)
    assert repository.eligible_layer_ids(course_id=course.id, chapter_id=chapter.id, user=student)["local"] == []
    assert repository.eligible_layer_ids(course_id=course.id, chapter_id=chapter.id, user=admin)["local"] == [document_id]
    denied = client.get(
        f"/api/v1/knowledge/documents/{document_id}/pages?page=1", headers=_headers(student)
    )
    assert denied.status_code == 403
    db.add(ClassMembership(teaching_class_id=teaching_class.id, user_id=student.id, status="active", join_method="code"))
    db.commit()
    assert repository.eligible_layer_ids(course_id=course.id, chapter_id=chapter.id, user=student)["local"] == [document_id]
    allowed = client.get(
        f"/api/v1/knowledge/documents/{document_id}/pages?page=1", headers=_headers(student)
    )
    assert allowed.status_code == 200


def test_layered_retrieval_respects_source_quotas(monkeypatch) -> None:
    pools = {
        "central": [RetrievedChunk("c1", {"vector_id": "c1"}, .95), RetrievedChunk("c2", {"vector_id": "c2"}, .9), RetrievedChunk("c3", {"vector_id": "c3"}, .88)],
        "textbook": [RetrievedChunk(f"t{i}", {"vector_id": f"t{i}"}, .8 - i * .01) for i in range(1, 7)],
        "local": [RetrievedChunk("l1", {"vector_id": "l1"}, .99), RetrievedChunk("l2", {"vector_id": "l2"}, .98)],
    }

    def fake_retrieve(*args, material_type: str, **kwargs):
        return pools[material_type]

    monkeypatch.setattr("app.rag.retriever.retrieve_documents", fake_retrieve)
    result = retrieve_layered("问题", layer_document_ids={"central": [1], "textbook": [2], "local": [3]}, chapter_id=1, top_k=6)
    ids = [item.metadata["vector_id"] for item in result]
    assert len([item for item in ids if str(item).startswith("c")]) == 2
    assert len([item for item in ids if str(item).startswith("l")]) == 1
    assert len([item for item in ids if str(item).startswith("t")]) == 3

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.models.chapter import Chapter
from app.models.citation import DocumentOutlineNode, TextbookVersion
from app.models.course import Course
from app.models.knowledge_document import KnowledgeDocument
from app.models.user import User
from app.repositories.knowledge_repository import KnowledgeRepository


def prepare_manager(db: Session, role: str = "teacher") -> tuple[dict[str, str], int, int]:
    user = User(username=f"{role}_kb", password_hash=hash_password("secure-pass-123"), role=role)
    course = Course(name="毛泽东思想和中国特色社会主义理论体系概论", description="知识库测试")
    db.add_all([user, course])
    db.flush()
    chapter = Chapter(course_id=course.id, title="马克思主义中国化时代化", content="章节基础内容", sort_order=1)
    db.add(chapter)
    db.commit()
    db.refresh(user)
    db.refresh(course)
    db.refresh(chapter)
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}, course.id, chapter.id


def test_upload_search_reindex_and_delete_document(client: TestClient, db: Session) -> None:
    headers, course_id, chapter_id = prepare_manager(db)
    upload = client.post(
        "/api/v1/knowledge/documents",
        headers=headers,
        data={
            "source_title": "测试教材第一章",
            "course_id": str(course_id),
            "chapter_id": str(chapter_id),
            "knowledge_point": "马克思主义中国化时代化",
        },
        files={"file": ("chapter.md", "# 第一章\n马克思主义中国化时代化是一个历史过程。", "text/markdown")},
    )
    assert upload.status_code == 201, upload.text
    document = upload.json()["data"]
    assert document["status"] == "ready"
    assert document["chunk_count"] == 1

    listed = client.get("/api/v1/knowledge/documents", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()["data"]) == 1

    search = client.post(
        "/api/v1/knowledge/search",
        headers=headers,
        json={"question": "马克思主义中国化", "course_id": course_id, "chapter_id": chapter_id, "top_k": 4},
    )
    assert search.status_code == 200
    assert search.json()["data"][0]["metadata"]["source_title"] == "测试教材第一章"

    ai_response = client.post(
        "/api/v1/ai/assist",
        headers=headers,
        json={
            "course_id": course_id,
            "chapter_id": chapter_id,
            "learning_stage": "review",
            "task_type": "question_answer",
            "question": "什么是马克思主义中国化时代化？",
        },
    )
    assert ai_response.status_code == 200
    source = ai_response.json()["data"]["sources"][0]
    assert source["source_title"] == "测试教材第一章"
    assert source["document_id"] == document["id"]
    assert source["pdf_page_start"] == 1
    assert source["evidence_type"] == "教材直接依据"

    reindex = client.post(f"/api/v1/knowledge/documents/{document['id']}/reindex", headers=headers)
    assert reindex.status_code == 200
    assert reindex.json()["data"]["status"] == "ready"

    deleted = client.delete(f"/api/v1/knowledge/documents/{document['id']}", headers=headers)
    assert deleted.status_code == 200
    assert client.get("/api/v1/knowledge/documents", headers=headers).json()["data"] == []


def test_student_cannot_manage_knowledge_base(client: TestClient, db: Session) -> None:
    headers, _, _ = prepare_manager(db, role="student")
    response = client.get("/api/v1/knowledge/documents", headers=headers)
    assert response.status_code == 403


def test_rejects_unsupported_file_type(client: TestClient, db: Session) -> None:
    headers, course_id, _ = prepare_manager(db)
    response = client.post(
        "/api/v1/knowledge/documents",
        headers=headers,
        data={"source_title": "非法文件", "course_id": str(course_id)},
        files={"file": ("payload.exe", b"not allowed", "application/octet-stream")},
    )
    assert response.status_code == 400


def test_upload_new_version_can_auto_create_pending_outline(client: TestClient, db: Session) -> None:
    headers, course_id, chapter_id = prepare_manager(db)
    response = client.post(
        "/api/v1/knowledge/documents",
        headers=headers,
        data={
            "source_title": "OCR 修订版教材",
            "course_id": str(course_id),
            "version_label": "2023版 OCR修订版",
            "source_role": "primary",
            "access_policy": "full_preview",
            "auto_calibrate": "true",
        },
        files={"file": ("ocr.md", "# 马克思主义中国化时代化\n教材完整正文。", "text/markdown")},
    )
    assert response.status_code == 201, response.text
    document = response.json()["data"]
    assert document["calibration_status"] == "pending"
    assert document["status"] == "processing"
    outline = db.query(DocumentOutlineNode).filter_by(document_id=document["id"]).one()
    assert outline.chapter_id == chapter_id
    assert db.get(Chapter, chapter_id).content == "章节基础内容"

    rerun = client.post(f"/api/v1/knowledge/documents/{document['id']}/auto-calibrate", headers=headers)
    assert rerun.status_code == 200, rerun.text
    assert db.query(DocumentOutlineNode).filter_by(document_id=document["id"]).count() == 1


def test_only_current_published_pdf_version_is_ready_for_ai(db: Session) -> None:
    course = Course(name="教材版本切换测试")
    db.add(course); db.flush()
    old_version = TextbookVersion(course_id=course.id, version_label="旧版", status="published", is_current=False)
    new_version = TextbookVersion(course_id=course.id, version_label="OCR版", status="published", is_current=True)
    db.add_all([old_version, new_version]); db.flush()
    db.add_all([
        KnowledgeDocument(source_title="旧教材", source_type="pdf", original_filename="old.pdf",
                          stored_path="/tmp/old.pdf", course_id=course.id, vector_collection="test",
                          textbook_version_id=old_version.id, status="ready", calibration_status="published", chunk_count=1),
        KnowledgeDocument(source_title="新教材", source_type="pdf", original_filename="new.pdf",
                          stored_path="/tmp/new.pdf", course_id=course.id, vector_collection="test",
                          textbook_version_id=new_version.id, status="ready", calibration_status="published", chunk_count=1),
    ]); db.commit()
    assert [item.source_title for item in KnowledgeRepository(db).list_ready_for_course(course.id)] == ["新教材"]

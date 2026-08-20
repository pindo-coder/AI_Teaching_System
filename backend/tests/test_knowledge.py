from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.models.chapter import Chapter
from app.models.citation import DocumentOutlineNode, DocumentPage, TextbookVersion
from app.models.course import Course
from app.models.knowledge_document import KnowledgeDocument
from app.models.user import User
from app.repositories.knowledge_repository import KnowledgeRepository
from app.rag.document_loader import ExtractedPage


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


def test_pending_pdf_can_refresh_ocr_without_losing_outline_or_printed_page(
    client: TestClient, db: Session, tmp_path, monkeypatch,
) -> None:
    headers, course_id, chapter_id = prepare_manager(db)
    pdf_path = tmp_path / "pending-ocr.pdf"
    pdf_path.write_bytes(b"%PDF-placeholder")
    document = KnowledgeDocument(
        source_title="待清洗教材", source_type="pdf", original_filename="pending-ocr.pdf",
        stored_path=str(pdf_path), course_id=course_id, vector_collection="test",
        status="processing", calibration_status="pending", chunk_count=0,
    )
    db.add(document); db.flush()
    db.add_all([
        DocumentPage(
            document_id=document.id, pdf_page=1, printed_page_label="137",
            raw_text="旧文字", text="旧文字", text_blocks=[],
        ),
        DocumentOutlineNode(
            document_id=document.id, chapter_id=chapter_id, node_type="chapter", title="第七章",
            sort_order=1, pdf_page_start=1, pdf_page_end=1, retrieval_enabled=True,
        ),
    ])
    db.commit()
    blocks = [{
        "id": "p1-b0", "text": "重新提取的正文", "bbox": [80, 150, 500, 180],
        "excluded": False, "exclusion_reason": None, "manual_override": None,
    }]
    monkeypatch.setattr(
        "app.services.knowledge_service.extract_pages",
        lambda *_: [ExtractedPage(
            pdf_page=1, raw_text="重新提取的正文", text="重新提取的正文",
            width=595, height=842, text_blocks=blocks,
        )],
    )

    response = client.post(f"/api/v1/knowledge/documents/{document.id}/refresh-ocr", headers=headers)

    assert response.status_code == 200, response.text
    refreshed_page = db.query(DocumentPage).filter_by(document_id=document.id).one()
    assert refreshed_page.raw_text == "重新提取的正文"
    assert refreshed_page.printed_page_label == "137"
    assert db.query(DocumentOutlineNode).filter_by(document_id=document.id).count() == 1


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
        KnowledgeDocument(source_title="旧版文本教材", source_type="md", original_filename="old.md",
                          stored_path="/tmp/old.md", course_id=course.id, vector_collection="test",
                          textbook_version_id=old_version.id, status="ready", calibration_status="calibrated", chunk_count=1),
        KnowledgeDocument(source_title="当前文本教材", source_type="md", original_filename="new.md",
                          stored_path="/tmp/new.md", course_id=course.id, vector_collection="test",
                          textbook_version_id=new_version.id, status="ready", calibration_status="calibrated", chunk_count=1),
    ]); db.commit()
    assert {item.source_title for item in KnowledgeRepository(db).list_ready_for_course(course.id)} == {
        "新教材", "当前文本教材",
    }


def test_admin_can_list_and_restore_published_textbook_version(client: TestClient, db: Session) -> None:
    headers, course_id, _ = prepare_manager(db, role="admin")
    old_version = TextbookVersion(course_id=course_id, version_label="2023 历史版", status="published", is_current=False)
    current_version = TextbookVersion(course_id=course_id, version_label="2026 当前版", status="published", is_current=True)
    db.add_all([old_version, current_version]); db.flush()
    db.add_all([
        KnowledgeDocument(source_title="历史教材", source_type="pdf", original_filename="old.pdf",
                          stored_path="/tmp/old.pdf", course_id=course_id, vector_collection="test",
                          textbook_version_id=old_version.id, status="ready", calibration_status="published", chunk_count=1),
        KnowledgeDocument(source_title="当前教材", source_type="pdf", original_filename="current.pdf",
                          stored_path="/tmp/current.pdf", course_id=course_id, vector_collection="test",
                          textbook_version_id=current_version.id, status="ready", calibration_status="published", chunk_count=1),
    ]); db.commit()

    listed = client.get(f"/api/v1/knowledge/courses/{course_id}/versions", headers=headers)
    assert listed.status_code == 200, listed.text
    assert {item["version_label"] for item in listed.json()["data"]} == {"2023 历史版", "2026 当前版"}

    activated = client.post(f"/api/v1/knowledge/versions/{old_version.id}/activate", headers=headers)
    assert activated.status_code == 200, activated.text
    db.refresh(old_version); db.refresh(current_version)
    assert old_version.is_current is True
    assert current_version.is_current is False
    assert [item.source_title for item in KnowledgeRepository(db).list_ready_for_course(course_id)] == ["历史教材"]

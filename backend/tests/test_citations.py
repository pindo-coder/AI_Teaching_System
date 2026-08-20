from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.models.citation import DocumentOutlineNode, DocumentPage, KnowledgeChunk
from app.models.course import Course
from app.models.knowledge_document import KnowledgeDocument
from app.models.user import User
from app.rag.vector_store import IncompatibleVectorIndexError
from app.schemas.knowledge import DocumentCalibrationUpdate
from app.services.citation_service import CitationService, _roman, _roman_value


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


def test_roman_printed_page_roundtrip() -> None:
    assert _roman_value("xiv") == 14
    assert _roman(14) == "XIV"


def test_calibration_manifest_failure_rolls_back_database_changes(
    db: Session, monkeypatch,
) -> None:
    course = Course(name="校准事务测试")
    db.add(course); db.flush()
    document = KnowledgeDocument(
        source_title="事务教材", source_type="pdf", original_filename="transaction.pdf",
        stored_path="/tmp/transaction.pdf", course_id=course.id,
        vector_collection="old-active", calibration_status="pending", status="processing",
        chunk_count=1,
    )
    db.add(document); db.flush()
    page_text = "第一章 绪论\n\n这是用于重新生成索引的教材正文。"
    page = DocumentPage(
        document_id=document.id, pdf_page=1, raw_text=page_text, text=page_text,
        text_blocks=[],
    )
    old_outline = DocumentOutlineNode(
        document_id=document.id, node_type="chapter", title="旧章节",
        sort_order=1, pdf_page_start=1, pdf_page_end=1, retrieval_enabled=True,
    )
    old_chunk = KnowledgeChunk(
        document_id=document.id, vector_id=f"document-{document.id}-chunk-0",
        chunk_index=0, content="旧索引正文", pdf_page_start=1, pdf_page_end=1,
        index_version="old:embedding:256:test",
    )
    db.add_all([page, old_outline, old_chunk]); db.commit()

    monkeypatch.setattr(
        "app.services.citation_service.resolve_active_collection_name",
        lambda: (_ for _ in ()).throw(IncompatibleVectorIndexError("活动索引维度不兼容")),
    )
    payload = DocumentCalibrationUpdate.model_validate({
        "version_label": "当前版",
        "access_policy": "full_preview",
        "page_number_ranges": [],
        "outline": [{
            "client_id": "new-chapter", "node_type": "chapter", "title": "新章节",
            "sort_order": 1, "pdf_page_start": 1, "pdf_page_end": 1,
            "retrieval_enabled": True,
        }],
    })

    with pytest.raises(HTTPException) as raised:
        CitationService(db).calibrate(document.id, payload)

    assert raised.value.status_code == 503
    assert raised.value.detail == "活动索引维度不兼容"
    assert db.query(KnowledgeChunk).filter_by(document_id=document.id).one().content == "旧索引正文"
    assert db.query(DocumentOutlineNode).filter_by(document_id=document.id).one().title == "旧章节"
    restored = db.get(KnowledgeDocument, document.id)
    assert restored is not None
    assert restored.vector_collection == "old-active"
    assert restored.status == "processing"


def test_citation_only_document_exposes_only_requested_page(client: TestClient, db: Session, tmp_path: Path) -> None:
    student = User(username="citation_student", identity_no="S-CITE", password_hash=hash_password("password-123"), role="student")
    teacher = User(username="citation_teacher", identity_no="T-CITE", password_hash=hash_password("password-123"), role="teacher", approval_status="approved")
    course = Course(name="引用测试教材")
    db.add_all([student, teacher, course]); db.flush()
    file_path = tmp_path / "citation.pdf"
    writer = PdfWriter(); writer.add_blank_page(width=595, height=842)
    with file_path.open("wb") as stream: writer.write(stream)
    document = KnowledgeDocument(
        source_title="教材原文", source_type="pdf", original_filename="教材原文.pdf",
        stored_path=str(file_path), course_id=course.id, chapter_id=None,
        vector_collection="test", source_role="primary", access_policy="citation_only",
        calibration_status="published", status="ready", chunk_count=1,
    )
    db.add(document); db.flush()
    page_text = "全过程人民民主是社会主义民主政治的本质属性。"
    db.add(DocumentPage(
        document_id=document.id, pdf_page=1, printed_page_label="1", raw_text=page_text, text=page_text,
        text_blocks=[{
            "id": "p1-b0", "text": page_text, "bbox": [60, 120, 520, 150],
            "excluded": False, "exclusion_reason": None, "manual_override": None,
        }],
    ))
    db.commit()

    assert client.get(f"/api/v1/knowledge/documents/{document.id}/pages", headers=_headers(student)).status_code == 403
    page = client.get(f"/api/v1/knowledge/documents/{document.id}/pages?page=1", headers=_headers(student))
    assert page.status_code == 200
    assert page.json()["data"][0]["printed_page_label"] == "1"
    assert page.json()["data"][0]["raw_text"] is None
    assert client.get(f"/api/v1/knowledge/documents/{document.id}/file", headers=_headers(student)).status_code == 403
    cited_file = client.get(f"/api/v1/knowledge/documents/{document.id}/file?page=1", headers=_headers(student))
    assert cited_file.status_code == 200
    assert cited_file.headers["content-type"].startswith("application/pdf")
    assert client.get(f"/api/v1/knowledge/documents/{document.id}/file", headers=_headers(teacher)).status_code == 200

    excluded = client.put(
        f"/api/v1/knowledge/documents/{document.id}/pages/1/text-blocks/p1-b0",
        headers=_headers(teacher), json={"excluded": True},
    )
    assert excluded.status_code == 200, excluded.text
    assert excluded.json()["data"]["text"] == ""
    assert excluded.json()["data"]["text_blocks"][0]["manual_override"] == "exclude"

    restored = client.put(
        f"/api/v1/knowledge/documents/{document.id}/pages/1/text-blocks/p1-b0",
        headers=_headers(teacher), json={"excluded": False},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["data"]["text"] == page_text

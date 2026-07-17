from pathlib import Path

from fastapi.testclient import TestClient
from pypdf import PdfWriter
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.models.citation import DocumentPage
from app.models.course import Course
from app.models.knowledge_document import KnowledgeDocument
from app.models.user import User
from app.services.citation_service import _roman, _roman_value


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


def test_roman_printed_page_roundtrip() -> None:
    assert _roman_value("xiv") == 14
    assert _roman(14) == "XIV"


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
    db.add(DocumentPage(document_id=document.id, pdf_page=1, printed_page_label="1",
                        text="全过程人民民主是社会主义民主政治的本质属性。", text_blocks=[]))
    db.commit()

    assert client.get(f"/api/v1/knowledge/documents/{document.id}/pages", headers=_headers(student)).status_code == 403
    page = client.get(f"/api/v1/knowledge/documents/{document.id}/pages?page=1", headers=_headers(student))
    assert page.status_code == 200
    assert page.json()["data"][0]["printed_page_label"] == "1"
    assert client.get(f"/api/v1/knowledge/documents/{document.id}/file", headers=_headers(student)).status_code == 403
    cited_file = client.get(f"/api/v1/knowledge/documents/{document.id}/file?page=1", headers=_headers(student))
    assert cited_file.status_code == 200
    assert cited_file.headers["content-type"].startswith("application/pdf")
    assert client.get(f"/api/v1/knowledge/documents/{document.id}/file", headers=_headers(teacher)).status_code == 200

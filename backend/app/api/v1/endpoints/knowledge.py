from io import BytesIO
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_roles
from app.db.session import get_db
from app.models.user import User
from app.repositories.knowledge_repository import KnowledgeRepository
from app.schemas.common import ApiResponse
from app.schemas.knowledge import (
    CitationFeedbackCreate, DocumentCalibrationUpdate, KnowledgeDocumentRead,
    KnowledgeSearchItem, KnowledgeSearchRequest,
)
from app.services.knowledge_service import KnowledgeService
from app.services.citation_service import CitationService
from app.repositories.course_repository import ChapterRepository
from app.models.citation import PageNumberRange, TextbookVersion
from sqlalchemy import select


router = APIRouter(prefix="/knowledge", tags=["knowledge"])
knowledge_manager = require_roles("teacher", "admin")


@router.post(
    "/documents",
    response_model=ApiResponse[KnowledgeDocumentRead],
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    file: Annotated[UploadFile, File()],
    source_title: Annotated[str, Form(min_length=1, max_length=255)],
    course_id: Annotated[int, Form()],
    chapter_id: Annotated[int | None, Form()] = None,
    knowledge_point: Annotated[str | None, Form(max_length=255)] = None,
    version_label: Annotated[str, Form(max_length=100)] = "当前版",
    source_role: Annotated[str, Form(pattern="^(primary|supplementary)$")] = "primary",
    access_policy: Annotated[str, Form(pattern="^(citation_only|full_preview|download)$")] = "full_preview",
    auto_calibrate: Annotated[bool, Form()] = False,
    _: User = Depends(knowledge_manager),
    db: Session = Depends(get_db),
) -> ApiResponse[KnowledgeDocumentRead]:
    content = await file.read()
    chapters = ChapterRepository(db).list_by_course(course_id) if auto_calibrate else []
    if auto_calibrate and not chapters:
        raise HTTPException(status_code=400, detail="当前教材还没有专题，无法自动生成章节边界")
    if auto_calibrate and db.scalar(select(TextbookVersion).where(
        TextbookVersion.course_id == course_id,
        TextbookVersion.version_label == version_label,
    )):
        raise HTTPException(
            status_code=409,
            detail="教材版本标识已存在，请为新文件填写不同的版本名称",
        )
    document = KnowledgeService(db).ingest(
        filename=file.filename or "unknown",
        content=content,
        source_title=source_title,
        course_id=course_id,
        chapter_id=chapter_id,
        knowledge_point=knowledge_point,
        version_label=version_label,
        source_role=source_role,
        access_policy=access_policy,
        defer_index=auto_calibrate,
    )
    if auto_calibrate:
        document = CitationService(db).auto_calibrate(document.id, chapters, version_label=version_label)
    message = "新版本已上传并生成待确认章节边界" if auto_calibrate else "文档上传并建立索引成功"
    return ApiResponse(message=message, data=KnowledgeDocumentRead.model_validate(document))


@router.get("/documents", response_model=ApiResponse[list[KnowledgeDocumentRead]])
def list_documents(
    course_id: int | None = None,
    _: User = Depends(knowledge_manager),
    db: Session = Depends(get_db),
) -> ApiResponse[list[KnowledgeDocumentRead]]:
    documents = KnowledgeRepository(db).list(course_id=course_id)
    return ApiResponse(data=[KnowledgeDocumentRead.model_validate(item) for item in documents])


@router.get("/documents/{document_id}", response_model=ApiResponse[KnowledgeDocumentRead])
def get_document(
    document_id: int,
    _: User = Depends(knowledge_manager),
    db: Session = Depends(get_db),
) -> ApiResponse[KnowledgeDocumentRead]:
    document = KnowledgeService(db).require_document(document_id)
    return ApiResponse(data=KnowledgeDocumentRead.model_validate(document))


@router.get("/documents/{document_id}/pages", response_model=ApiResponse[list[dict]])
def document_pages(document_id: int, user: User = Depends(get_current_user),
                   page: int | None = None, db: Session = Depends(get_db)) -> ApiResponse[list[dict]]:
    service = CitationService(db); document = service.require_document(document_id)
    if document.access_policy == "citation_only" and page is None and user.role == "student":
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="该资料仅允许查看引用所在页")
    pages = service.pages(document_id)
    if page is not None:
        pages = [item for item in pages if item.pdf_page == page]
    return ApiResponse(data=[{"id": page.id, "pdf_page": page.pdf_page,
                              "printed_page_label": page.printed_page_label,
                              "text": page.text, "width": page.width, "height": page.height} for page in pages])


@router.get("/documents/{document_id}/outline", response_model=ApiResponse[list[dict]])
def document_outline(document_id: int, _: User = Depends(get_current_user),
                     db: Session = Depends(get_db)) -> ApiResponse[list[dict]]:
    nodes = CitationService(db).outline(document_id)
    return ApiResponse(data=[{"id": node.id, "parent_id": node.parent_id, "chapter_id": node.chapter_id,
                              "node_type": node.node_type, "title": node.title, "sort_order": node.sort_order,
                              "pdf_page_start": node.pdf_page_start, "pdf_page_end": node.pdf_page_end,
                              "start_anchor": node.start_anchor, "end_anchor": node.end_anchor,
                              "retrieval_enabled": node.retrieval_enabled,
                              "calibration_status": node.calibration_status} for node in nodes])


@router.get("/documents/{document_id}/calibration-meta", response_model=ApiResponse[dict])
def calibration_meta(document_id: int, _: User = Depends(knowledge_manager),
                     db: Session = Depends(get_db)) -> ApiResponse[dict]:
    document = CitationService(db).require_document(document_id)
    ranges = db.scalars(select(PageNumberRange).where(
        PageNumberRange.document_id == document_id
    ).order_by(PageNumberRange.pdf_page_start)).all()
    version = db.get(TextbookVersion, document.textbook_version_id) if document.textbook_version_id else None
    return ApiResponse(data={
        "version_label": version.version_label if version else "当前版",
        "access_policy": document.access_policy,
        "page_number_ranges": [{
            "pdf_page_start": item.pdf_page_start, "pdf_page_end": item.pdf_page_end,
            "numbering_style": item.numbering_style, "printed_start": item.printed_start,
        } for item in ranges],
    })


@router.get("/documents/{document_id}/file")
def document_file(document_id: int, user: User = Depends(get_current_user),
                  page: int | None = None, db: Session = Depends(get_db)):
    document = CitationService(db).require_document(document_id)
    if document.access_policy == "citation_only" and page is None and user.role == "student":
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="该资料仅允许查看引用所在页")
    if page is not None and document.source_type == "pdf":
        from fastapi import HTTPException
        from pypdf import PdfReader, PdfWriter

        reader = PdfReader(document.stored_path)
        if page < 1 or page > len(reader.pages):
            raise HTTPException(status_code=404, detail="引用页不存在")
        writer = PdfWriter()
        writer.add_page(reader.pages[page - 1])
        output = BytesIO()
        writer.write(output)
        output.seek(0)
        return StreamingResponse(output, media_type="application/pdf", headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(document.original_filename)}",
            "Cache-Control": "private, max-age=300",
        })
    response = FileResponse(document.stored_path,
                            media_type="application/pdf" if document.source_type == "pdf" else "text/plain")
    disposition = "attachment" if document.access_policy == "download" else "inline"
    response.headers["Content-Disposition"] = (
        f"{disposition}; filename*=UTF-8''{quote(document.original_filename)}"
    )
    return response


@router.put("/documents/{document_id}/calibration", response_model=ApiResponse[KnowledgeDocumentRead])
def calibrate_document(document_id: int, payload: DocumentCalibrationUpdate,
                       _: User = Depends(knowledge_manager), db: Session = Depends(get_db)) -> ApiResponse[KnowledgeDocumentRead]:
    document = CitationService(db).calibrate(document_id, payload)
    return ApiResponse(message="教材结构已校准，受影响索引已重建", data=KnowledgeDocumentRead.model_validate(document))


@router.post("/documents/{document_id}/publish", response_model=ApiResponse[KnowledgeDocumentRead])
def publish_document(document_id: int, _: User = Depends(require_roles("admin")),
                     db: Session = Depends(get_db)) -> ApiResponse[KnowledgeDocumentRead]:
    document = CitationService(db).publish(document_id)
    return ApiResponse(message="教材版本已发布", data=KnowledgeDocumentRead.model_validate(document))


@router.post("/citation-feedback", response_model=ApiResponse[dict], status_code=status.HTTP_201_CREATED)
def citation_feedback(payload: CitationFeedbackCreate, user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)) -> ApiResponse[dict]:
    record = CitationService(db).feedback(user.id, payload)
    return ApiResponse(message="引用问题已记录", data={"id": record.id})


@router.delete("/documents/{document_id}", response_model=ApiResponse[dict[str, int]])
def delete_document(
    document_id: int,
    _: User = Depends(knowledge_manager),
    db: Session = Depends(get_db),
) -> ApiResponse[dict[str, int]]:
    KnowledgeService(db).delete(document_id)
    return ApiResponse(message="文档及向量索引已删除", data={"id": document_id})


@router.post("/documents/{document_id}/reindex", response_model=ApiResponse[KnowledgeDocumentRead])
def reindex_document(
    document_id: int,
    _: User = Depends(knowledge_manager),
    db: Session = Depends(get_db),
) -> ApiResponse[KnowledgeDocumentRead]:
    document = KnowledgeService(db).reindex(document_id)
    return ApiResponse(message="文档重新索引成功", data=KnowledgeDocumentRead.model_validate(document))


@router.post("/documents/{document_id}/auto-calibrate", response_model=ApiResponse[KnowledgeDocumentRead])
def auto_calibrate_document(
    document_id: int,
    _: User = Depends(knowledge_manager),
    db: Session = Depends(get_db),
) -> ApiResponse[KnowledgeDocumentRead]:
    document = KnowledgeService(db).require_document(document_id)
    chapters = ChapterRepository(db).list_by_course(document.course_id)
    if not chapters:
        raise HTTPException(status_code=400, detail="当前教材还没有专题，无法自动拆分")
    version = db.get(TextbookVersion, document.textbook_version_id) if document.textbook_version_id else None
    calibrated = CitationService(db).auto_calibrate(
        document.id, chapters, version_label=version.version_label if version else "当前版"
    )
    return ApiResponse(message="已重新生成待确认章节边界", data=KnowledgeDocumentRead.model_validate(calibrated))


@router.post("/search", response_model=ApiResponse[list[KnowledgeSearchItem]])
def search_knowledge(
    payload: KnowledgeSearchRequest,
    _: User = Depends(knowledge_manager),
    db: Session = Depends(get_db),
) -> ApiResponse[list[KnowledgeSearchItem]]:
    chunks = KnowledgeService(db).search(
        payload.question,
        course_id=payload.course_id,
        chapter_id=payload.chapter_id,
        top_k=payload.top_k,
    )
    return ApiResponse(
        data=[
            KnowledgeSearchItem(content=item.content, score=item.score, metadata=item.metadata)
            for item in chunks
        ]
    )

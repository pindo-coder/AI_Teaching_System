from io import BytesIO
from typing import Annotated
from urllib.parse import quote
from datetime import date
import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_roles
from app.db.session import get_db
from app.models.user import User
from app.models.knowledge_document import KnowledgeDocument
from app.repositories.knowledge_repository import KnowledgeRepository
from app.schemas.common import ApiResponse
from app.schemas.knowledge import (
    CitationFeedbackCreate, DocumentCalibrationUpdate, KnowledgeDocumentRead,
    KnowledgeSearchItem, KnowledgeSearchRequest, MaterialClassificationUpdate,
    MaterialScopeUpdate, MaterialSuggestion, MaterialUrlCreate, TextbookVersionRead,
)
from app.services.knowledge_service import KnowledgeService
from app.services.citation_service import CitationService
from app.repositories.course_repository import ChapterRepository
from app.models.citation import PageNumberRange, TextbookVersion
from sqlalchemy import select
from app.services.material_center_service import MaterialCenterService


router = APIRouter(prefix="/knowledge", tags=["knowledge"])
knowledge_manager = require_roles("teacher", "admin")


def _form_ints(value: str, field: str) -> list[int]:
    try:
        parsed = json.loads(value or "[]")
        if not isinstance(parsed, list) or any(not isinstance(item, int) for item in parsed):
            raise ValueError
        return list(dict.fromkeys(parsed))
    except (ValueError, TypeError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail=f"{field} 格式无效") from None


def _form_strings(value: str, field: str) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
        if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
            raise ValueError
        return list(dict.fromkeys(item.strip() for item in parsed if item.strip()))
    except (ValueError, TypeError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail=f"{field} 格式无效") from None


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
    user: User = Depends(knowledge_manager),
    db: Session = Depends(get_db),
) -> ApiResponse[list[KnowledgeDocumentRead]]:
    documents = MaterialCenterService(db).list_for_user(user)
    if course_id is not None:
        documents = [item for item in documents if item.course_id == course_id or course_id in item.course_ids]
    return ApiResponse(data=documents)


@router.get("/materials", response_model=ApiResponse[list[KnowledgeDocumentRead]])
def list_materials(
    material_type: str | None = None,
    review_status: str | None = None,
    user: User = Depends(knowledge_manager),
    db: Session = Depends(get_db),
) -> ApiResponse[list[KnowledgeDocumentRead]]:
    if material_type and material_type not in {"central", "textbook", "local", "unclassified"}:
        raise HTTPException(status_code=400, detail="资料类型无效")
    return ApiResponse(data=MaterialCenterService(db).list_for_user(
        user, material_type=material_type, review_status=review_status
    ))


@router.post("/materials", response_model=ApiResponse[KnowledgeDocumentRead], status_code=status.HTTP_201_CREATED)
async def upload_material(
    file: Annotated[UploadFile, File()],
    material_type: Annotated[str, Form(pattern="^(central|local)$")],
    source_title: Annotated[str, Form(min_length=1, max_length=255)],
    publisher: Annotated[str, Form(min_length=1, max_length=255)],
    published_date: Annotated[date, Form()],
    applicable_scope: Annotated[str | None, Form(max_length=500)] = None,
    version_label: Annotated[str | None, Form(max_length=100)] = None,
    supersedes_document_id: Annotated[int | None, Form()] = None,
    access_policy: Annotated[str, Form(pattern="^(citation_only|full_preview|download)$")] = "full_preview",
    course_ids: Annotated[str, Form()] = "[]",
    chapter_ids: Annotated[str, Form()] = "[]",
    teaching_class_ids: Annotated[str, Form()] = "[]",
    knowledge_tags: Annotated[str, Form()] = "[]",
    user: User = Depends(knowledge_manager),
    db: Session = Depends(get_db),
) -> ApiResponse[KnowledgeDocumentRead]:
    content = await file.read()
    service = MaterialCenterService(db)
    document = service.ingest_file(
        user, material_type=material_type, filename=file.filename or "unknown",
        content=content, source_title=source_title, publisher=publisher,
        published_date=published_date, applicable_scope=applicable_scope,
        version_label=version_label, supersedes_document_id=supersedes_document_id,
        access_policy=access_policy, course_ids=_form_ints(course_ids, "教材范围"),
        chapter_ids=_form_ints(chapter_ids, "专题范围"),
        class_ids=_form_ints(teaching_class_ids, "教学班范围"),
        knowledge_tags=_form_strings(knowledge_tags, "知识点"),
    )
    message = "中央材料已上传，请确认智能关联后发布" if material_type == "central" else "地方材料已加入所选教学班"
    return ApiResponse(message=message, data=service.read(document))


@router.post("/materials/url", response_model=ApiResponse[KnowledgeDocumentRead], status_code=status.HTTP_201_CREATED)
def import_material_url(
    payload: MaterialUrlCreate,
    user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> ApiResponse[KnowledgeDocumentRead]:
    service = MaterialCenterService(db)
    document = service.ingest_url(
        user, source_url=payload.source_url, source_title=payload.source_title,
        publisher=payload.publisher, published_date=payload.published_date,
        applicable_scope=payload.applicable_scope, version_label=payload.version_label,
        supersedes_document_id=payload.supersedes_document_id,
        access_policy=payload.access_policy, course_ids=payload.course_ids,
        chapter_ids=payload.chapter_ids, knowledge_tags=payload.knowledge_tags,
    )
    return ApiResponse(message="网页正文已存档，请确认智能关联后发布", data=service.read(document))


@router.get("/materials/{document_id}/suggestions", response_model=ApiResponse[list[MaterialSuggestion]])
def material_suggestions(
    document_id: int,
    user: User = Depends(knowledge_manager),
    db: Session = Depends(get_db),
) -> ApiResponse[list[MaterialSuggestion]]:
    document = KnowledgeService(db).require_document(document_id)
    if document.material_type == "central" and user.role != "admin":
        raise HTTPException(status_code=403, detail="只有管理员可以确认中央材料关联")
    if document.material_type == "local" and user.role != "admin" and document.owner_user_id != user.id:
        raise HTTPException(status_code=403, detail="无权查看该资料的关联建议")
    return ApiResponse(data=MaterialCenterService(db).suggestions(document_id))


@router.put("/materials/{document_id}/scopes", response_model=ApiResponse[KnowledgeDocumentRead])
def update_material_scopes(
    document_id: int,
    payload: MaterialScopeUpdate,
    user: User = Depends(knowledge_manager),
    db: Session = Depends(get_db),
) -> ApiResponse[KnowledgeDocumentRead]:
    service = MaterialCenterService(db)
    document = service.knowledge.require_document(document_id)
    document = service.replace_scopes(
        document, user, course_ids=payload.course_ids, chapter_ids=payload.chapter_ids,
        class_ids=payload.teaching_class_ids, knowledge_tags=payload.knowledge_tags,
        confirmed=True,
    )
    return ApiResponse(message="资料适用范围已确认", data=service.read(document))


@router.post("/materials/{document_id}/publish", response_model=ApiResponse[KnowledgeDocumentRead])
def publish_material(
    document_id: int,
    user: User = Depends(knowledge_manager),
    db: Session = Depends(get_db),
) -> ApiResponse[KnowledgeDocumentRead]:
    service = MaterialCenterService(db)
    return ApiResponse(message="资料已发布并进入权威检索", data=service.read(service.publish(document_id, user)))


@router.post("/materials/{document_id}/archive", response_model=ApiResponse[KnowledgeDocumentRead])
def archive_material(
    document_id: int,
    user: User = Depends(knowledge_manager),
    db: Session = Depends(get_db),
) -> ApiResponse[KnowledgeDocumentRead]:
    service = MaterialCenterService(db)
    return ApiResponse(message="资料已归档，不再参与新回答", data=service.read(service.archive(document_id, user)))


@router.put("/materials/{document_id}/classification", response_model=ApiResponse[KnowledgeDocumentRead])
def classify_material(
    document_id: int,
    payload: MaterialClassificationUpdate,
    user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> ApiResponse[KnowledgeDocumentRead]:
    service = MaterialCenterService(db)
    document = service.classify(
        document_id, user, material_type=payload.material_type, publisher=payload.publisher,
        published_date=payload.published_date, applicable_scope=payload.applicable_scope,
    )
    return ApiResponse(message="历史资料分类已确认并重建索引", data=service.read(document))


@router.get("/courses/{course_id}/versions", response_model=ApiResponse[list[TextbookVersionRead]])
def list_textbook_versions(
    course_id: int,
    _: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> ApiResponse[list[TextbookVersionRead]]:
    versions = list(db.scalars(select(TextbookVersion).where(
        TextbookVersion.course_id == course_id
    ).order_by(TextbookVersion.created_time.desc(), TextbookVersion.id.desc())).all())
    documents = list(db.scalars(select(KnowledgeDocument).where(
        KnowledgeDocument.course_id == course_id
    ).order_by(KnowledgeDocument.created_time.desc())).all())
    by_version: dict[int, list[KnowledgeDocumentRead]] = {}
    for document in documents:
        if document.textbook_version_id:
            by_version.setdefault(document.textbook_version_id, []).append(
                KnowledgeDocumentRead.model_validate(document)
            )
    return ApiResponse(data=[TextbookVersionRead(
        id=version.id,
        course_id=version.course_id,
        version_label=version.version_label,
        status=version.status,
        is_current=version.is_current,
        created_time=version.created_time,
        documents=by_version.get(version.id, []),
    ) for version in versions])


@router.post("/versions/{version_id}/activate", response_model=ApiResponse[TextbookVersionRead])
def activate_textbook_version(
    version_id: int,
    _: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> ApiResponse[TextbookVersionRead]:
    version = CitationService(db).activate_version(version_id)
    documents = list(db.scalars(select(KnowledgeDocument).where(
        KnowledgeDocument.textbook_version_id == version.id
    ).order_by(KnowledgeDocument.created_time.desc())).all())
    return ApiResponse(message="当前教材版本已切换", data=TextbookVersionRead(
        id=version.id,
        course_id=version.course_id,
        version_label=version.version_label,
        status=version.status,
        is_current=version.is_current,
        created_time=version.created_time,
        documents=[KnowledgeDocumentRead.model_validate(item) for item in documents],
    ))


@router.get("/documents/{document_id}", response_model=ApiResponse[KnowledgeDocumentRead])
def get_document(
    document_id: int,
    user: User = Depends(knowledge_manager),
    db: Session = Depends(get_db),
) -> ApiResponse[KnowledgeDocumentRead]:
    document = KnowledgeService(db).require_document(document_id)
    service = MaterialCenterService(db)
    service.ensure_document_access(document, user)
    return ApiResponse(data=service.read(document))


@router.get("/documents/{document_id}/pages", response_model=ApiResponse[list[dict]])
def document_pages(document_id: int, user: User = Depends(get_current_user),
                   page: int | None = None, db: Session = Depends(get_db)) -> ApiResponse[list[dict]]:
    service = CitationService(db); document = service.require_document(document_id)
    MaterialCenterService(db).ensure_document_access(document, user)
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
def document_outline(document_id: int, user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)) -> ApiResponse[list[dict]]:
    document = KnowledgeService(db).require_document(document_id)
    MaterialCenterService(db).ensure_document_access(document, user)
    nodes = CitationService(db).outline(document_id)
    return ApiResponse(data=[{"id": node.id, "parent_id": node.parent_id, "chapter_id": node.chapter_id,
                              "node_type": node.node_type, "title": node.title, "sort_order": node.sort_order,
                              "pdf_page_start": node.pdf_page_start, "pdf_page_end": node.pdf_page_end,
                              "start_anchor": node.start_anchor, "end_anchor": node.end_anchor,
                              "retrieval_enabled": node.retrieval_enabled,
                              "calibration_status": node.calibration_status} for node in nodes])


@router.get("/documents/{document_id}/calibration-meta", response_model=ApiResponse[dict])
def calibration_meta(document_id: int, user: User = Depends(knowledge_manager),
                     db: Session = Depends(get_db)) -> ApiResponse[dict]:
    document = CitationService(db).require_document(document_id)
    MaterialCenterService(db).ensure_document_access(document, user)
    if document.material_type != "textbook":
        raise HTTPException(status_code=400, detail="只有教材正文可以进行引用校准")
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
    MaterialCenterService(db).ensure_document_access(document, user)
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
                       user: User = Depends(knowledge_manager), db: Session = Depends(get_db)) -> ApiResponse[KnowledgeDocumentRead]:
    document = KnowledgeService(db).require_document(document_id)
    MaterialCenterService(db).ensure_document_access(document, user)
    if document.material_type != "textbook":
        raise HTTPException(status_code=400, detail="只有教材正文可以进行引用校准")
    document = CitationService(db).calibrate(document_id, payload)
    return ApiResponse(message="教材结构已校准，受影响索引已重建", data=KnowledgeDocumentRead.model_validate(document))


@router.post("/documents/{document_id}/publish", response_model=ApiResponse[KnowledgeDocumentRead])
def publish_document(document_id: int, _: User = Depends(require_roles("admin")),
                     db: Session = Depends(get_db)) -> ApiResponse[KnowledgeDocumentRead]:
    document = KnowledgeService(db).require_document(document_id)
    if document.material_type != "textbook":
        raise HTTPException(status_code=400, detail="中央或地方材料请使用资料中心发布流程")
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
    user: User = Depends(knowledge_manager),
    db: Session = Depends(get_db),
) -> ApiResponse[dict[str, int]]:
    service = KnowledgeService(db)
    document = service.require_document(document_id)
    if document.material_type == "central" and user.role != "admin":
        raise HTTPException(status_code=403, detail="只有管理员可以删除中央材料草稿")
    if document.material_type == "local" and user.role != "admin" and document.owner_user_id != user.id:
        raise HTTPException(status_code=403, detail="无权删除该地方材料")
    service.delete(document_id)
    return ApiResponse(message="文档及向量索引已删除", data={"id": document_id})


@router.post("/documents/{document_id}/reindex", response_model=ApiResponse[KnowledgeDocumentRead])
def reindex_document(
    document_id: int,
    user: User = Depends(knowledge_manager),
    db: Session = Depends(get_db),
) -> ApiResponse[KnowledgeDocumentRead]:
    service = KnowledgeService(db)
    document = service.require_document(document_id)
    if document.material_type == "central" and user.role != "admin":
        raise HTTPException(status_code=403, detail="只有管理员可以重建中央材料索引")
    if document.material_type == "local" and user.role != "admin" and document.owner_user_id != user.id:
        raise HTTPException(status_code=403, detail="无权重建该地方材料索引")
    document = service.reindex(document_id)
    return ApiResponse(message="文档重新索引成功", data=KnowledgeDocumentRead.model_validate(document))


@router.post("/documents/{document_id}/auto-calibrate", response_model=ApiResponse[KnowledgeDocumentRead])
def auto_calibrate_document(
    document_id: int,
    user: User = Depends(knowledge_manager),
    db: Session = Depends(get_db),
) -> ApiResponse[KnowledgeDocumentRead]:
    document = KnowledgeService(db).require_document(document_id)
    MaterialCenterService(db).ensure_document_access(document, user)
    if document.material_type != "textbook":
        raise HTTPException(status_code=400, detail="只有教材正文可以自动拆分专题")
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

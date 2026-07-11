from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy.orm import Session

from app.api.dependencies import require_roles
from app.db.session import get_db
from app.models.user import User
from app.repositories.knowledge_repository import KnowledgeRepository
from app.schemas.common import ApiResponse
from app.schemas.knowledge import KnowledgeDocumentRead, KnowledgeSearchItem, KnowledgeSearchRequest
from app.services.knowledge_service import KnowledgeService


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
    _: User = Depends(knowledge_manager),
    db: Session = Depends(get_db),
) -> ApiResponse[KnowledgeDocumentRead]:
    content = await file.read()
    document = KnowledgeService(db).ingest(
        filename=file.filename or "unknown",
        content=content,
        source_title=source_title,
        course_id=course_id,
        chapter_id=chapter_id,
        knowledge_point=knowledge_point,
    )
    return ApiResponse(message="文档上传并建立索引成功", data=KnowledgeDocumentRead.model_validate(document))


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

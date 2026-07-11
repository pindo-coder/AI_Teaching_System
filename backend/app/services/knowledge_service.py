from pathlib import Path
from uuid import uuid4
import logging

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.rag.document_loader import SUPPORTED_EXTENSIONS, extract_text
from app.rag.retriever import RetrievedChunk, retrieve
from app.rag.text_splitter import split_text
from app.rag.vector_store import add_chunks, delete_document_vectors, resolve_backend_path
from app.repositories.course_repository import ChapterRepository, CourseRepository
from app.repositories.knowledge_repository import KnowledgeRepository
from app.models.knowledge_document import KnowledgeDocument


logger = logging.getLogger(__name__)


class KnowledgeService:
    def __init__(self, db: Session) -> None:
        self.documents = KnowledgeRepository(db)
        self.courses = CourseRepository(db)
        self.chapters = ChapterRepository(db)

    def ingest(
        self,
        *,
        filename: str,
        content: bytes,
        source_title: str,
        course_id: int,
        chapter_id: int | None,
        knowledge_point: str | None,
    ) -> KnowledgeDocument:
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持 PDF、TXT、Markdown 文件")
        if suffix == ".pdf" and not content.startswith(b"%PDF-"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件扩展名与 PDF 内容不匹配")
        if not source_title.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="资料标题不能为空")
        if len(content) > settings.max_upload_size_mb * 1024 * 1024:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"文件不能超过 {settings.max_upload_size_mb} MB",
            )
        course = self.courses.get(course_id)
        if course is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="课程不存在")
        if chapter_id is not None:
            chapter = self.chapters.get(chapter_id)
            if chapter is None or chapter.course_id != course_id:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="章节与课程不匹配")
        try:
            text = extract_text(filename, content)
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        chunks = split_text(text)
        if not chunks:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件没有可入库的文本内容")

        upload_dir = resolve_backend_path(settings.knowledge_upload_directory)
        upload_dir.mkdir(parents=True, exist_ok=True)
        stored_path = upload_dir / f"{uuid4().hex}{suffix}"
        stored_path.write_bytes(content)
        document = self.documents.create(
            source_title=source_title.strip(),
            source_type=suffix.lstrip("."),
            original_filename=Path(filename).name,
            stored_path=str(stored_path),
            course_id=course_id,
            chapter_id=chapter_id,
            knowledge_point=knowledge_point.strip() if knowledge_point else None,
            vector_collection=settings.rag_collection_name,
            status="processing",
            chunk_count=0,
        )
        try:
            add_chunks(
                document_id=document.id,
                chunks=chunks,
                metadata={
                    "source_title": document.source_title,
                    "source_type": document.source_type,
                    "course_id": course_id,
                    "chapter_id": chapter_id if chapter_id is not None else -1,
                    "knowledge_point": document.knowledge_point or "",
                    "authority_level": "",
                    "effective_date": "",
                    "expired_date": "",
                },
            )
            document.status = "ready"
            document.chunk_count = len(chunks)
        except Exception as exc:
            document.status = "failed"
            self.documents.save(document)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="文档向量化失败") from exc
        saved = self.documents.save(document)
        logger.info(
            "knowledge_ingested document_id=%s course_id=%s chapter_id=%s chunks=%s",
            saved.id,
            saved.course_id,
            saved.chapter_id,
            saved.chunk_count,
        )
        return saved

    def require_document(self, document_id: int) -> KnowledgeDocument:
        document = self.documents.get(document_id)
        if document is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识库文档不存在")
        return document

    def delete(self, document_id: int) -> None:
        document = self.require_document(document_id)
        delete_document_vectors(document.id)
        path = Path(document.stored_path)
        if path.exists():
            path.unlink()
        self.documents.delete(document)
        logger.info("knowledge_deleted document_id=%s", document_id)

    def reindex(self, document_id: int) -> KnowledgeDocument:
        document = self.require_document(document_id)
        path = Path(document.stored_path)
        if not path.exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="原始文件不存在，无法重新索引")
        content = path.read_bytes()
        try:
            text = extract_text(document.original_filename, content)
            chunks = split_text(text)
            delete_document_vectors(document.id)
            add_chunks(
                document_id=document.id,
                chunks=chunks,
                metadata={
                    "source_title": document.source_title,
                    "source_type": document.source_type,
                    "course_id": document.course_id,
                    "chapter_id": document.chapter_id if document.chapter_id is not None else -1,
                    "knowledge_point": document.knowledge_point or "",
                    "authority_level": "",
                    "effective_date": "",
                    "expired_date": "",
                },
            )
            document.status = "ready"
            document.chunk_count = len(chunks)
        except Exception as exc:
            document.status = "failed"
            self.documents.save(document)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="重新索引失败") from exc
        return self.documents.save(document)

    def search(self, question: str, *, course_id: int, chapter_id: int | None, top_k: int) -> list[RetrievedChunk]:
        if self.courses.get(course_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="课程不存在")
        return retrieve(question, course_id=course_id, chapter_id=chapter_id, top_k=top_k)

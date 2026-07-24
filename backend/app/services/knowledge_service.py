from pathlib import Path
from uuid import uuid4
import logging
import hashlib
from datetime import date, datetime

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.rag.document_loader import SUPPORTED_EXTENSIONS, extract_pages, extract_text
from app.rag.retriever import RetrievedChunk, retrieve
from app.rag.text_splitter import split_pages, split_text
from app.rag.vector_store import add_chunks, add_precise_chunks, delete_document_vectors, resolve_backend_path
from app.repositories.course_repository import ChapterRepository, CourseRepository
from app.repositories.knowledge_repository import KnowledgeRepository
from app.models.knowledge_document import KnowledgeDocument
from app.models.citation import DocumentPage, KnowledgeChunk, TextbookVersion


logger = logging.getLogger(__name__)


class KnowledgeService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.documents = KnowledgeRepository(db)
        self.courses = CourseRepository(db)
        self.chapters = ChapterRepository(db)

    def _mark_index_failed(self, document_id: int) -> None:
        """从失败事务中恢复，并把文档保留为可重试的明确状态。"""
        self.db.rollback()
        try:
            delete_document_vectors(document_id)
        except Exception:
            logger.exception("knowledge_vector_cleanup_failed document_id=%s", document_id)
        document = self.db.get(KnowledgeDocument, document_id)
        if document is not None:
            self.db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id))
            document.status = "failed"
            document.chunk_count = 0
            self.db.commit()

    def ingest(
        self,
        *,
        filename: str,
        content: bytes,
        source_title: str,
        course_id: int | None,
        chapter_id: int | None,
        knowledge_point: str | None,
        version_label: str = "当前版",
        source_role: str = "primary",
        access_policy: str = "full_preview",
        defer_index: bool = False,
        material_type: str = "textbook",
        publisher: str | None = None,
        published_date: date | None = None,
        source_url: str | None = None,
        applicable_scope: str | None = None,
        owner_user_id: int | None = None,
        review_status: str | None = None,
        supersedes_document_id: int | None = None,
        snapshot_time: datetime | None = None,
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
        if material_type not in {"central", "textbook", "local", "unclassified"}:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="资料类型无效")
        if material_type == "textbook" and course_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="教材资料必须绑定所属教材")
        course = self.courses.get(course_id) if course_id is not None else None
        if course_id is not None and course is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="课程不存在")
        if chapter_id is not None:
            chapter = self.chapters.get(chapter_id)
            if chapter is None or chapter.course_id != course_id:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="章节与课程不匹配")
        try:
            pages = extract_pages(filename, content)
            text = "\n\n".join(page.text for page in pages if page.text)
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        precise_chunks = split_pages(pages)
        chunks = [str(item["content"]) for item in precise_chunks]
        if not chunks:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件没有可入库的文本内容")

        upload_dir = resolve_backend_path(settings.knowledge_upload_directory)
        upload_dir.mkdir(parents=True, exist_ok=True)
        stored_path = upload_dir / f"{uuid4().hex}{suffix}"
        stored_path.write_bytes(content)
        textbook_version = None
        if material_type == "textbook" and course_id is not None:
            textbook_version = self.db.scalar(select(TextbookVersion).where(
                TextbookVersion.course_id == course_id, TextbookVersion.version_label == version_label
            ))
            if textbook_version is None:
                has_current_version = self.db.scalar(select(func.count()).select_from(TextbookVersion).where(
                    TextbookVersion.course_id == course_id,
                    TextbookVersion.is_current.is_(True),
                )) > 0
                publish_text_version = suffix != ".pdf" and not has_current_version
                textbook_version = TextbookVersion(course_id=course_id, version_label=version_label,
                                                   status="published" if publish_text_version else "draft",
                                                   is_current=publish_text_version)
                self.db.add(textbook_version); self.db.commit(); self.db.refresh(textbook_version)
        digest = hashlib.sha256(content).hexdigest()
        document = self.documents.create(
            textbook_version_id=textbook_version.id if textbook_version else None,
            source_title=source_title.strip(),
            source_type=suffix.lstrip("."),
            original_filename=Path(filename).name,
            stored_path=str(stored_path),
            course_id=course_id,
            chapter_id=chapter_id,
            knowledge_point=knowledge_point.strip() if knowledge_point else None,
            vector_collection=settings.rag_collection_name,
            source_role=source_role,
            material_type=material_type,
            publisher=publisher.strip() if publisher else None,
            published_date=published_date,
            source_url=source_url,
            applicable_scope=applicable_scope.strip() if applicable_scope else None,
            owner_user_id=owner_user_id,
            review_status=review_status or ("published" if material_type == "textbook" else "pending"),
            is_active=True,
            content_hash=digest,
            snapshot_time=snapshot_time,
            version_label=version_label.strip() if version_label else None,
            supersedes_document_id=supersedes_document_id,
            access_policy=access_policy,
            calibration_status="pending" if suffix == ".pdf" and material_type == "textbook" else "calibrated",
            status="processing",
            chunk_count=0,
        )
        document_id = document.id
        try:
            self.db.add_all([DocumentPage(document_id=document.id, pdf_page=page.pdf_page, text=page.text,
                                          width=page.width, height=page.height, text_blocks=[]) for page in pages])
            self.db.commit()
        except Exception as exc:
            logger.exception("knowledge_page_persist_failed document_id=%s", document_id)
            self._mark_index_failed(document_id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="原文保存失败，请稍后重试或联系管理员检查数据库容量",
            ) from exc
        if defer_index:
            return document
        try:
            vector_ids = add_precise_chunks(
                document_id=document.id,
                chunks=precise_chunks,
                metadata={
                    "source_title": document.source_title,
                    "source_type": document.source_type,
                    "course_id": course_id,
                    "chapter_id": chapter_id if chapter_id is not None else -1,
                    "knowledge_point": document.knowledge_point or "",
                    "source_role": document.source_role,
                    "material_type": document.material_type,
                    "publisher": document.publisher or "",
                    "published_date": document.published_date.isoformat() if document.published_date else "",
                    "source_url": document.source_url or "",
                    "authority_level": "",
                    "effective_date": "",
                    "expired_date": "",
                },
            )
            index_version = f"{settings.embedding_model}:{settings.embedding_dimensions}"
            self.db.add_all([
                KnowledgeChunk(
                    document_id=document.id, vector_id=vector_id, chunk_index=index,
                    content=str(chunk["content"]), chapter_id=chapter_id,
                    pdf_page_start=int(chunk["pdf_page_start"]), pdf_page_end=int(chunk["pdf_page_end"]),
                    paragraph_index=int(chunk.get("paragraph_index") or 1),
                    start_anchor=str(chunk.get("start_anchor") or "")[:500],
                    end_anchor=str(chunk.get("end_anchor") or "")[-500:], index_version=index_version,
                )
                for index, (chunk, vector_id) in enumerate(zip(precise_chunks, vector_ids))
            ])
            document.status = "ready"
            document.chunk_count = len(chunks)
            saved = self.documents.save(document)
        except Exception as exc:
            logger.exception("knowledge_ingest_failed document_id=%s", document_id)
            self._mark_index_failed(document_id)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="文档向量化失败") from exc
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
        version_id = document.textbook_version_id
        version = self.db.get(TextbookVersion, version_id) if version_id else None
        if document.calibration_status == "published" and version and version.is_current:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="当前正在使用的已发布教材不能直接删除，请先发布替代版本",
            )
        if document.material_type in {"central", "local"} and document.review_status == "published" and document.is_active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="已发布资料不能直接删除，请先归档后再处理",
            )
        delete_document_vectors(document.id)
        path = Path(document.stored_path)
        if path.exists():
            path.unlink()
        self.documents.delete(document)
        if version and not self.db.scalar(select(func.count()).select_from(KnowledgeDocument).where(
            KnowledgeDocument.textbook_version_id == version.id
        )):
            self.db.delete(version)
            self.db.commit()
        logger.info("knowledge_deleted document_id=%s", document_id)

    def reindex(self, document_id: int) -> KnowledgeDocument:
        document = self.require_document(document_id)
        path = Path(document.stored_path)
        if not path.exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="原始文件不存在，无法重新索引")
        content = path.read_bytes()
        try:
            pages = extract_pages(document.original_filename, content)
            chunks = split_pages(pages)
            delete_document_vectors(document.id)
            self.db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document.id))
            self.db.execute(delete(DocumentPage).where(DocumentPage.document_id == document.id))
            self.db.add_all([DocumentPage(document_id=document.id, pdf_page=page.pdf_page, text=page.text,
                                          width=page.width, height=page.height, text_blocks=[]) for page in pages])
            vector_ids = add_precise_chunks(
                document_id=document.id,
                chunks=chunks,
                metadata={
                    "source_title": document.source_title,
                    "source_type": document.source_type,
                    "course_id": document.course_id,
                    "chapter_id": document.chapter_id if document.chapter_id is not None else -1,
                    "knowledge_point": document.knowledge_point or "",
                    "source_role": document.source_role,
                    "material_type": document.material_type,
                    "publisher": document.publisher or "",
                    "published_date": document.published_date.isoformat() if document.published_date else "",
                    "source_url": document.source_url or "",
                    "authority_level": "",
                    "effective_date": "",
                    "expired_date": "",
                },
            )
            index_version = f"{settings.embedding_model}:{settings.embedding_dimensions}"
            self.db.add_all([
                KnowledgeChunk(document_id=document.id, vector_id=vector_id, chunk_index=index,
                               content=str(chunk["content"]), chapter_id=document.chapter_id,
                               pdf_page_start=int(chunk["pdf_page_start"]), pdf_page_end=int(chunk["pdf_page_end"]),
                               paragraph_index=int(chunk.get("paragraph_index") or 1),
                               start_anchor=str(chunk.get("start_anchor") or "")[:500],
                               end_anchor=str(chunk.get("end_anchor") or "")[-500:], index_version=index_version)
                for index, (chunk, vector_id) in enumerate(zip(chunks, vector_ids))
            ])
            document.status = "ready"
            document.chunk_count = len(chunks)
            return self.documents.save(document)
        except Exception as exc:
            logger.exception("knowledge_reindex_failed document_id=%s", document_id)
            self._mark_index_failed(document_id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="重新索引失败，请稍后重试",
            ) from exc

    def search(self, question: str, *, course_id: int, chapter_id: int | None, top_k: int) -> list[RetrievedChunk]:
        if self.courses.get(course_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="课程不存在")
        return retrieve(question, course_id=course_id, chapter_id=chapter_id, top_k=top_k)

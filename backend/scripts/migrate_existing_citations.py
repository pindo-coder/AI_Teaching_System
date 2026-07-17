"""为升级前已经上传的 PDF 补建分页、章节边界和精确引用元数据。"""
from sqlalchemy import select

import app.db.models  # noqa: F401  # 注册全部 ORM 模型及其字符串关系
from app.db.session import SessionLocal
from app.models.chapter import Chapter
from app.models.citation import DocumentOutlineNode, DocumentPage, TextbookVersion
from app.models.knowledge_document import KnowledgeDocument
from app.services.citation_service import CitationService
from app.services.knowledge_service import KnowledgeService


def migrate() -> None:
    with SessionLocal() as db:
        documents = db.scalars(select(KnowledgeDocument).where(
            KnowledgeDocument.source_type == "pdf"
        ).order_by(KnowledgeDocument.id)).all()
        for document in documents:
            if document.textbook_version_id is None:
                version = db.scalar(select(TextbookVersion).where(
                    TextbookVersion.course_id == document.course_id,
                    TextbookVersion.version_label == "迁移基线版",
                ))
                if version is None:
                    version = TextbookVersion(course_id=document.course_id, version_label="迁移基线版",
                                              status="draft", is_current=False)
                    db.add(version); db.flush()
                document.textbook_version_id = version.id
                db.commit()
            has_outline = db.scalar(select(DocumentOutlineNode.id).where(
                DocumentOutlineNode.document_id == document.id
            ).limit(1))
            if has_outline:
                print(f"跳过（已有结构）：{document.id} {document.source_title}")
                continue
            has_pages = db.scalar(select(DocumentPage.id).where(
                DocumentPage.document_id == document.id
            ).limit(1))
            if not has_pages:
                KnowledgeService(db).reindex(document.id)
            chapters = db.scalars(select(Chapter).where(
                Chapter.course_id == document.course_id
            ).order_by(Chapter.sort_order, Chapter.id)).all()
            if not chapters:
                print(f"跳过（无专题）：{document.id} {document.source_title}")
                continue
            CitationService(db).auto_calibrate(document.id, list(chapters))
            print(f"已补建，等待人工确认：{document.id} {document.source_title}")


if __name__ == "__main__":
    migrate()

from __future__ import annotations

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models.knowledge_document import KnowledgeDocument
from app.models.citation import TextbookVersion


class KnowledgeRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list(self, *, course_id: int | None = None) -> list[KnowledgeDocument]:
        query = select(KnowledgeDocument).order_by(KnowledgeDocument.created_time.desc())
        if course_id is not None:
            query = query.where(KnowledgeDocument.course_id == course_id)
        return list(self.db.scalars(query).all())

    def list_ready_for_course(self, course_id: int) -> list[KnowledgeDocument]:
        query = select(KnowledgeDocument).outerjoin(
            TextbookVersion, TextbookVersion.id == KnowledgeDocument.textbook_version_id
        ).where(
            KnowledgeDocument.course_id == course_id,
            KnowledgeDocument.status == "ready",
            or_(
                KnowledgeDocument.source_type != "pdf",
                and_(
                    KnowledgeDocument.calibration_status == "published",
                    TextbookVersion.is_current.is_(True),
                ),
            ),
        )
        return list(self.db.scalars(query).all())

    def get(self, document_id: int) -> KnowledgeDocument | None:
        return self.db.get(KnowledgeDocument, document_id)

    def create(self, **values: object) -> KnowledgeDocument:
        document = KnowledgeDocument(**values)
        self.db.add(document)
        self.db.commit()
        self.db.refresh(document)
        return document

    def save(self, document: KnowledgeDocument) -> KnowledgeDocument:
        self.db.commit()
        self.db.refresh(document)
        return document

    def delete(self, document: KnowledgeDocument) -> None:
        self.db.delete(document)
        self.db.commit()

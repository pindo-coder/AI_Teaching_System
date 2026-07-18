from __future__ import annotations

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models.knowledge_document import KnowledgeDocument
from app.models.citation import TextbookVersion
from app.models.material_scope import DocumentChapterScope, DocumentClassScope, DocumentCourseScope
from app.models.teaching_class import ClassMembership, TeachingClassTeacher
from app.models.user import User


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
            KnowledgeDocument.material_type == "textbook",
            KnowledgeDocument.status == "ready",
            or_(
                KnowledgeDocument.textbook_version_id.is_(None),
                TextbookVersion.is_current.is_(True),
            ),
            or_(
                KnowledgeDocument.source_type != "pdf",
                KnowledgeDocument.calibration_status == "published",
            ),
        )
        return list(self.db.scalars(query).all())

    def eligible_layer_ids(self, *, course_id: int, chapter_id: int | None,
                           user: User | None = None) -> dict[str, list[int]]:
        """先由关系数据库执行权限和作用域过滤，再把安全的文档 ID 交给向量库。"""
        textbook_ids = [item.id for item in self.list_ready_for_course(course_id)]
        candidates = list(self.db.scalars(select(KnowledgeDocument).where(
            KnowledgeDocument.material_type.in_(["central", "local"]),
            KnowledgeDocument.status == "ready",
            KnowledgeDocument.review_status == "published",
            KnowledgeDocument.is_active.is_(True),
        )).all())
        candidate_ids = [item.id for item in candidates]
        if not candidate_ids:
            return {"central": [], "textbook": textbook_ids, "local": []}

        course_scopes: dict[int, set[int]] = {}
        for document_id, scoped_course_id in self.db.execute(select(
            DocumentCourseScope.document_id, DocumentCourseScope.course_id
        ).where(
            DocumentCourseScope.document_id.in_(candidate_ids),
            DocumentCourseScope.confirmed.is_(True),
        )).all():
            course_scopes.setdefault(document_id, set()).add(scoped_course_id)
        chapter_scopes: dict[int, set[int]] = {}
        for document_id, scoped_chapter_id in self.db.execute(select(
            DocumentChapterScope.document_id, DocumentChapterScope.chapter_id
        ).where(
            DocumentChapterScope.document_id.in_(candidate_ids),
            DocumentChapterScope.confirmed.is_(True),
        )).all():
            chapter_scopes.setdefault(document_id, set()).add(scoped_chapter_id)
        class_scopes: dict[int, set[int]] = {}
        for document_id, class_id in self.db.execute(select(
            DocumentClassScope.document_id, DocumentClassScope.teaching_class_id
        ).where(DocumentClassScope.document_id.in_(candidate_ids))).all():
            class_scopes.setdefault(document_id, set()).add(class_id)

        user_class_ids: set[int] = set()
        if user and user.role == "student":
            user_class_ids = set(self.db.scalars(select(ClassMembership.teaching_class_id).where(
                ClassMembership.user_id == user.id,
                ClassMembership.status == "active",
            )).all())
        elif user and user.role == "teacher":
            user_class_ids = set(self.db.scalars(select(TeachingClassTeacher.teaching_class_id).where(
                TeachingClassTeacher.user_id == user.id
            )).all())

        output: dict[str, list[int]] = {"central": [], "textbook": textbook_ids, "local": []}
        for document in candidates:
            scoped_courses = course_scopes.get(document.id, set())
            if course_id not in scoped_courses:
                continue
            scoped_chapters = chapter_scopes.get(document.id, set())
            if scoped_chapters and (chapter_id is None or chapter_id not in scoped_chapters):
                continue
            if document.material_type == "local":
                scoped_classes = class_scopes.get(document.id, set())
                if scoped_classes and not (user and user.role == "admin") and not (scoped_classes & user_class_ids):
                    continue
            output[document.material_type].append(document.id)
        return output

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

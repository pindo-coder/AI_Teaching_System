from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from html.parser import HTMLParser
import hashlib
import ipaddress
from pathlib import Path
import socket
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.chapter import Chapter
from app.models.citation import DocumentPage, KnowledgeChunk, TextbookVersion
from app.models.course import Course
from app.models.knowledge_document import KnowledgeDocument
from app.models.material_scope import (
    DocumentChapterScope, DocumentClassScope, DocumentCourseScope, DocumentKnowledgeTag,
)
from app.models.teaching_class import ClassMembership, TeachingClassTeacher
from app.models.user import User
from app.schemas.knowledge import KnowledgeDocumentRead, MaterialSuggestion
from app.services.knowledge_service import KnowledgeService


class _ArticleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._ignored = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._ignored += 1
        if tag in {"p", "article", "section", "h1", "h2", "h3", "li", "br"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._ignored:
            self._ignored -= 1
        if tag in {"p", "article", "section", "h1", "h2", "h3", "li"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignored and data.strip():
            self.parts.append(data.strip())

    def text(self) -> str:
        lines = [" ".join(line.split()) for line in " ".join(self.parts).splitlines()]
        return "\n".join(line for line in lines if line).strip()


def _assert_public_https(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="中央材料网址必须是公开可访问的 HTTPS 地址")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443)}
    except OSError as exc:
        raise HTTPException(status_code=400, detail="中央材料网址无法解析") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise HTTPException(status_code=400, detail="中央材料网址不能指向本机或内网地址")


def _default_fetch(url: str) -> tuple[str, str]:
    _assert_public_https(url)
    limit = settings.max_upload_size_mb * 1024 * 1024
    headers = {"User-Agent": "AI-Teaching-Material-Archive/1.0"}
    with httpx.Client(timeout=25, follow_redirects=True, headers=headers) as client:
        with client.stream("GET", url) as response:
            if response.status_code >= 400:
                raise HTTPException(status_code=400, detail=f"原文网址访问失败（HTTP {response.status_code}）")
            _assert_public_https(str(response.url))
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > limit:
                    raise HTTPException(status_code=413, detail="网页正文超过系统允许的资料大小")
                chunks.append(chunk)
            charset = response.encoding or "utf-8"
            raw = b"".join(chunks).decode(charset, errors="replace")
            content_type = response.headers.get("content-type", "").lower()
    if "html" in content_type or "<html" in raw[:1000].lower():
        parser = _ArticleTextParser()
        parser.feed(raw)
        text = parser.text()
    else:
        text = raw.strip()
    if len(text) < 80:
        raise HTTPException(status_code=400, detail="未能从网页提取有效正文，请改为上传原始文件")
    return text, str(response.url)


class MaterialCenterService:
    def __init__(self, db: Session, fetcher: Callable[[str], tuple[str, str]] | None = None) -> None:
        self.db = db
        self.knowledge = KnowledgeService(db)
        self.fetcher = fetcher or _default_fetch

    @staticmethod
    def _require_type_permission(user: User, material_type: str) -> None:
        if material_type == "central" and user.role != "admin":
            raise HTTPException(status_code=403, detail="只有管理员可以导入中央材料")
        if material_type == "local" and user.role not in {"teacher", "admin"}:
            raise HTTPException(status_code=403, detail="当前账号不能导入地方材料")
        if material_type not in {"central", "local"}:
            raise HTTPException(status_code=400, detail="该入口仅用于中央材料和地方材料")

    def _manageable_class_ids(self, user: User) -> set[int]:
        if user.role == "admin":
            from app.models.teaching_class import TeachingClass
            return set(self.db.scalars(select(TeachingClass.id)).all())
        return set(self.db.scalars(select(TeachingClassTeacher.teaching_class_id).where(
            TeachingClassTeacher.user_id == user.id
        )).all())

    def ensure_document_access(self, document: KnowledgeDocument, user: User) -> None:
        """保护原文与分页接口，避免通过猜测 ID 越过资料发布和教学班边界。"""
        if user.role == "admin" or document.material_type == "textbook":
            return
        if document.material_type == "central":
            if document.review_status in {"published", "archived"}:
                return
            raise HTTPException(status_code=403, detail="中央材料尚未发布")
        if document.material_type != "local":
            raise HTTPException(status_code=403, detail="该资料尚未完成分类")
        if document.owner_user_id == user.id:
            return
        if document.review_status not in {"published", "archived"}:
            raise HTTPException(status_code=403, detail="地方材料尚未发布")
        scoped_classes = set(self.db.scalars(select(DocumentClassScope.teaching_class_id).where(
            DocumentClassScope.document_id == document.id
        )).all())
        if not scoped_classes:
            return
        if user.role == "teacher":
            allowed = self._manageable_class_ids(user)
        elif user.role == "student":
            allowed = set(self.db.scalars(select(ClassMembership.teaching_class_id).where(
                ClassMembership.user_id == user.id,
                ClassMembership.status == "active",
            )).all())
        else:
            allowed = set()
        if not scoped_classes.intersection(allowed):
            raise HTTPException(status_code=403, detail="该地方材料不属于当前用户的教学班")

    def _validate_scopes(self, user: User, material_type: str, course_ids: list[int],
                         chapter_ids: list[int], class_ids: list[int]) -> tuple[list[int], list[int], list[int]]:
        courses = set(self.db.scalars(select(Course.id).where(Course.id.in_(set(course_ids)))).all()) if course_ids else set()
        if courses != set(course_ids):
            raise HTTPException(status_code=400, detail="包含不存在的教材")
        chapters = list(self.db.scalars(select(Chapter).where(Chapter.id.in_(set(chapter_ids)))).all()) if chapter_ids else []
        if {item.id for item in chapters} != set(chapter_ids):
            raise HTTPException(status_code=400, detail="包含不存在的专题")
        courses.update(item.course_id for item in chapters)
        if class_ids:
            manageable = self._manageable_class_ids(user)
            if not set(class_ids).issubset(manageable):
                raise HTTPException(status_code=403, detail="无权将资料关联到所选教学班")
        if material_type == "central" and class_ids:
            raise HTTPException(status_code=400, detail="中央材料不直接绑定教学班")
        if material_type == "local" and not courses:
            raise HTTPException(status_code=400, detail="地方材料至少需要关联一本教材或一个专题")
        if material_type == "local" and user.role == "teacher" and not class_ids:
            raise HTTPException(status_code=400, detail="教师上传的地方材料必须选择自己的教学班")
        return sorted(courses), sorted(set(chapter_ids)), sorted(set(class_ids))

    def replace_scopes(self, document: KnowledgeDocument, user: User, *, course_ids: list[int],
                       chapter_ids: list[int], class_ids: list[int], knowledge_tags: list[str],
                       confirmed: bool = True) -> KnowledgeDocument:
        if user.role != "admin" and document.owner_user_id != user.id:
            raise HTTPException(status_code=403, detail="无权修改该资料的适用范围")
        course_ids, chapter_ids, class_ids = self._validate_scopes(
            user, document.material_type, course_ids, chapter_ids, class_ids
        )
        self.db.execute(delete(DocumentCourseScope).where(DocumentCourseScope.document_id == document.id))
        self.db.execute(delete(DocumentChapterScope).where(DocumentChapterScope.document_id == document.id))
        self.db.execute(delete(DocumentClassScope).where(DocumentClassScope.document_id == document.id))
        self.db.execute(delete(DocumentKnowledgeTag).where(DocumentKnowledgeTag.document_id == document.id))
        now = datetime.utcnow() if confirmed else None
        self.db.add_all([
            DocumentCourseScope(document_id=document.id, course_id=course_id, confirmed=confirmed,
                                confirmed_by=user.id if confirmed else None, confirmed_time=now)
            for course_id in course_ids
        ])
        self.db.add_all([
            DocumentChapterScope(document_id=document.id, chapter_id=chapter_id, confirmed=confirmed,
                                 confirmed_by=user.id if confirmed else None, confirmed_time=now)
            for chapter_id in chapter_ids
        ])
        self.db.add_all([
            DocumentClassScope(document_id=document.id, teaching_class_id=class_id)
            for class_id in class_ids
        ])
        clean_tags = sorted({item.strip()[:120] for item in knowledge_tags if item.strip()})
        self.db.add_all([DocumentKnowledgeTag(document_id=document.id, tag=tag) for tag in clean_tags])
        if course_ids:
            document.course_id = course_ids[0]
        document.chapter_id = chapter_ids[0] if len(chapter_ids) == 1 else None
        document.knowledge_point = "、".join(clean_tags)[:255] or None
        self.db.commit()
        self.db.refresh(document)
        return document

    def ingest_file(self, user: User, *, material_type: str, filename: str, content: bytes,
                    source_title: str, publisher: str, published_date: date,
                    applicable_scope: str | None, version_label: str | None,
                    supersedes_document_id: int | None, access_policy: str,
                    course_ids: list[int], chapter_ids: list[int], class_ids: list[int],
                    knowledge_tags: list[str], source_url: str | None = None,
                    snapshot_time: datetime | None = None) -> KnowledgeDocument:
        self._require_type_permission(user, material_type)
        course_ids, chapter_ids, class_ids = self._validate_scopes(
            user, material_type, course_ids, chapter_ids, class_ids
        )
        digest = hashlib.sha256(content).hexdigest()
        duplicate = self.db.scalar(select(KnowledgeDocument).where(
            KnowledgeDocument.content_hash == digest,
            KnowledgeDocument.material_type == material_type,
            KnowledgeDocument.is_active.is_(True),
        ))
        if duplicate:
            raise HTTPException(status_code=409, detail=f"相同内容已入库：{duplicate.source_title}")
        if supersedes_document_id:
            previous = self.knowledge.require_document(supersedes_document_id)
            if previous.material_type != material_type:
                raise HTTPException(status_code=400, detail="新旧版本的资料类型不一致")
        review_status = "pending" if material_type == "central" else "published"
        document = self.knowledge.ingest(
            filename=filename, content=content, source_title=source_title,
            course_id=course_ids[0] if course_ids else None,
            chapter_id=chapter_ids[0] if len(chapter_ids) == 1 else None,
            knowledge_point="、".join(knowledge_tags)[:255] or None,
            version_label=version_label or "当前版", source_role="supplementary",
            access_policy=access_policy, material_type=material_type, publisher=publisher,
            published_date=published_date, applicable_scope=applicable_scope,
            source_url=source_url, snapshot_time=snapshot_time,
            owner_user_id=user.id, review_status=review_status,
            supersedes_document_id=supersedes_document_id,
        )
        self.replace_scopes(
            document, user, course_ids=course_ids, chapter_ids=chapter_ids,
            class_ids=class_ids, knowledge_tags=knowledge_tags,
            confirmed=material_type == "local",
        )
        if material_type == "local":
            document.verified_by = user.id
            document.verified_time = datetime.utcnow()
            self.db.commit(); self.db.refresh(document)
        return document

    def ingest_url(self, user: User, *, source_url: str, source_title: str, publisher: str,
                   published_date: date, applicable_scope: str | None, version_label: str | None,
                   supersedes_document_id: int | None, access_policy: str,
                   course_ids: list[int], chapter_ids: list[int], knowledge_tags: list[str]) -> KnowledgeDocument:
        self._require_type_permission(user, "central")
        text, final_url = self.fetcher(source_url)
        raw_name = (urlparse(final_url).path.rsplit("/", 1)[-1] or "central-material")[:120]
        safe_name = f"{Path(raw_name).stem or 'central-material'}.md"
        document = self.ingest_file(
            user, material_type="central", filename=safe_name,
            content=text.encode("utf-8"), source_title=source_title, publisher=publisher,
            published_date=published_date, applicable_scope=applicable_scope,
            version_label=version_label, supersedes_document_id=supersedes_document_id,
            access_policy=access_policy, course_ids=course_ids, chapter_ids=chapter_ids,
            class_ids=[], knowledge_tags=knowledge_tags, source_url=final_url,
            snapshot_time=datetime.utcnow(),
        )
        # URL 与发布机关仍需管理员在预览后确认，因此保持 pending。
        return document

    def publish(self, document_id: int, user: User) -> KnowledgeDocument:
        document = self.knowledge.require_document(document_id)
        if document.material_type == "central" and user.role != "admin":
            raise HTTPException(status_code=403, detail="只有管理员可以发布中央材料")
        if document.material_type == "local" and user.role != "admin" and document.owner_user_id != user.id:
            raise HTTPException(status_code=403, detail="无权发布该地方材料")
        if document.material_type not in {"central", "local"}:
            raise HTTPException(status_code=400, detail="教材请使用原有教材发布流程")
        if document.status != "ready" or not Path(document.stored_path).exists():
            raise HTTPException(status_code=409, detail="资料原文或向量索引尚未就绪")
        if not document.publisher or not document.published_date:
            raise HTTPException(status_code=400, detail="请先补全来源单位和发布日期")
        course_scope = self.db.scalar(select(DocumentCourseScope).where(
            DocumentCourseScope.document_id == document.id,
            DocumentCourseScope.confirmed.is_(True),
        ))
        class_scope = self.db.scalar(select(DocumentClassScope).where(
            DocumentClassScope.document_id == document.id
        ))
        if document.material_type == "central" and not course_scope:
            raise HTTPException(status_code=400, detail="请先确认中央材料关联的教材或专题")
        if document.material_type == "local" and user.role != "admin" and not class_scope:
            raise HTTPException(status_code=400, detail="教师材料必须限定到自己的教学班")
        digest = hashlib.sha256(Path(document.stored_path).read_bytes()).hexdigest()
        if document.content_hash and digest != document.content_hash:
            raise HTTPException(status_code=409, detail="资料文件校验失败，请重新上传")
        document.content_hash = digest
        document.review_status = "published"
        document.is_active = True
        document.verified_by = user.id
        document.verified_time = datetime.utcnow()
        if document.supersedes_document_id:
            previous = self.db.get(KnowledgeDocument, document.supersedes_document_id)
            if previous and previous.material_type == document.material_type:
                previous.review_status = "archived"
                previous.is_active = False
        self.db.commit(); self.db.refresh(document)
        return document

    def archive(self, document_id: int, user: User) -> KnowledgeDocument:
        document = self.knowledge.require_document(document_id)
        if user.role != "admin" and document.owner_user_id != user.id:
            raise HTTPException(status_code=403, detail="无权归档该资料")
        if document.material_type == "textbook":
            raise HTTPException(status_code=400, detail="教材版本请使用原有版本切换功能")
        document.review_status = "archived"
        document.is_active = False
        self.db.commit(); self.db.refresh(document)
        return document

    def classify(self, document_id: int, user: User, *, material_type: str,
                 publisher: str | None, published_date: date | None,
                 applicable_scope: str | None) -> KnowledgeDocument:
        if user.role != "admin":
            raise HTTPException(status_code=403, detail="只有管理员可以确认历史资料分类")
        document = self.knowledge.require_document(document_id)
        if document.material_type != "unclassified":
            raise HTTPException(status_code=409, detail="该资料已经完成分类")
        document.material_type = material_type
        document.publisher = publisher.strip() if publisher else None
        document.published_date = published_date
        document.applicable_scope = applicable_scope.strip() if applicable_scope else None
        if material_type == "textbook":
            if document.course_id is None:
                raise HTTPException(status_code=400, detail="教材正文必须先绑定所属教材")
            label = document.version_label or f"迁移资料-{document.id}"
            version = self.db.scalar(select(TextbookVersion).where(
                TextbookVersion.course_id == document.course_id,
                TextbookVersion.version_label == label,
            ))
            if version is None:
                version = TextbookVersion(
                    course_id=document.course_id, version_label=label,
                    status="draft", is_current=False,
                )
                self.db.add(version); self.db.flush()
            document.textbook_version_id = version.id
            document.source_role = "primary"
            document.calibration_status = "pending" if document.source_type == "pdf" else "calibrated"
            document.review_status = "published"
        else:
            document.source_role = "supplementary"
            document.textbook_version_id = None
            document.review_status = "pending"
        document.is_active = True
        self.db.commit(); self.db.refresh(document)
        return self.knowledge.reindex(document.id)

    def suggestions(self, document_id: int) -> list[MaterialSuggestion]:
        document = self.knowledge.require_document(document_id)
        chunks = list(self.db.scalars(select(KnowledgeChunk.content).where(
            KnowledgeChunk.document_id == document.id
        ).limit(10)).all())
        if not chunks:
            chunks = list(self.db.scalars(select(DocumentPage.text).where(
                DocumentPage.document_id == document.id
            ).limit(10)).all())
        source = "".join(chunks)[:30000]

        def grams(value: str) -> set[str]:
            compact = "".join(value.split())
            return {compact[index:index + 2] for index in range(max(0, len(compact) - 1))}

        source_grams = grams(source)
        output: list[MaterialSuggestion] = []
        for chapter, course in self.db.execute(
            select(Chapter, Course).join(Course, Course.id == Chapter.course_id)
        ).all():
            target = grams(f"{course.name}{chapter.title}{(chapter.content or '')[:1200]}")
            score = len(source_grams & target) / max(1, min(len(source_grams), len(target)))
            if chapter.title.replace(" ", "") in source.replace(" ", ""):
                score += 0.2
            output.append(MaterialSuggestion(
                course_id=course.id, course_name=course.name, chapter_id=chapter.id,
                chapter_title=chapter.title, score=round(min(score, 1), 4),
            ))
        return sorted(output, key=lambda item: item.score, reverse=True)[:8]

    def _scope_values(self, document_id: int) -> dict[str, list]:
        return {
            "course_ids": list(self.db.scalars(select(DocumentCourseScope.course_id).where(
                DocumentCourseScope.document_id == document_id,
                DocumentCourseScope.confirmed.is_(True),
            )).all()),
            "chapter_ids": list(self.db.scalars(select(DocumentChapterScope.chapter_id).where(
                DocumentChapterScope.document_id == document_id,
                DocumentChapterScope.confirmed.is_(True),
            )).all()),
            "teaching_class_ids": list(self.db.scalars(select(DocumentClassScope.teaching_class_id).where(
                DocumentClassScope.document_id == document_id
            )).all()),
            "knowledge_tags": list(self.db.scalars(select(DocumentKnowledgeTag.tag).where(
                DocumentKnowledgeTag.document_id == document_id
            )).all()),
        }

    def read(self, document: KnowledgeDocument) -> KnowledgeDocumentRead:
        return KnowledgeDocumentRead.model_validate(document).model_copy(
            update=self._scope_values(document.id)
        )

    def list_for_user(self, user: User, *, material_type: str | None = None,
                      review_status: str | None = None) -> list[KnowledgeDocumentRead]:
        query = select(KnowledgeDocument).order_by(KnowledgeDocument.created_time.desc())
        if material_type:
            query = query.where(KnowledgeDocument.material_type == material_type)
        if review_status:
            query = query.where(KnowledgeDocument.review_status == review_status)
        documents = list(self.db.scalars(query).all())
        if user.role == "admin":
            return [self.read(item) for item in documents]
        class_ids = self._manageable_class_ids(user)
        output = []
        for document in documents:
            if document.material_type == "textbook":
                output.append(document)
            elif document.material_type == "central" and document.review_status == "published" and document.is_active:
                output.append(document)
            elif document.material_type == "local":
                scopes = set(self._scope_values(document.id)["teaching_class_ids"])
                if document.owner_user_id == user.id or (
                    document.review_status == "published" and document.is_active and (not scopes or scopes & class_ids)
                ):
                    output.append(document)
        return [self.read(item) for item in output]

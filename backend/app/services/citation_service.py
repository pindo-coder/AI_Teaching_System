import re

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.chapter import Chapter
from app.models.citation import (
    CitationFeedback, DocumentOutlineNode, DocumentPage, KnowledgeChunk, PageNumberRange,
    TextbookVersion,
)
from app.models.knowledge_document import KnowledgeDocument
from app.rag.text_splitter import split_text
from app.rag.vector_store import add_precise_chunks, delete_document_vectors
from app.schemas.knowledge import CitationFeedbackCreate, DocumentCalibrationUpdate
from app.schemas.knowledge import OutlineNodeInput


def _roman(value: int) -> str:
    pairs = ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
             (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"))
    output = ""
    for number, token in pairs:
        while value >= number:
            output += token; value -= number
    return output


def _roman_value(value: str) -> int:
    numbers = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = previous = 0
    for token in reversed(value.strip().upper()):
        current = numbers.get(token, 0)
        if current < previous:
            total -= current
        else:
            total += current; previous = current
    return total or 1


class CitationService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def require_document(self, document_id: int) -> KnowledgeDocument:
        document = self.db.get(KnowledgeDocument, document_id)
        if document is None:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="教材文档不存在")
        return document

    @staticmethod
    def _slice_page(text: str, *, is_start: bool, is_end: bool,
                    start_anchor: str | None, end_anchor: str | None) -> str:
        output = text
        if is_start and start_anchor:
            index = output.find(start_anchor)
            if index >= 0:
                output = output[index:]
        if is_end and end_anchor:
            index = output.find(end_anchor)
            if index >= 0:
                output = output[:index + len(end_anchor)]
        return output.strip()

    def pages(self, document_id: int) -> list[DocumentPage]:
        self.require_document(document_id)
        return list(self.db.scalars(select(DocumentPage).where(
            DocumentPage.document_id == document_id
        ).order_by(DocumentPage.pdf_page)).all())

    def outline(self, document_id: int) -> list[DocumentOutlineNode]:
        self.require_document(document_id)
        return list(self.db.scalars(select(DocumentOutlineNode).where(
            DocumentOutlineNode.document_id == document_id
        ).order_by(DocumentOutlineNode.sort_order, DocumentOutlineNode.id)).all())

    def calibrate(self, document_id: int, payload: DocumentCalibrationUpdate) -> KnowledgeDocument:
        document = self.require_document(document_id)
        pages = {page.pdf_page: page for page in self.pages(document_id)}
        if not pages:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="文档没有可校准的页面文本")
        max_page = max(pages)
        for node in payload.outline:
            if node.pdf_page_end < node.pdf_page_start or node.pdf_page_end > max_page:
                from fastapi import HTTPException
                raise HTTPException(status_code=400, detail=f"“{node.title}”的页码范围无效")

        self.db.execute(delete(PageNumberRange).where(PageNumberRange.document_id == document_id))
        for item in payload.page_number_ranges:
            if item.pdf_page_end < item.pdf_page_start or item.pdf_page_end > max_page:
                from fastapi import HTTPException
                raise HTTPException(status_code=400, detail="印刷页码区段无效")
            self.db.add(PageNumberRange(document_id=document_id, **item.model_dump()))
            if item.printed_start and item.printed_start.isdigit():
                start_value = int(item.printed_start)
            elif item.printed_start and item.numbering_style in {"roman_upper", "roman_lower"}:
                start_value = _roman_value(item.printed_start)
            else:
                start_value = 1
            for pdf_page in range(item.pdf_page_start, item.pdf_page_end + 1):
                offset = pdf_page - item.pdf_page_start
                if item.numbering_style == "none":
                    label = None
                elif item.numbering_style == "arabic":
                    label = str(start_value + offset)
                else:
                    roman = _roman(start_value + offset)
                    label = roman if item.numbering_style == "roman_upper" else roman.lower()
                pages[pdf_page].printed_page_label = label

        self.db.execute(delete(DocumentOutlineNode).where(DocumentOutlineNode.document_id == document_id))
        self.db.flush()
        created: dict[str, DocumentOutlineNode] = {}
        # 先创建父节点，再创建子节点；前端 client_id 使树在尚无数据库 ID 时也能表达关系。
        pending = list(payload.outline)
        while pending:
            progressed = False
            for item in pending[:]:
                if item.parent_client_id and item.parent_client_id not in created:
                    continue
                node = DocumentOutlineNode(
                    document_id=document_id,
                    parent_id=created[item.parent_client_id].id if item.parent_client_id else None,
                    chapter_id=item.chapter_id, node_type=item.node_type, title=item.title.strip(),
                    sort_order=item.sort_order, pdf_page_start=item.pdf_page_start,
                    pdf_page_end=item.pdf_page_end, start_anchor=item.start_anchor,
                    end_anchor=item.end_anchor, retrieval_enabled=item.retrieval_enabled,
                    calibration_status="reviewed",
                )
                self.db.add(node); self.db.flush(); created[item.client_id] = node
                pending.remove(item); progressed = True
            if not progressed:
                from fastapi import HTTPException
                raise HTTPException(status_code=400, detail="章节树包含不存在的父节点或循环关系")

        nodes = list(created.values())
        by_id = {node.id: node for node in nodes}
        children = {node.parent_id for node in nodes if node.parent_id is not None}

        def lineage(node: DocumentOutlineNode) -> list[DocumentOutlineNode]:
            result = [node]
            while result[-1].parent_id:
                result.append(by_id[result[-1].parent_id])
            return list(reversed(result))

        # 章节正文始终由 PDF 原文生成；教学补充说明应存放在独立字段/资料中。
        for node in [item for item in nodes if item.node_type == "chapter" and item.chapter_id]:
            page_texts = [self._slice_page(pages[number].text,
                                           is_start=number == node.pdf_page_start,
                                           is_end=number == node.pdf_page_end,
                                           start_anchor=node.start_anchor, end_anchor=node.end_anchor)
                          for number in range(node.pdf_page_start, node.pdf_page_end + 1)]
            chapter = self.db.get(Chapter, node.chapter_id)
            if chapter and chapter.course_id == document.course_id:
                chapter.title = node.title
                chapter.content = "\n\n".join(text for text in page_texts if text)

        precise_chunks: list[dict[str, object]] = []
        leaf_nodes = [node for node in nodes if node.id not in children and node.retrieval_enabled]
        for node in leaf_nodes:
            path = lineage(node)
            chapter_id = next((item.chapter_id for item in reversed(path) if item.chapter_id), document.chapter_id)
            section_path = " / ".join(item.title for item in path)
            for number in range(node.pdf_page_start, node.pdf_page_end + 1):
                text = self._slice_page(pages[number].text,
                                        is_start=number == node.pdf_page_start,
                                        is_end=number == node.pdf_page_end,
                                        start_anchor=node.start_anchor, end_anchor=node.end_anchor)
                for paragraph_index, chunk in enumerate(split_text(text), start=1):
                    precise_chunks.append({
                        "content": chunk, "pdf_page_start": number, "pdf_page_end": number,
                        "paragraph_index": paragraph_index,
                        "printed_page_start": pages[number].printed_page_label or "",
                        "printed_page_end": pages[number].printed_page_label or "",
                        "section_path": section_path, "start_anchor": chunk[:120], "end_anchor": chunk[-120:],
                        "metadata": {"chapter_id": chapter_id if chapter_id is not None else -1,
                                     "outline_node_id": node.id},
                    })
        if not precise_chunks:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="校准结果没有可用于检索的正文节点")

        delete_document_vectors(document_id)
        self.db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id))
        vector_ids = add_precise_chunks(
            document_id=document_id, chunks=precise_chunks,
            metadata={"source_title": document.source_title, "source_type": document.source_type,
                      "course_id": document.course_id, "chapter_id": document.chapter_id or -1,
                      "knowledge_point": document.knowledge_point or "", "source_role": document.source_role,
                      "material_type": document.material_type, "publisher": document.publisher or "",
                      "published_date": document.published_date.isoformat() if document.published_date else "",
                      "source_url": document.source_url or "",
                      "authority_level": "", "effective_date": "", "expired_date": ""},
        )
        version = f"{settings.embedding_model}:{settings.embedding_dimensions}"
        for index, (chunk, vector_id) in enumerate(zip(precise_chunks, vector_ids)):
            metadata = dict(chunk.get("metadata") or {})
            self.db.add(KnowledgeChunk(
                document_id=document_id, vector_id=vector_id, chunk_index=index,
                content=str(chunk["content"]), chapter_id=metadata.get("chapter_id") if metadata.get("chapter_id") != -1 else None,
                outline_node_id=metadata.get("outline_node_id"), pdf_page_start=int(chunk["pdf_page_start"]),
                pdf_page_end=int(chunk["pdf_page_end"]), paragraph_index=int(chunk.get("paragraph_index") or 1), printed_page_start=str(chunk.get("printed_page_start") or "") or None,
                printed_page_end=str(chunk.get("printed_page_end") or "") or None,
                section_path=str(chunk.get("section_path") or "") or None,
                start_anchor=str(chunk.get("start_anchor") or "")[:500],
                end_anchor=str(chunk.get("end_anchor") or "")[-500:], index_version=version,
            ))
        document.access_policy = payload.access_policy
        document.calibration_status = "calibrated"
        document.status = "ready"
        document.chunk_count = len(precise_chunks)
        if document.textbook_version_id:
            version_row = self.db.get(TextbookVersion, document.textbook_version_id)
            version_row.version_label = payload.version_label
        self.db.commit(); self.db.refresh(document)
        return document

    def auto_calibrate(self, document_id: int, chapters: list[Chapter], version_label: str = "当前版") -> KnowledgeDocument:
        """生成待人工确认的章节草稿；确认前不改专题正文，也不建立向量索引。"""
        document = self.require_document(document_id)
        if document.calibration_status == "published":
            from fastapi import HTTPException
            raise HTTPException(status_code=409, detail="已发布教材不能重新自动拆分，请先上传新版本")
        pages = self.pages(document_id)
        if not pages or not chapters:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="没有可用于自动校准的页面或章节")
        ordered_chapters = sorted(chapters, key=lambda item: (item.sort_order, item.id))
        compact_pages = {page.pdf_page: "".join(page.text.split()) for page in pages}
        toc_pages = [number for number, text in compact_pages.items() if number <= 20 and "目录" in text]
        content_floor = (max(toc_pages) + 1) if toc_pages else 1

        def marker(chapter: Chapter) -> str:
            title = "".join(chapter.title.split())
            if "导论" in title:
                return "导论"
            matched = re.search(r"第[一二三四五六七八九十百]+章", title)
            return matched.group(0) if matched else title

        numbered = [item for item in ordered_chapters if marker(item).startswith("第")]
        learning_pages = [
            page.pdf_page for page in pages
            if page.pdf_page >= content_floor and "学习要点" in compact_pages[page.pdf_page]
        ]
        start_by_chapter: dict[int, int] = {}
        # 思政教材各章首页均有“学习要点”，它比容易出现空格、错字的 OCR 章名更稳定。
        if numbered and len(learning_pages) >= len(numbered):
            for chapter, page_number in zip(numbered, learning_pages):
                start_by_chapter[chapter.id] = page_number

        previous = content_floor
        for chapter in ordered_chapters:
            if chapter.id in start_by_chapter:
                previous = start_by_chapter[chapter.id]
                continue
            token = marker(chapter)
            candidates = []
            for page in pages:
                if page.pdf_page < previous or page.pdf_page < content_floor:
                    continue
                index = compact_pages[page.pdf_page].find(token)
                if index < 0:
                    continue
                chapter_marker_count = len(set(re.findall(
                    r"第[一二三四五六七八九十百]+章", compact_pages[page.pdf_page]
                )))
                # 优先页首标题，并避开一页列出多个章名的目录、总结或附录页。
                candidates.append((chapter_marker_count > 2, index > 100, page.pdf_page))
            if candidates:
                previous = min(candidates)[2]
            start_by_chapter[chapter.id] = previous

        starts = [(start_by_chapter[item.id], item) for item in ordered_chapters]
        max_page = pages[-1].pdf_page
        self.db.execute(delete(DocumentOutlineNode).where(DocumentOutlineNode.document_id == document_id))
        for index, (start_page, chapter) in enumerate(starts):
            next_start = starts[index + 1] if index + 1 < len(starts) else None
            end_page = max(start_page, (next_start[0] - 1) if next_start else max_page)
            self.db.add(DocumentOutlineNode(
                document_id=document_id, chapter_id=chapter.id, node_type="chapter",
                title=chapter.title, sort_order=chapter.sort_order, pdf_page_start=start_page,
                pdf_page_end=end_page, start_anchor=None, end_anchor=None,
                retrieval_enabled=True, calibration_status="auto",
            ))
        document.calibration_status = "pending"
        document.status = "processing"
        document.chunk_count = 0
        self.db.commit(); self.db.refresh(document)
        return document

    def publish(self, document_id: int) -> KnowledgeDocument:
        document = self.require_document(document_id)
        if document.calibration_status != "calibrated":
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="请先完成教材结构校准")
        document.calibration_status = "published"
        if document.textbook_version_id:
            version = self.db.get(TextbookVersion, document.textbook_version_id)
            for previous in self.db.scalars(select(TextbookVersion).where(
                TextbookVersion.course_id == version.course_id,
                TextbookVersion.id != version.id,
            )).all():
                previous.is_current = False
            version.status = "published"; version.is_current = True
        self.db.commit(); self.db.refresh(document)
        return document

    def activate_version(self, version_id: int) -> TextbookVersion:
        version = self.db.get(TextbookVersion, version_id)
        if version is None:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="教材版本不存在")
        documents = list(self.db.scalars(select(KnowledgeDocument).where(
            KnowledgeDocument.textbook_version_id == version.id
        )).all())
        if version.status != "published" or not any(
            item.status == "ready" and item.calibration_status == "published" for item in documents
        ):
            from fastapi import HTTPException
            raise HTTPException(status_code=409, detail="该版本尚未完成校准发布，不能设为当前版本")
        for previous in self.db.scalars(select(TextbookVersion).where(
            TextbookVersion.course_id == version.course_id,
            TextbookVersion.id != version.id,
            TextbookVersion.is_current.is_(True),
        )).all():
            previous.is_current = False
        version.is_current = True
        self.db.commit(); self.db.refresh(version)
        return version

    def feedback(self, user_id: int, payload: CitationFeedbackCreate) -> CitationFeedback:
        record = CitationFeedback(user_id=user_id, **payload.model_dump())
        self.db.add(record); self.db.commit(); self.db.refresh(record)
        return record

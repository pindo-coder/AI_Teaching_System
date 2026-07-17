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
        """按章节标题生成待人工确认的初始结构，同时让章节检索立即具备正确隔离。"""
        pages = self.pages(document_id)
        if not pages or not chapters:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="没有可用于自动校准的页面或章节")
        starts: list[tuple[int, int, Chapter]] = []
        last_page = 1
        for chapter in chapters:
            found_page = last_page; found_index = 0
            compact_title = "".join(chapter.title.split())
            for page in pages[last_page - 1:]:
                compact_text = "".join(page.text.split())
                index = compact_text.find(compact_title)
                if index >= 0:
                    found_page = page.pdf_page
                    # 锚点使用原始标题；若 PDF 插入空格则用该页开头作为保守定位。
                    found_index = page.text.find(chapter.title)
                    break
            starts.append((found_page, found_index, chapter)); last_page = found_page
        outline: list[OutlineNodeInput] = []
        max_page = pages[-1].pdf_page
        page_map = {page.pdf_page: page for page in pages}
        for index, (start_page, start_index, chapter) in enumerate(starts):
            next_start = starts[index + 1] if index + 1 < len(starts) else None
            end_page = next_start[0] if next_start else max_page
            end_anchor = None
            if next_start and next_start[1] <= 0 and end_page > start_page:
                end_page -= 1
            elif next_start and next_start[1] > 0:
                prefix = page_map[end_page].text[:next_start[1]].strip()
                end_anchor = prefix[-160:] or None
            outline.append(OutlineNodeInput(
                client_id=f"chapter-{chapter.id}", chapter_id=chapter.id, node_type="chapter",
                title=chapter.title, sort_order=chapter.sort_order, pdf_page_start=start_page,
                pdf_page_end=max(start_page, end_page), start_anchor=chapter.title if start_index >= 0 else None,
                end_anchor=end_anchor, retrieval_enabled=True,
            ))
        document = self.calibrate(document_id, DocumentCalibrationUpdate(
            version_label=version_label, access_policy="full_preview", page_number_ranges=[], outline=outline
        ))
        document.calibration_status = "pending"
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

    def feedback(self, user_id: int, payload: CitationFeedbackCreate) -> CitationFeedback:
        record = CitationFeedback(user_id=user_id, **payload.model_dump())
        self.db.add(record); self.db.commit(); self.db.refresh(record)
        return record

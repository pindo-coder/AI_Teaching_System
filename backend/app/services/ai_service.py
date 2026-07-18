from collections.abc import Iterator
from typing import Protocol
import logging

from fastapi import HTTPException, status
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from sqlalchemy import case, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.prompts import (
    AI_SYSTEM_PROMPT,
    AI_USER_PROMPT,
    STAGE_INSTRUCTIONS,
    STAGE_LABELS,
    TASK_INSTRUCTIONS,
    TASK_LABELS,
)
from app.repositories.course_repository import ChapterRepository, CourseRepository
from app.repositories.knowledge_repository import KnowledgeRepository
from app.models.citation import DocumentOutlineNode, DocumentPage, TextbookVersion
from app.models.knowledge_document import KnowledgeDocument
from app.models.user import User
from app.rag.retriever import retrieve_layered
from app.schemas.ai import AiAssistData, AiAssistRequest, AiSource


logger = logging.getLogger(__name__)


def source_position(metadata: dict[str, object]) -> str:
    label = metadata.get("position_label")
    if label:
        return str(label)
    index = metadata.get("chunk_index")
    count = metadata.get("chunk_count")
    if isinstance(index, int) and isinstance(count, int):
        return f"教材文本第 {index + 1} / {count} 段"
    return "教材文本片段"


class AiGenerator(Protocol):
    def generate(self, variables: dict[str, str]) -> str: ...
    def stream(self, variables: dict[str, str]) -> Iterator[str]: ...


class LangChainGenerator:
    """使用 OpenAI 兼容 API；通过配置即可替换具体模型供应商。"""

    def __init__(self) -> None:
        if not settings.llm_api_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="尚未配置 LLM_API_KEY，请启用 AI_MOCK_MODE 或配置模型服务",
            )
        prompt = ChatPromptTemplate.from_messages(
            [("system", AI_SYSTEM_PROMPT), ("human", AI_USER_PROMPT)]
        )
        model = ChatOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            timeout=settings.llm_timeout_seconds,
        )
        self.chain = prompt | model | StrOutputParser()

    def generate(self, variables: dict[str, str]) -> str:
        try:
            return self.chain.invoke(variables)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="大模型服务暂时不可用，请稍后重试",
            ) from exc

    def stream(self, variables: dict[str, str]) -> Iterator[str]:
        try:
            yield from self.chain.stream(variables)
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="大模型服务暂时不可用，请稍后重试") from exc


class MockGenerator:
    """供本地开发和自动化测试使用，不调用外部模型。"""

    def generate(self, variables: dict[str, str]) -> str:
        task = variables["task_type_label"]
        stage = variables["learning_stage_label"]
        title = variables["chapter_title"]
        content = variables["chapter_content"].strip()
        excerpt = content[:800] + ("……" if len(content) > 800 else "")
        if task == "生成预习问题":
            return (
                f"【{stage}·{task}】\n\n"
                f"以下问题均围绕当前专题《{title}》设计：\n\n"
                "1. 本专题试图回答的核心问题是什么？\n提问意图：明确章节主旨。\n\n"
                "2. 本专题涉及哪些核心概念，它们之间有什么关系？\n提问意图：梳理概念结构。\n\n"
                "3. 本专题的主要观点和论证依据是什么？\n提问意图：理解教材论述。\n\n"
                "4. 本专题观点可以联系哪些现实问题？\n提问意图：建立理论与实践联系。\n\n"
                "5. 学习本专题后还可以进一步思考什么问题？\n提问意图：形成拓展思考。"
            )
        if task == "章节重点总结":
            return (
                f"【{stage}·{task}】\n\n本章主旨：围绕“{title}”理解教材核心论述。\n\n"
                f"核心内容：\n{excerpt}\n\n"
                "学习提示：建议结合章节原文，按照“概念—观点—逻辑—现实意义”的顺序复习。"
            )
        return (
            f"【{stage}·{task}】\n\n"
            f"本次学习围绕“{title}”展开。根据当前章节资料，可重点关注以下内容：\n\n"
            f"{excerpt}\n\n"
            "以上内容由本地模拟模式生成，用于验证业务流程；接入模型 API 后将生成更完整的教材化回答。"
        )

    def stream(self, variables: dict[str, str]) -> Iterator[str]:
        answer = self.generate(variables)
        for index in range(0, len(answer), 24):
            yield answer[index : index + 24]


class AiService:
    def __init__(self, db: Session, generator: AiGenerator | None = None,
                 user: User | None = None) -> None:
        self.db = db
        self.courses = CourseRepository(db)
        self.chapters = ChapterRepository(db)
        self.documents = KnowledgeRepository(db)
        self.user = user
        self.generator = generator or (MockGenerator() if settings.ai_mock_mode else LangChainGenerator())

    def _chapter_direct_source(self, *, course_id: int, chapter_id: int, excerpt: str) -> AiSource | None:
        """为专题正文补回其教材 PDF 定位，使非 RAG 回答同样可核对原页。"""
        row = self.db.execute(
            select(KnowledgeDocument, DocumentOutlineNode)
            .join(DocumentOutlineNode, DocumentOutlineNode.document_id == KnowledgeDocument.id)
            .outerjoin(TextbookVersion, TextbookVersion.id == KnowledgeDocument.textbook_version_id)
            .where(
                KnowledgeDocument.course_id == course_id,
                KnowledgeDocument.material_type == "textbook",
                KnowledgeDocument.source_type == "pdf",
                KnowledgeDocument.status == "ready",
                KnowledgeDocument.calibration_status == "published",
                or_(KnowledgeDocument.textbook_version_id.is_(None), TextbookVersion.is_current.is_(True)),
                DocumentOutlineNode.chapter_id == chapter_id,
            )
            .order_by(
                case((KnowledgeDocument.source_role == "primary", 0), else_=1),
                case((KnowledgeDocument.calibration_status == "published", 0), else_=1),
                KnowledgeDocument.id,
            )
        ).first()
        if row is None:
            return None
        document, outline = row
        page_rows = self.db.scalars(
            select(DocumentPage).where(
                DocumentPage.document_id == document.id,
                DocumentPage.pdf_page.in_([outline.pdf_page_start, outline.pdf_page_end]),
            )
        ).all()
        labels = {item.pdf_page: item.printed_page_label for item in page_rows}
        printed_start = labels.get(outline.pdf_page_start)
        printed_end = labels.get(outline.pdf_page_end)
        if printed_start:
            position = f"教材第 {printed_start}"
            if printed_end and printed_end != printed_start:
                position += f"—{printed_end}"
            position += " 页"
        else:
            position = f"PDF 第 {outline.pdf_page_start}"
            if outline.pdf_page_end != outline.pdf_page_start:
                position += f"—{outline.pdf_page_end}"
            position += " 页（印刷页码待校准）"
        return AiSource(
            source_type="pdf",
            source_title=document.source_title,
            course_id=course_id,
            chapter_id=chapter_id,
            excerpt=excerpt[:180] + ("……" if len(excerpt) > 180 else ""),
            position=position,
            document_id=document.id,
            section_path=outline.title,
            pdf_page_start=outline.pdf_page_start,
            pdf_page_end=outline.pdf_page_end,
            printed_page_start=printed_start,
            printed_page_end=printed_end,
            evidence_type="教材直接依据",
            material_type="textbook",
        )

    def _validated_sources(self, sources: list[AiSource]) -> list[AiSource]:
        """引用卡片只使用数据库中仍然存在的资料与页码，拒绝过期向量元数据。"""
        output: list[AiSource] = []
        seen: set[tuple[int | None, str | None, int | None]] = set()
        evidence_labels = {"central": "中央材料依据", "textbook": "教材直接依据", "local": "地方材料依据"}
        for source in sources:
            if source.document_id is not None:
                document = self.db.get(KnowledgeDocument, source.document_id)
                if document is None or document.status != "ready":
                    continue
                source.source_title = document.source_title
                source.material_type = document.material_type
                source.publisher = document.publisher
                source.published_date = document.published_date.isoformat() if document.published_date else None
                source.source_url = document.source_url
                source.evidence_type = evidence_labels.get(document.material_type, "资料依据")
                if source.pdf_page_start is not None:
                    page_exists = self.db.scalar(select(DocumentPage.id).where(
                        DocumentPage.document_id == document.id,
                        DocumentPage.pdf_page == source.pdf_page_start,
                    ))
                    if page_exists is None:
                        source.pdf_page_start = None
                        source.pdf_page_end = None
                        source.printed_page_start = None
                        source.printed_page_end = None
            key = (source.document_id, source.vector_id, source.pdf_page_start)
            if key in seen:
                continue
            seen.add(key)
            output.append(source)
        return output

    def _prepare(self, payload: AiAssistRequest) -> tuple[dict[str, str], list[AiSource], int] | AiAssistData:
        course = self.courses.get(payload.course_id)
        chapter = self.chapters.get(payload.chapter_id)
        if course is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="课程不存在")
        if chapter is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="章节不存在")
        if chapter.course_id != course.id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="章节与课程不匹配")
        layer_document_ids = self.documents.eligible_layer_ids(
            course_id=course.id, chapter_id=chapter.id, user=self.user
        )
        # 导入教材自动生成的专题正文是当前章节的首要依据，不能在章节检索
        # 不到时回退到整本教材的 Top-K，否则容易把导论内容带入其他章节。
        chapter_content = (chapter.content or "").strip()
        retrieved_chunks = []
        if any(layer_document_ids.values()):
            retrieved_chunks = retrieve_layered(
                f"{chapter.title} {payload.question}", layer_document_ids=layer_document_ids,
                chapter_id=chapter.id, top_k=6,
            )
        if not chapter_content and any(layer_document_ids.values()) and not retrieved_chunks:
            return AiAssistData(
                answer="当前专题没有可用的教材原文或知识库片段，暂时无法生成有依据的内容。",
                grounded=False,
                model="none",
            )

        material_labels = {"central": "中央材料", "textbook": "教材正文", "local": "地方材料"}
        content_parts = [
            f"[资料 {index + 1}｜{material_labels.get(str(item.metadata.get('material_type')), '资料')}｜{item.metadata.get('section_path') or item.metadata.get('source_title', '未命名资料')}｜{item.metadata.get('position_label', '位置待校准')}]\n{item.content}"
            for index, item in enumerate(retrieved_chunks)
        ]
        has_textbook_chunk = any(str(item.metadata.get("material_type")) == "textbook" for item in retrieved_chunks)
        if chapter_content and not has_textbook_chunk:
            content_parts.append(
                f"[资料 {len(content_parts) + 1}｜教材正文｜当前专题正文｜专题内容]\n{chapter_content}"
            )
        content = "\n\n".join(content_parts) if content_parts else chapter_content
        if not content:
            return AiAssistData(
                answer="当前章节尚未录入课程资料，无法生成有依据的回答。请联系教师完善章节内容。",
                grounded=False,
                model="none",
            )

        variables = {
            "course_name": course.name,
            "chapter_title": chapter.title,
            "learning_stage_label": STAGE_LABELS[payload.learning_stage],
            "task_type_label": TASK_LABELS[payload.task_type],
            "chapter_content": content,
            "question": payload.question,
            "task_instructions": TASK_INSTRUCTIONS[TASK_LABELS[payload.task_type]],
            "stage_instructions": STAGE_INSTRUCTIONS[STAGE_LABELS[payload.learning_stage]],
        }
        direct_source = self._chapter_direct_source(
            course_id=course.id, chapter_id=chapter.id, excerpt=chapter_content
        ) if not has_textbook_chunk else None
        sources = [
                AiSource(
                    source_type=str(item.metadata.get("source_type", "document")),
                    source_title=str(item.metadata.get("source_title", "未命名资料")),
                    course_id=course.id,
                    chapter_id=chapter.id,
                    excerpt=item.content[:180] + ("……" if len(item.content) > 180 else ""),
                    position=source_position(item.metadata),
                    document_id=int(item.metadata["document_id"]) if item.metadata.get("document_id") is not None else None,
                    vector_id=str(item.metadata.get("vector_id")) if item.metadata.get("vector_id") else None,
                    section_path=str(item.metadata.get("section_path")) if item.metadata.get("section_path") else None,
                    pdf_page_start=int(item.metadata["pdf_page_start"]) if item.metadata.get("pdf_page_start") is not None else None,
                    pdf_page_end=int(item.metadata["pdf_page_end"]) if item.metadata.get("pdf_page_end") is not None else None,
                    paragraph_index=int(item.metadata["paragraph_index"]) if item.metadata.get("paragraph_index") is not None else None,
                    printed_page_start=str(item.metadata.get("printed_page_start")) if item.metadata.get("printed_page_start") else None,
                    printed_page_end=str(item.metadata.get("printed_page_end")) if item.metadata.get("printed_page_end") else None,
                    evidence_type="教材直接依据" if str(item.metadata.get("source_role", "primary")) == "primary" else "补充资料依据",
                    material_type=str(item.metadata.get("material_type", "textbook")),
                    publisher=str(item.metadata.get("publisher")) if item.metadata.get("publisher") else None,
                    published_date=str(item.metadata.get("published_date")) if item.metadata.get("published_date") else None,
                    source_url=str(item.metadata.get("source_url")) if item.metadata.get("source_url") else None,
                )
                for item in retrieved_chunks
            ]
        evidence_labels = {"central": "中央材料依据", "textbook": "教材直接依据", "local": "地方材料依据"}
        for source in sources:
            source.evidence_type = evidence_labels.get(source.material_type, "资料依据")
        if direct_source:
            sources.append(direct_source)
        if not sources:
            sources = [
                AiSource(
                    source_type="chapter",
                    source_title=f"{course.name} · {chapter.title}",
                    course_id=course.id,
                    chapter_id=chapter.id,
                    excerpt=content[:180] + ("……" if len(content) > 180 else ""),
                    position="当前专题正文",
                    material_type="textbook",
                )
            ]
        return variables, self._validated_sources(sources), len(retrieved_chunks)

    def assist(self, payload: AiAssistRequest) -> AiAssistData:
        prepared = self._prepare(payload)
        if isinstance(prepared, AiAssistData):
            return prepared
        variables, sources, rag_chunks = prepared
        answer = self.generator.generate(variables)
        logger.info("ai_assist chapter_id=%s stage=%s task=%s rag_chunks=%s", payload.chapter_id, payload.learning_stage, payload.task_type, rag_chunks)
        return AiAssistData(answer=answer, grounded=True, model="mock" if settings.ai_mock_mode else settings.llm_model, sources=sources)

    def stream(self, payload: AiAssistRequest) -> tuple[Iterator[str], list[AiSource], bool, str]:
        prepared = self._prepare(payload)
        if isinstance(prepared, AiAssistData):
            return iter([prepared.answer]), prepared.sources, prepared.grounded, prepared.model
        variables, sources, _ = prepared
        return self.generator.stream(variables), sources, True, "mock" if settings.ai_mock_mode else settings.llm_model

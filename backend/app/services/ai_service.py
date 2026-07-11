from typing import Protocol
import logging

from fastapi import HTTPException, status
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.prompts import AI_SYSTEM_PROMPT, AI_USER_PROMPT, STAGE_LABELS, TASK_LABELS
from app.repositories.course_repository import ChapterRepository, CourseRepository
from app.repositories.knowledge_repository import KnowledgeRepository
from app.rag.retriever import retrieve
from app.schemas.ai import AiAssistData, AiAssistRequest, AiSource


logger = logging.getLogger(__name__)


class AiGenerator(Protocol):
    def generate(self, variables: dict[str, str]) -> str: ...


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


class MockGenerator:
    """供本地开发和自动化测试使用，不调用外部模型。"""

    def generate(self, variables: dict[str, str]) -> str:
        task = variables["task_type_label"]
        stage = variables["learning_stage_label"]
        title = variables["chapter_title"]
        content = variables["chapter_content"].strip()
        excerpt = content[:240] + ("……" if len(content) > 240 else "")
        return (
            f"【{stage}·{task}】\n\n"
            f"本次学习围绕“{title}”展开。根据当前章节资料，可重点关注以下内容：\n\n"
            f"{excerpt}\n\n"
            "以上内容由本地模拟模式生成，用于验证业务流程；接入模型 API 后将生成更完整的教材化回答。"
        )


class AiService:
    def __init__(self, db: Session, generator: AiGenerator | None = None) -> None:
        self.courses = CourseRepository(db)
        self.chapters = ChapterRepository(db)
        self.documents = KnowledgeRepository(db)
        self.generator = generator or (MockGenerator() if settings.ai_mock_mode else LangChainGenerator())

    def assist(self, payload: AiAssistRequest) -> AiAssistData:
        course = self.courses.get(payload.course_id)
        chapter = self.chapters.get(payload.chapter_id)
        if course is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="课程不存在")
        if chapter is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="章节不存在")
        if chapter.course_id != course.id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="章节与课程不匹配")
        ready_documents = self.documents.list_ready_for_course(course.id)
        retrieval_query = f"{chapter.title} {payload.question}"
        retrieved_chunks = (
            retrieve(retrieval_query, course_id=course.id, chapter_id=chapter.id)
            if ready_documents
            else []
        )
        if ready_documents and not retrieved_chunks:
            return AiAssistData(
                answer="当前知识库中没有检索到足以回答该问题的相关资料。建议补充资料或调整问题表述。",
                grounded=False,
                model="none",
            )

        content = (
            "\n\n".join(
                f"[资料 {index + 1}：{item.metadata.get('source_title', '未命名资料')}]\n{item.content}"
                for index, item in enumerate(retrieved_chunks)
            )
            if retrieved_chunks
            else (chapter.content or "").strip()
        )
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
        }
        answer = self.generator.generate(variables)
        logger.info(
            "ai_assist course_id=%s chapter_id=%s stage=%s task=%s rag_chunks=%s model=%s",
            course.id,
            chapter.id,
            payload.learning_stage,
            payload.task_type,
            len(retrieved_chunks),
            "mock" if settings.ai_mock_mode else settings.llm_model,
        )
        sources = (
            [
                AiSource(
                    source_type=str(item.metadata.get("source_type", "document")),
                    source_title=str(item.metadata.get("source_title", "未命名资料")),
                    course_id=course.id,
                    chapter_id=chapter.id,
                    excerpt=item.content[:180] + ("……" if len(item.content) > 180 else ""),
                )
                for item in retrieved_chunks
            ]
            if retrieved_chunks
            else [
                AiSource(
                    source_type="chapter",
                    source_title=f"{course.name} · {chapter.title}",
                    course_id=course.id,
                    chapter_id=chapter.id,
                    excerpt=content[:180] + ("……" if len(content) > 180 else ""),
                )
            ]
        )
        return AiAssistData(
            answer=answer,
            grounded=True,
            model="mock" if settings.ai_mock_mode else settings.llm_model,
            sources=sources,
        )

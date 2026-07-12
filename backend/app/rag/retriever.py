from dataclasses import dataclass

from app.core.config import settings
from app.rag.vector_store import get_vector_store


@dataclass
class RetrievedChunk:
    content: str
    metadata: dict[str, object]
    score: float


def retrieve(
    question: str,
    *,
    course_id: int,
    chapter_id: int | None,
    top_k: int | None = None,
    fallback_to_course: bool = True,
) -> list[RetrievedChunk]:
    store = get_vector_store()
    limit = top_k or settings.rag_top_k
    filters: dict[str, object] = {"course_id": course_id}
    if chapter_id is not None:
        filters = {"$and": [{"course_id": course_id}, {"chapter_id": chapter_id}]}
    results = store.similarity_search_with_relevance_scores(question, k=limit, filter=filters)
    chunks = [
        RetrievedChunk(content=document.page_content, metadata=document.metadata, score=score)
        for document, score in results
        if score >= settings.rag_score_threshold
    ]
    if not chunks and chapter_id is not None and fallback_to_course:
        results = store.similarity_search_with_relevance_scores(
            question, k=limit, filter={"course_id": course_id}
        )
        chunks = [
            RetrievedChunk(content=document.page_content, metadata=document.metadata, score=score)
            for document, score in results
            if score >= settings.rag_score_threshold
        ]
    return chunks

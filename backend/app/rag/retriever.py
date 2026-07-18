from dataclasses import dataclass

from app.core.config import settings
from app.rag.vector_store import get_vector_store


@dataclass
class RetrievedChunk:
    content: str
    metadata: dict[str, object]
    score: float


def retrieve_documents(
    question: str,
    *,
    document_ids: list[int],
    top_k: int,
    material_type: str,
    chapter_id: int | None = None,
    restrict_to_chapter: bool = False,
) -> list[RetrievedChunk]:
    if not document_ids:
        return []
    clauses: list[dict[str, object]] = [{"document_id": {"$in": document_ids}}]
    if restrict_to_chapter and chapter_id is not None:
        clauses.append({"chapter_id": chapter_id})
    filters: dict[str, object] = clauses[0] if len(clauses) == 1 else {"$and": clauses}
    results = get_vector_store().similarity_search_with_relevance_scores(
        question, k=max(top_k, 1), filter=filters
    )
    authority_bonus = {"central": 0.06, "textbook": 0.03, "local": 0.0}.get(material_type, 0.0)
    output = []
    for document, score in results:
        # 权威等级只能在已经通过相关性门槛的材料之间调序，不能把无关中央材料强行加入。
        if score < settings.rag_score_threshold:
            continue
        metadata = {**document.metadata, "material_type": material_type,
                    "semantic_score": score, "authority_bonus": authority_bonus}
        output.append(RetrievedChunk(
            content=document.page_content,
            metadata=metadata,
            score=min(1.0, score + authority_bonus),
        ))
    return sorted(output, key=lambda item: item.score, reverse=True)


def retrieve_layered(
    question: str,
    *,
    layer_document_ids: dict[str, list[int]],
    chapter_id: int | None,
    top_k: int = 6,
) -> list[RetrievedChunk]:
    """中央/教材/地方独立召回，再按 2/至少2/最多1 的证据配额合并。"""
    pools = {
        "central": retrieve_documents(
            question, document_ids=layer_document_ids.get("central", []), top_k=8,
            material_type="central",
        ),
        "textbook": retrieve_documents(
            question, document_ids=layer_document_ids.get("textbook", []), top_k=10,
            material_type="textbook", chapter_id=chapter_id, restrict_to_chapter=True,
        ),
        "local": retrieve_documents(
            question, document_ids=layer_document_ids.get("local", []), top_k=6,
            material_type="local",
        ),
    }
    selected = [*pools["central"][:2], *pools["textbook"][:2], *pools["local"][:1]]
    chosen = {str(item.metadata.get("vector_id") or f"{item.metadata.get('document_id')}:{item.metadata.get('chunk_index')}")
              for item in selected}
    remaining = []
    # 中央材料最多2条、地方材料最多1条；剩余位置由教材正文补足。
    for layer in ("textbook",):
        for item in pools[layer]:
            key = str(item.metadata.get("vector_id") or f"{item.metadata.get('document_id')}:{item.metadata.get('chunk_index')}")
            if key not in chosen:
                remaining.append(item)
    remaining.sort(key=lambda item: item.score, reverse=True)
    selected.extend(remaining[:max(0, top_k - len(selected))])
    return sorted(selected[:top_k], key=lambda item: item.score, reverse=True)


def retrieve(
    question: str,
    *,
    course_id: int,
    chapter_id: int | None,
    top_k: int | None = None,
    fallback_to_course: bool = True,
    document_ids: list[int] | None = None,
) -> list[RetrievedChunk]:
    store = get_vector_store()
    limit = top_k or settings.rag_top_k
    filters: dict[str, object] = {"course_id": course_id}
    if chapter_id is not None:
        filters = {"$and": [{"course_id": course_id}, {"chapter_id": chapter_id}]}
    if document_ids is not None:
        clauses = filters.get("$and", [filters]) if "$and" in filters else [filters]
        filters = {"$and": [*clauses, {"document_id": {"$in": document_ids}}]}
    results = store.similarity_search_with_relevance_scores(question, k=limit, filter=filters)
    chunks = [
        RetrievedChunk(content=document.page_content, metadata=document.metadata, score=score)
        for document, score in results
        if score >= settings.rag_score_threshold
    ]
    # 主教材优先；补充资料只在主教材之后提供佐证，避免同一课程多版本混用。
    chunks.sort(key=lambda item: (0 if str(item.metadata.get("source_role", "primary")) == "primary" else 1, -item.score))
    if not chunks and chapter_id is not None and fallback_to_course:
        results = store.similarity_search_with_relevance_scores(
            question, k=limit, filter={"$and": [{"course_id": course_id}, {"document_id": {"$in": document_ids}}]} if document_ids is not None else {"course_id": course_id}
        )
        chunks = [
            RetrievedChunk(content=document.page_content, metadata=document.metadata, score=score)
            for document, score in results
            if score >= settings.rag_score_threshold
        ]
        chunks.sort(key=lambda item: (0 if str(item.metadata.get("source_role", "primary")) == "primary" else 1, -item.score))
    return chunks

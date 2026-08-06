"""在新 Chroma collection 中安全重建全部精确引用向量，再原子切换。

旧 collection 不会被删除；切换前的活动清单保存为 active_index.previous.json，
回退时必须同时恢复旧清单及其匹配的 Embedding 配置。
"""
from __future__ import annotations

import argparse
from datetime import datetime

from sqlalchemy import select, update

import app.db.models  # noqa: F401  # 注册全部 ORM 模型及其字符串关系
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.citation import IndexVersion, KnowledgeChunk
from app.models.knowledge_document import KnowledgeDocument
from app.rag.embeddings import get_embedding_profile, get_embeddings
from app.rag.vector_store import activate_index, add_precise_chunks, get_vector_store


def collection_name() -> str:
    profile = get_embedding_profile()
    model = profile.model.replace("/", "-").replace(":", "-")
    return f"{settings.rag_collection_name}_{model}_{profile.dimensions}_{profile.fingerprint}_{datetime.now():%Y%m%d%H%M%S}"


def rebuild(*, activate: bool) -> str:
    profile = get_embedding_profile()
    probe = get_embeddings().embed_query("高校思政课教材精确引用向量索引")
    if len(probe) != profile.dimensions:
        raise RuntimeError(f"向量维度不匹配：配置 {profile.dimensions}，接口返回 {len(probe)}")

    target = collection_name()
    with SessionLocal() as db:
        version = IndexVersion(
            collection_name=target, embedding_provider=settings.embedding_provider,
            embedding_model=settings.embedding_model, embedding_dimensions=profile.dimensions,
            chunk_size=settings.text_chunk_size, chunk_overlap=settings.text_chunk_overlap, status="building",
        )
        db.add(version); db.commit(); db.refresh(version)
        try:
            documents = db.scalars(select(KnowledgeDocument).order_by(KnowledgeDocument.id)).all()
            missing_ready_documents: list[str] = []
            rows_by_document: dict[int, list[KnowledgeChunk]] = {}
            for document in documents:
                rows = list(db.scalars(select(KnowledgeChunk).where(
                    KnowledgeChunk.document_id == document.id
                ).order_by(KnowledgeChunk.chunk_index)).all())
                rows_by_document[document.id] = rows
                if document.status == "ready" and document.is_active and not rows:
                    missing_ready_documents.append(f"{document.id}:{document.source_title}")
            if missing_ready_documents:
                preview = "、".join(missing_ready_documents[:10])
                raise RuntimeError(
                    f"发现 {len(missing_ready_documents)} 个应检索但没有分块的文档：{preview}。"
                    "请先修复或重新索引这些文档，禁止激活不完整索引。"
                )

            total = 0
            expected_by_layer: dict[str, int] = {}
            for document in documents:
                rows = rows_by_document[document.id]
                if not rows:
                    continue
                chunks = [{
                    "content": row.content, "pdf_page_start": row.pdf_page_start,
                    "pdf_page_end": row.pdf_page_end, "printed_page_start": row.printed_page_start or "",
                    "paragraph_index": row.paragraph_index or 1,
                    "printed_page_end": row.printed_page_end or "", "section_path": row.section_path or "",
                    "start_anchor": row.start_anchor or "", "end_anchor": row.end_anchor or "",
                    "metadata": {"chapter_id": row.chapter_id or -1, "outline_node_id": row.outline_node_id or -1},
                } for row in rows]
                add_precise_chunks(document_id=document.id, chunks=chunks, collection_name=target, metadata={
                    "source_title": document.source_title, "source_type": document.source_type,
                    "course_id": document.course_id if document.course_id is not None else -1,
                    "chapter_id": document.chapter_id or -1,
                    "knowledge_point": document.knowledge_point or "", "source_role": document.source_role,
                    "material_type": document.material_type,
                    "publisher": document.publisher or "",
                    "published_date": document.published_date.isoformat() if document.published_date else "",
                    "source_url": document.source_url or "",
                    "authority_level": "", "effective_date": "", "expired_date": "",
                })
                total += len(rows)
                expected_by_layer[document.material_type] = expected_by_layer.get(document.material_type, 0) + len(rows)
            store = get_vector_store(target)
            actual = store._collection.count()
            if actual != total:
                raise RuntimeError(f"索引完整性检查失败：预期 {total} 条，实际 {actual} 条")
            for material_type, expected in expected_by_layer.items():
                layer = store._collection.get(where={"material_type": material_type}, include=[])
                layer_actual = len(layer.get("ids") or [])
                if layer_actual != expected:
                    raise RuntimeError(
                        f"{material_type} 层索引不完整：预期 {expected} 条，实际 {layer_actual} 条"
                    )
            version.status = "ready"
            if activate:
                db.execute(update(IndexVersion).values(is_active=False))
                version.is_active = True; version.activated_time = datetime.now()
                db.execute(update(KnowledgeDocument).values(vector_collection=target))
            db.commit()
        except Exception:
            version.status = "failed"; db.commit(); raise

    if activate:
        activate_index(target, profile=profile)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--activate", action="store_true", help="校验通过后原子切换为新索引")
    args = parser.parse_args()
    name = rebuild(activate=args.activate)
    print(f"精确引用索引已构建：{name}")
    print("已激活" if args.activate else "尚未激活；确认后重新执行并加 --activate")

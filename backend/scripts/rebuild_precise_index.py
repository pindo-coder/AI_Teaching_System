"""在新 Chroma collection 中安全重建全部精确引用向量，再原子切换。

旧 collection 不会被删除，若新模型或数据异常可删除 active_index.json 回退。
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime

from sqlalchemy import select, update

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.citation import IndexVersion, KnowledgeChunk
from app.models.knowledge_document import KnowledgeDocument
from app.rag.embeddings import get_embeddings
from app.rag.vector_store import add_precise_chunks, get_vector_store, resolve_backend_path


def collection_name() -> str:
    model = settings.embedding_model.replace("/", "-").replace(":", "-")
    return f"{settings.rag_collection_name}_{model}_{settings.embedding_dimensions}_{datetime.now():%Y%m%d%H%M%S}"


def rebuild(*, activate: bool) -> str:
    probe = get_embeddings().embed_query("高校思政课教材精确引用向量索引")
    if len(probe) != settings.embedding_dimensions:
        raise RuntimeError(f"向量维度不匹配：配置 {settings.embedding_dimensions}，接口返回 {len(probe)}")

    target = collection_name()
    with SessionLocal() as db:
        version = IndexVersion(
            collection_name=target, embedding_provider=settings.embedding_provider,
            embedding_model=settings.embedding_model, embedding_dimensions=settings.embedding_dimensions,
            chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap, status="building",
        )
        db.add(version); db.commit(); db.refresh(version)
        try:
            documents = db.scalars(select(KnowledgeDocument).order_by(KnowledgeDocument.id)).all()
            total = 0
            for document in documents:
                rows = db.scalars(select(KnowledgeChunk).where(
                    KnowledgeChunk.document_id == document.id
                ).order_by(KnowledgeChunk.chunk_index)).all()
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
                    "course_id": document.course_id, "chapter_id": document.chapter_id or -1,
                    "knowledge_point": document.knowledge_point or "", "source_role": document.source_role,
                    "authority_level": "", "effective_date": "", "expired_date": "",
                })
                total += len(rows)
            actual = get_vector_store(target)._collection.count()
            if actual != total:
                raise RuntimeError(f"索引完整性检查失败：预期 {total} 条，实际 {actual} 条")
            version.status = "ready"
            if activate:
                db.execute(update(IndexVersion).values(is_active=False))
                version.is_active = True; version.activated_time = datetime.now()
            db.commit()
        except Exception:
            version.status = "failed"; db.commit(); raise

    if activate:
        directory = resolve_backend_path(settings.chroma_persist_directory)
        target_file = directory / "active_index.json"
        temporary = directory / ".active_index.json.tmp"
        temporary.write_text(json.dumps({"collection_name": target}, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, target_file)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--activate", action="store_true", help="校验通过后原子切换为新索引")
    args = parser.parse_args()
    name = rebuild(activate=args.activate)
    print(f"精确引用索引已构建：{name}")
    print("已激活" if args.activate else "尚未激活；确认后重新执行并加 --activate")

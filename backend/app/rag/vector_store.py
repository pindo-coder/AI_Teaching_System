from pathlib import Path
import json

from langchain_chroma import Chroma
from langchain_core.documents import Document

from app.core.config import BACKEND_DIR, settings
from app.rag.embeddings import get_embeddings


def resolve_backend_path(configured_path: str) -> Path:
    path = Path(configured_path)
    return path if path.is_absolute() else (BACKEND_DIR / path).resolve()


def get_vector_store(collection_name: str | None = None) -> Chroma:
    persist_directory = resolve_backend_path(settings.chroma_persist_directory)
    persist_directory.mkdir(parents=True, exist_ok=True)
    active_file = persist_directory / "active_index.json"
    file_collection = None
    if active_file.exists():
        try:
            file_collection = json.loads(active_file.read_text(encoding="utf-8")).get("collection_name")
        except (OSError, ValueError, TypeError):
            file_collection = None
    return Chroma(
        collection_name=collection_name or settings.rag_active_collection or file_collection or settings.rag_collection_name,
        embedding_function=get_embeddings(),
        persist_directory=str(persist_directory),
    )


def get_study_note_vector_store() -> Chroma:
    """个人笔记与教材库分集合存放，避免检索结果相互污染。"""
    persist_directory = resolve_backend_path(settings.chroma_persist_directory)
    persist_directory.mkdir(parents=True, exist_ok=True)
    return Chroma(
        collection_name=f"{settings.rag_collection_name}_study_notes",
        embedding_function=get_embeddings(),
        persist_directory=str(persist_directory),
    )


def add_chunks(*, document_id: int, chunks: list[str], metadata: dict[str, str | int]) -> None:
    documents = [
        Document(
            page_content=chunk,
            metadata={
                **metadata,
                "document_id": document_id,
                "chunk_index": index,
                "chunk_count": len(chunks),
                "position_label": f"教材文本第 {index + 1} / {len(chunks)} 段",
            },
        )
        for index, chunk in enumerate(chunks)
    ]
    ids = [f"document-{document_id}-chunk-{index}" for index in range(len(chunks))]
    get_vector_store().add_documents(documents, ids=ids)


def add_precise_chunks(*, document_id: int, chunks: list[dict[str, object]],
                       metadata: dict[str, str | int], collection_name: str | None = None) -> list[str]:
    ids = [f"document-{document_id}-chunk-{index}" for index in range(len(chunks))]
    documents = []
    for index, chunk in enumerate(chunks):
        pdf_start = int(chunk["pdf_page_start"])
        pdf_end = int(chunk.get("pdf_page_end", pdf_start))
        printed_start = str(chunk.get("printed_page_start") or "")
        printed_end = str(chunk.get("printed_page_end") or printed_start)
        paragraph_index = int(chunk.get("paragraph_index") or 1)
        material_type = str(metadata.get("material_type") or "textbook")
        source_type = str(metadata.get("source_type") or "document")
        if source_type == "pdf":
            printed_prefix = "教材第" if material_type == "textbook" else "印刷第"
            printed = f"{printed_prefix} {printed_start}" + (f"—{printed_end}" if printed_end and printed_end != printed_start else "") + " 页｜" if printed_start else ""
            physical = f"PDF 第 {pdf_start}" + (f"—{pdf_end}" if pdf_end != pdf_start else "") + " 页"
            position_label = f"{printed}{physical}｜第 {paragraph_index} 段"
        elif metadata.get("source_url"):
            position_label = f"权威原文网页｜第 {paragraph_index} 段"
        else:
            position_label = f"资料正文｜第 {paragraph_index} 段"
        documents.append(Document(
            page_content=str(chunk["content"]),
            metadata={**metadata, **dict(chunk.get("metadata") or {}),
                      "document_id": document_id, "vector_id": ids[index], "chunk_index": index,
                      "chunk_count": len(chunks), "pdf_page_start": pdf_start, "pdf_page_end": pdf_end,
                      "paragraph_index": paragraph_index,
                      "printed_page_start": printed_start, "printed_page_end": printed_end,
                      "section_path": str(chunk.get("section_path") or ""),
                      "start_anchor": str(chunk.get("start_anchor") or ""),
                      "end_anchor": str(chunk.get("end_anchor") or ""),
                      "position_label": position_label},
        ))
    get_vector_store(collection_name).add_documents(documents, ids=ids)
    return ids


def delete_document_vectors(document_id: int) -> None:
    store = get_vector_store()
    result = store.get(where={"document_id": document_id}, include=[])
    if result["ids"]:
        store.delete(ids=result["ids"])


def upsert_study_note_vector(*, note_id: int, content: str, metadata: dict[str, str | int]) -> None:
    """以小段写入笔记，支持长笔记的语义检索与定位。"""
    delete_study_note_vectors(note_id)
    text = content.strip()
    if not text:
        return
    size = 900
    chunks = [text[index:index + size] for index in range(0, len(text), size)]
    documents = [
        Document(page_content=chunk, metadata={**metadata, "note_id": note_id, "chunk_index": index})
        for index, chunk in enumerate(chunks)
    ]
    get_study_note_vector_store().add_documents(documents, ids=[f"study-note-{note_id}-{index}" for index in range(len(chunks))])


def delete_study_note_vectors(note_id: int) -> None:
    store = get_study_note_vector_store()
    result = store.get(where={"note_id": note_id}, include=[])
    if result["ids"]:
        store.delete(ids=result["ids"])

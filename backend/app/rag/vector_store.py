from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document

from app.core.config import BACKEND_DIR, settings
from app.rag.embeddings import get_embeddings


def resolve_backend_path(configured_path: str) -> Path:
    path = Path(configured_path)
    return path if path.is_absolute() else (BACKEND_DIR / path).resolve()


def get_vector_store() -> Chroma:
    persist_directory = resolve_backend_path(settings.chroma_persist_directory)
    persist_directory.mkdir(parents=True, exist_ok=True)
    return Chroma(
        collection_name=settings.rag_collection_name,
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

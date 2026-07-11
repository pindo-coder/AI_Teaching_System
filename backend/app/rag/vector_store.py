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


def add_chunks(*, document_id: int, chunks: list[str], metadata: dict[str, str | int]) -> None:
    documents = [
        Document(
            page_content=chunk,
            metadata={**metadata, "document_id": document_id, "chunk_index": index},
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

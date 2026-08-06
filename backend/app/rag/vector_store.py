from pathlib import Path
import json
import os
import re

from langchain_chroma import Chroma
from langchain_core.documents import Document

from app.core.config import BACKEND_DIR, settings
from app.rag.embeddings import EmbeddingProfile, get_embedding_profile, get_embeddings


INDEX_MANIFEST_VERSION = 2


class IncompatibleVectorIndexError(RuntimeError):
    """活动索引与当前 Embedding 配置不兼容。"""


def resolve_backend_path(configured_path: str) -> Path:
    path = Path(configured_path)
    return path if path.is_absolute() else (BACKEND_DIR / path).resolve()


def _safe_token(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-_") or "embedding"


def profile_collection_name(profile: EmbeddingProfile | None = None) -> str:
    profile = profile or get_embedding_profile()
    return (
        f"{settings.rag_collection_name}_{_safe_token(profile.model)}_"
        f"{profile.dimensions}_{profile.fingerprint}"
    )


def active_index_path() -> Path:
    """旧版/兼容用的最近一次活动索引指针。"""
    return resolve_backend_path(settings.chroma_persist_directory) / "active_index.json"


def profile_active_index_path(profile: EmbeddingProfile | None = None) -> Path:
    """按 Embedding 配置隔离活动索引，允许本地 mock 与真实模型安全切换。"""
    profile = profile or get_embedding_profile()
    return resolve_backend_path(settings.chroma_persist_directory) / f"active_index.{profile.fingerprint}.json"


def _read_manifest(path: Path) -> dict[str, object]:
    if not path.exists():
        raise FileNotFoundError(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise IncompatibleVectorIndexError("活动索引清单损坏，请重新构建索引") from exc
    if not isinstance(payload, dict) or not payload.get("collection_name"):
        raise IncompatibleVectorIndexError("活动索引清单缺少 collection_name，请重新构建索引")
    return payload


def read_active_index(profile: EmbeddingProfile | None = None) -> dict[str, object] | None:
    profile = profile or get_embedding_profile()
    scoped_path = profile_active_index_path(profile)
    if scoped_path.exists():
        return _read_manifest(scoped_path)
    legacy_path = active_index_path()
    if legacy_path.exists():
        return _read_manifest(legacy_path)
    return None


def _validate_manifest(payload: dict[str, object], profile: EmbeddingProfile) -> None:
    # 旧版清单只有集合名，无法证明维数安全；明确阻止继续混用。
    if int(payload.get("manifest_version") or 0) != INDEX_MANIFEST_VERSION:
        raise IncompatibleVectorIndexError(
            "活动索引属于旧版格式，无法校验 Embedding 维数。请执行 rebuild_precise_index.py --activate"
        )
    actual = (
        str(payload.get("embedding_provider") or ""),
        str(payload.get("embedding_model") or ""),
        int(payload.get("embedding_dimensions") or 0),
        str(payload.get("embedding_fingerprint") or ""),
    )
    expected = (profile.provider, profile.model, profile.dimensions, profile.fingerprint)
    if actual != expected:
        raise IncompatibleVectorIndexError(
            "当前 Embedding 配置与活动索引不一致："
            f"索引={actual[0]}/{actual[1]}/{actual[2]}维，"
            f"配置={expected[0]}/{expected[1]}/{expected[2]}维。"
            "请先重建并原子切换索引。"
        )


def resolve_active_collection_name() -> str:
    profile = get_embedding_profile()
    payload = read_active_index(profile)
    if payload is not None:
        _validate_manifest(payload, profile)
        return str(payload["collection_name"])
    if settings.rag_active_collection:
        # 显式覆盖仅用于首次迁移；集合中的实际维数仍会在打开时校验。
        return settings.rag_active_collection
    # 首次安装也使用配置指纹集合，不再复用无版本的历史集合名。
    return profile_collection_name(profile)


def activate_index(collection_name: str, *, profile: EmbeddingProfile | None = None) -> None:
    profile = profile or get_embedding_profile()
    directory = resolve_backend_path(settings.chroma_persist_directory)
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "manifest_version": INDEX_MANIFEST_VERSION,
        "collection_name": collection_name,
        "embedding_provider": profile.provider,
        "embedding_model": profile.model,
        "embedding_dimensions": profile.dimensions,
        "embedding_fingerprint": profile.fingerprint,
    }
    def write_manifest(target: Path, manifest: dict[str, object]) -> None:
        temporary = target.with_name(f".{target.name}.tmp")
        temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, target)

    legacy_target = active_index_path()
    # 第一次切换到另一种 Embedding 前，先把旧的全局指针归档到其
    # 配置指纹下。这样 DashScope、mock 或后续新模型可以各自保留
    # 一套完整索引，不必每次切换都重建。
    if legacy_target.exists():
        try:
            legacy_payload = _read_manifest(legacy_target)
            legacy_fingerprint = str(legacy_payload.get("embedding_fingerprint") or "")
            if int(legacy_payload.get("manifest_version") or 0) == INDEX_MANIFEST_VERSION and legacy_fingerprint:
                legacy_scoped = directory / f"active_index.{_safe_token(legacy_fingerprint)}.json"
                if not legacy_scoped.exists():
                    write_manifest(legacy_scoped, legacy_payload)
        except IncompatibleVectorIndexError:
            # 损坏或旧版清单仍会保存在 previous 中，但不能作为安全索引复用。
            pass

    scoped_target = profile_active_index_path(profile)
    scoped_previous = scoped_target.with_name(f"{scoped_target.stem}.previous.json")
    if scoped_target.exists():
        scoped_previous.write_bytes(scoped_target.read_bytes())
    write_manifest(scoped_target, payload)

    previous = directory / "active_index.previous.json"
    if legacy_target.exists():
        previous.write_bytes(legacy_target.read_bytes())
    write_manifest(legacy_target, payload)


def _validate_collection_dimensions(store: Chroma, profile: EmbeddingProfile) -> None:
    if store._collection.count() == 0:
        return
    sample = store._collection.peek(limit=1)
    embeddings = sample.get("embeddings")
    if embeddings is None or len(embeddings) == 0:
        return
    stored_dimensions = len(embeddings[0])
    if stored_dimensions != profile.dimensions:
        raise IncompatibleVectorIndexError(
            f"Chroma 集合 {store._collection.name} 为 {stored_dimensions} 维，"
            f"当前模型要求 {profile.dimensions} 维。请重建索引，禁止写入该集合。"
        )


def get_vector_store(collection_name: str | None = None) -> Chroma:
    persist_directory = resolve_backend_path(settings.chroma_persist_directory)
    persist_directory.mkdir(parents=True, exist_ok=True)
    profile = get_embedding_profile()
    store = Chroma(
        collection_name=collection_name or resolve_active_collection_name(),
        embedding_function=get_embeddings(),
        persist_directory=str(persist_directory),
    )
    _validate_collection_dimensions(store, profile)
    return store


def get_study_note_vector_store() -> Chroma:
    """个人笔记按模型和维度分集合，切换 Embedding 后不复用旧维度集合。"""
    persist_directory = resolve_backend_path(settings.chroma_persist_directory)
    persist_directory.mkdir(parents=True, exist_ok=True)
    profile = get_embedding_profile()
    return Chroma(
        collection_name=(
            f"{settings.rag_collection_name}_study_notes_{_safe_token(profile.model)}_"
            f"{profile.dimensions}_{profile.fingerprint}"
        ),
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


def delete_document_vectors(document_id: int, collection_name: str | None = None) -> None:
    store = get_vector_store(collection_name)
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

import pytest

from app.rag import vector_store


class FakeStore:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def get(self, **_kwargs):
        return {"ids": ["document-7-chunk-0", "document-7-chunk-1"]}

    def delete(self, *, ids):
        self.deleted.extend(ids)


def test_replace_precise_chunks_does_not_delete_old_vectors_when_upsert_fails(monkeypatch) -> None:
    store = FakeStore()
    monkeypatch.setattr(vector_store, "get_vector_store", lambda *_: store)
    monkeypatch.setattr(
        vector_store, "add_precise_chunks",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("embedding unavailable")),
    )

    with pytest.raises(RuntimeError, match="embedding unavailable"):
        vector_store.replace_precise_chunks(
            document_id=7, chunks=[{"content": "new"}], metadata={}, collection_name="active",
        )

    assert store.deleted == []


def test_replace_precise_chunks_removes_only_stale_tail_after_success(monkeypatch) -> None:
    store = FakeStore()
    monkeypatch.setattr(vector_store, "get_vector_store", lambda *_: store)
    monkeypatch.setattr(
        vector_store, "add_precise_chunks",
        lambda **_kwargs: ["document-7-chunk-0"],
    )

    ids = vector_store.replace_precise_chunks(
        document_id=7, chunks=[{"content": "new"}], metadata={}, collection_name="active",
    )

    assert ids == ["document-7-chunk-0"]
    assert store.deleted == ["document-7-chunk-1"]


def test_replace_precise_chunks_rejects_fragment_explosion_before_opening_store(monkeypatch) -> None:
    opened = False

    def open_store(*_args, **_kwargs):
        nonlocal opened
        opened = True
        return FakeStore()

    monkeypatch.setattr(vector_store, "get_vector_store", open_store)
    chunks = [{"content": "fragment"}] * (vector_store.MAX_DOCUMENT_VECTOR_CHUNKS + 1)

    with pytest.raises(ValueError, match="超过安全上限"):
        vector_store.replace_precise_chunks(
            document_id=7, chunks=chunks, metadata={}, collection_name="active",
        )

    assert opened is False

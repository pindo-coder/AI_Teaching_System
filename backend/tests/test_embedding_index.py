import json

import pytest

from app.core.config import settings
from app.rag.embeddings import configured_embedding_dimensions, get_embedding_profile
from app.rag.vector_store import (
    INDEX_MANIFEST_VERSION,
    IncompatibleVectorIndexError,
    activate_index,
    active_index_path,
    profile_active_index_path,
    profile_collection_name,
    resolve_active_collection_name,
)


def test_dashscope_v2_uses_fixed_1536_dimensions(monkeypatch):
    monkeypatch.setattr(settings, "embedding_provider", "dashscope")
    monkeypatch.setattr(settings, "embedding_model", "text-embedding-v2")
    monkeypatch.setattr(settings, "embedding_dimensions", 1024)

    assert configured_embedding_dimensions() == 1536


def test_v4_profile_uses_configured_dimensions(monkeypatch):
    monkeypatch.setattr(settings, "embedding_provider", "dashscope")
    monkeypatch.setattr(settings, "embedding_model", "text-embedding-v4")
    monkeypatch.setattr(settings, "embedding_dimensions", 1024)

    profile = get_embedding_profile()
    assert profile.dimensions == 1024
    assert "text-embedding-v4" in profile_collection_name(profile)


def test_legacy_active_manifest_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "embedding_provider", "mock")
    monkeypatch.setattr(settings, "chroma_persist_directory", str(tmp_path))
    active_index_path().write_text(json.dumps({"collection_name": "legacy"}), encoding="utf-8")

    with pytest.raises(IncompatibleVectorIndexError, match="旧版格式"):
        resolve_active_collection_name()


def test_model_switch_cannot_reuse_active_collection(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "chroma_persist_directory", str(tmp_path))
    monkeypatch.setattr(settings, "embedding_provider", "dashscope")
    monkeypatch.setattr(settings, "embedding_model", "text-embedding-v2")
    monkeypatch.setattr(settings, "embedding_dimensions", 1024)
    old = get_embedding_profile()
    active_index_path().write_text(json.dumps({
        "manifest_version": INDEX_MANIFEST_VERSION,
        "collection_name": "v2-index",
        "embedding_provider": old.provider,
        "embedding_model": old.model,
        "embedding_dimensions": old.dimensions,
        "embedding_fingerprint": old.fingerprint,
    }), encoding="utf-8")

    monkeypatch.setattr(settings, "embedding_model", "text-embedding-v4")

    with pytest.raises(IncompatibleVectorIndexError, match="活动索引不一致"):
        resolve_active_collection_name()


def test_each_embedding_profile_keeps_its_own_active_collection(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "chroma_persist_directory", str(tmp_path))
    monkeypatch.setattr(settings, "embedding_provider", "dashscope")
    monkeypatch.setattr(settings, "embedding_model", "text-embedding-v4")
    monkeypatch.setattr(settings, "embedding_dimensions", 1024)
    dashscope_profile = get_embedding_profile()
    activate_index("dashscope-v4-index", profile=dashscope_profile)

    monkeypatch.setattr(settings, "embedding_provider", "mock")
    mock_profile = get_embedding_profile()
    activate_index("mock-index", profile=mock_profile)
    assert resolve_active_collection_name() == "mock-index"
    assert profile_active_index_path(mock_profile).exists()

    monkeypatch.setattr(settings, "embedding_provider", "dashscope")
    assert resolve_active_collection_name() == "dashscope-v4-index"
    assert profile_active_index_path(dashscope_profile).exists()

import os

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.core.config import settings


test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def reset_database(tmp_path, monkeypatch):
    # 测试默认使用确定性向量，避免单元测试依赖外部 Embedding 服务。
    monkeypatch.setattr(settings, "ai_mock_mode", True)
    monkeypatch.setattr(settings, "embedding_provider", "mock")
    # 测试不应读取开发者本机的百炼密钥；多模态可用性由专门用例显式覆盖。
    monkeypatch.setattr(settings, "dashscope_api_key", None)
    monkeypatch.setattr(settings, "ppt_multimodal_api_key", None)
    monkeypatch.setattr(settings, "ai_vision_api_key", None)
    monkeypatch.setattr(settings, "ai_asr_api_key", None)
    monkeypatch.setattr(settings, "ai_media_directory", str(tmp_path / "ai_media"))
    monkeypatch.setattr(settings, "chroma_persist_directory", str(tmp_path / "chroma"))
    monkeypatch.setattr(settings, "knowledge_upload_directory", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "generated_artifact_directory", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "rag_collection_name", "test_knowledge_base")
    monkeypatch.setattr(settings, "rag_score_threshold", -1.0)
    Base.metadata.drop_all(test_engine)
    Base.metadata.create_all(test_engine)
    yield


@pytest.fixture
def db() -> Session:
    with TestingSessionLocal() as session:
        yield session


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client

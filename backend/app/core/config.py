from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """集中管理环境配置，便于后续切换数据库和部署环境。"""

    app_name: str = "高校思政课 AI 智能教学辅助平台"
    app_env: str = "development"
    debug: bool = True
    api_v1_prefix: str = "/api/v1"
    database_url: str = "sqlite:///./data/app.db"
    cors_origins: list[str] = ["http://localhost:5173"]
    log_level: str = "INFO"
    jwt_secret_key: str = "please-change-this-development-secret"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 120
    bootstrap_admin_username: str | None = None
    bootstrap_admin_password: str | None = None
    ai_mock_mode: bool = True
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.2
    llm_timeout_seconds: int = 60
    embedding_provider: str = "mock"
    embedding_api_key: str | None = None
    embedding_base_url: str | None = None
    embedding_model: str = "text-embedding-3-small"
    chroma_persist_directory: str = "../knowledge_base/chroma"
    knowledge_upload_directory: str = "../knowledge_base/uploads"
    rag_collection_name: str = "ideology_course_kb"
    rag_top_k: int = 4
    rag_score_threshold: float = 0.15
    text_chunk_size: int = 800
    text_chunk_overlap: int = 120
    max_upload_size_mb: int = 20

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

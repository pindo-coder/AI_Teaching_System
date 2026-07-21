from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
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
    llm_api_key: str | None = Field(default=None, validation_alias=AliasChoices("LLM_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY"))
    llm_base_url: str | None = Field(default=None, validation_alias=AliasChoices("LLM_BASE_URL", "OPENAI_BASE_URL", "DEEPSEEK_BASE_URL"))
    llm_model: str = Field(default="gpt-4o-mini", validation_alias=AliasChoices("LLM_MODEL", "OPENAI_MODEL", "DEEPSEEK_MODEL"))
    llm_temperature: float = 0.2
    llm_timeout_seconds: int = 60
    embedding_provider: str = "mock"
    embedding_api_key: str | None = Field(default=None, validation_alias=AliasChoices("EMBEDDING_API_KEY", "DASHSCOPE_API_KEY", "OPENAI_API_KEY"))
    embedding_base_url: str | None = Field(default=None, validation_alias=AliasChoices("EMBEDDING_BASE_URL", "DASHSCOPE_BASE_URL", "OPENAI_BASE_URL"))
    embedding_model: str = Field(default="text-embedding-v4", validation_alias=AliasChoices("EMBEDDING_MODEL", "DASHSCOPE_EMBEDDING_MODEL", "OPENAI_EMBEDDING_MODEL"))
    embedding_dimensions: int = 1024
    chroma_persist_directory: str = "../knowledge_base/chroma"
    knowledge_upload_directory: str = "../knowledge_base/uploads"
    rag_collection_name: str = "ideology_course_kb"
    rag_active_collection: str | None = None
    rag_top_k: int = 4
    rag_score_threshold: float = 0.15
    text_chunk_size: int = 800
    text_chunk_overlap: int = 120
    max_upload_size_mb: int = 100
    material_batch_max_items: int = 500
    material_batch_worker_concurrency: int = 2

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

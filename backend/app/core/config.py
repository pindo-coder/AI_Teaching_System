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
    # SQLite 开发库仍可自动建表；MySQL 等持久数据库必须由 Alembic 管理，
    # 启动时只校验 revision，避免 create_all 产生“有表但缺列”的混合结构。
    database_schema_check_enabled: bool = True
    cors_origins: list[str] = ["http://localhost:5173"]
    log_level: str = "INFO"
    jwt_secret_key: str = "please-change-this-development-secret"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 120
    # 密码找回：development 默认 console，生产请改为 smtp 或 provider。
    mail_backend: str = "console"
    mail_host: str | None = None
    mail_port: int = 465
    mail_username: str | None = None
    mail_password: str | None = None
    mail_from: str | None = None
    mail_use_ssl: bool = True
    password_reset_url: str = "http://localhost:5173/reset-password"
    password_reset_token_expire_minutes: int = Field(default=20, ge=5, le=120)
    password_reset_rate_limit_seconds: int = Field(default=60, ge=10, le=3600)
    password_reset_hourly_limit: int = Field(default=5, ge=1, le=100)
    admin_temporary_password: str = "12345678"
    email_verification_url: str = "http://localhost:5173/verify-email"
    bootstrap_admin_username: str | None = None
    bootstrap_admin_password: str | None = None
    ai_mock_mode: bool = True
    llm_api_key: str | None = Field(default=None, validation_alias=AliasChoices("LLM_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY"))
    llm_base_url: str | None = Field(default=None, validation_alias=AliasChoices("LLM_BASE_URL", "OPENAI_BASE_URL", "DEEPSEEK_BASE_URL"))
    llm_model: str = Field(default="gpt-4o-mini", validation_alias=AliasChoices("LLM_MODEL", "OPENAI_MODEL", "DEEPSEEK_MODEL"))
    llm_temperature: float = 0.2
    llm_timeout_seconds: int = 60
    # 百炼视觉、语音、Embedding 共用同一地域的 API Key；各能力仍可用独立 Key 覆盖。
    dashscope_api_key: str | None = None
    # 学习助手的输入侧多模态保持轻量：文件分块落盘，推理交给外部兼容 API，
    # 小服务器不加载视觉或语音模型。独立配置允许文本、视觉和转写使用不同供应商。
    ai_media_directory: str = "../knowledge_base/ai_media"
    ai_media_max_images: int = Field(default=2, ge=1, le=2)
    ai_media_max_image_mb: int = Field(default=5, ge=1, le=20)
    ai_media_max_audio_mb: int = Field(default=10, ge=1, le=25)
    ai_media_max_audio_seconds: int = Field(default=60, ge=1, le=60)
    # 临时媒体必须有服务端生命周期、用户总额和可信时长校验，不能依赖浏览器清理。
    ai_media_retention_hours: int = Field(default=24, ge=1, le=168)
    ai_media_user_quota_mb: int = Field(default=50, ge=10, le=500)
    ai_media_ffprobe_binary: str = "ffprobe"
    ai_vision_enabled: bool = True
    # 媒体专用配置只表示显式覆盖；百炼/向量配置的复用由 provider 统一解析，
    # 避免 OPENAI_* 文本模型变量意外抢占图片或语音供应商。
    ai_vision_api_key: str | None = None
    ai_vision_base_url: str | None = None
    ai_vision_model: str = Field(
        default="qwen3-vl-plus",
        validation_alias=AliasChoices("AI_VISION_MODEL", "DASHSCOPE_VISION_MODEL"),
    )
    ai_vision_timeout_seconds: int = 90
    ai_asr_enabled: bool = True
    ai_asr_api_key: str | None = None
    ai_asr_base_url: str | None = None
    ai_asr_model: str = Field(
        default="qwen3-asr-flash",
        validation_alias=AliasChoices("AI_ASR_MODEL", "DASHSCOPE_ASR_MODEL"),
    )
    ai_asr_timeout_seconds: int = 120
    ai_config_encryption_key: str | None = None
    embedding_provider: str = "mock"
    embedding_api_key: str | None = Field(default=None, validation_alias=AliasChoices("EMBEDDING_API_KEY", "DASHSCOPE_API_KEY", "OPENAI_API_KEY"))
    embedding_base_url: str | None = Field(default=None, validation_alias=AliasChoices("EMBEDDING_BASE_URL", "DASHSCOPE_BASE_URL", "OPENAI_BASE_URL"))
    embedding_model: str = Field(default="text-embedding-v4", validation_alias=AliasChoices("EMBEDDING_MODEL", "DASHSCOPE_EMBEDDING_MODEL", "OPENAI_EMBEDDING_MODEL"))
    embedding_dimensions: int = 1024
    chroma_persist_directory: str = "../knowledge_base/chroma"
    knowledge_upload_directory: str = "../knowledge_base/uploads"
    generated_artifact_directory: str = "../knowledge_base/generated_artifacts"
    presentation_node_binary: str = "node"
    presentation_node_modules: str | None = None
    ppt_multimodal_enabled: bool = True
    ppt_multimodal_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("PPT_MULTIMODAL_API_KEY", "DASHSCOPE_API_KEY"),
    )
    ppt_multimodal_base_url: str = "https://dashscope.aliyuncs.com/api/v1"
    # Wan2.7 Image Pro 质量更适合课堂配图；如需降低成本可在 .env 改为 wan2.7-image。
    ppt_multimodal_model: str = "wan2.7-image-pro"
    ppt_multimodal_max_images: int = 3
    ppt_multimodal_timeout_seconds: int = 180
    rag_collection_name: str = "ideology_course_kb"
    rag_active_collection: str | None = None
    rag_top_k: int = 4
    rag_score_threshold: float = 0.15
    text_chunk_size: int = 800
    text_chunk_overlap: int = 120
    max_upload_size_mb: int = 100
    # 时政订阅没有统一的推送频率；这些参数控制缓存刷新和默认展示窗口。
    news_refresh_interval_minutes: int = Field(default=30, ge=1, le=1440)
    news_default_days: int = Field(default=90, ge=1, le=365)
    news_max_stale_days: int = Field(default=14, ge=1, le=3650)
    news_feed_item_limit: int = Field(default=50, ge=1, le=200)
    news_request_timeout_seconds: int = Field(default=10, ge=2, le=60)
    material_batch_max_items: int = 500
    material_batch_worker_concurrency: int = 2
    # 权威资料发现调度器默认关闭，管理员确认来源白名单后可在 .env 开启。
    authority_discovery_scheduler_enabled: bool = False
    authority_discovery_scheduler_poll_seconds: int = 300
    # 单机发现任务保护：默认只并发一个任务，避免抓取、解析和模型调用互相抢占资源。
    authority_discovery_max_running: int = 1
    authority_discovery_max_queued: int = 5
    authority_discovery_max_links_per_source: int = 20
    authority_discovery_cooldown_minutes: int = 30
    authority_discovery_daily_fetch_limit: int = 300
    authority_discovery_request_interval_seconds: int = 3
    authority_discovery_min_relevance_score: float = Field(default=0.55, ge=0, le=1)
    authority_discovery_min_association_score: float = Field(default=0.45, ge=0, le=1)
    authority_discovery_min_extraction_quality: float = Field(default=0.60, ge=0, le=1)
    authority_discovery_importance_threshold: float = Field(default=0.60, ge=0, le=1)
    # 教材匹配采用“多路召回 -> RRF -> 可选 Cross-Encoder”的分层结构。
    # 开源模型默认关闭，避免小型部署在启动时下载大模型；启用失败会确定性降级。
    authority_matching_rrf_rank_constant: int = Field(default=60, ge=1, le=500)
    authority_matching_max_chapters: int = Field(default=3, ge=1, le=8)
    # 召回、人工审核和告警使用不同阈值，避免为了降低误报而牺牲网页发现召回率。
    authority_matching_min_raw_score: float = Field(default=0.32, ge=0, le=1)
    authority_matching_candidate_retention_score: float = Field(default=0.20, ge=0, le=1)
    authority_matching_candidate_relevance_score: float = Field(default=0.35, ge=0, le=1)
    authority_matching_alert_score: float = Field(default=0.72, ge=0, le=1)
    authority_matching_reranker_enabled: bool = False
    authority_matching_reranker_model: str = "BAAI/bge-reranker-v2-m3"
    authority_matching_reranker_threshold: float = Field(default=0.45, ge=0, le=1)
    authority_matching_reranker_device: str = "cpu"
    authority_matching_nli_enabled: bool = False
    authority_matching_nli_model: str = "IDEA-CCNL/Erlangshen-Roberta-110M-NLI"
    authority_matching_nli_neutral_threshold: float = Field(default=0.55, ge=0, le=1)
    authority_matching_nli_device: str = "cpu"
    # 规划型 Agent 的安全开关与循环上限；生产环境可在不中断旧 Chat 的情况下关闭。
    agent_planner_enabled: bool = True
    agent_planner_use_llm: bool = True
    agent_planner_max_steps: int = 5
    # V2 使用声明式工具注册和单步重规划；保留开关便于灰度回退旧协议。
    agent_runtime_v2_enabled: bool = True
    agent_runtime_max_iterations: int = Field(default=8, ge=1, le=20)
    agent_tool_timeout_seconds: float = Field(default=30.0, ge=1, le=300)
    agent_tool_max_retries: int = Field(default=1, ge=0, le=2)
    agent_execution_deadline_seconds: float = Field(default=300.0, ge=10, le=3600)

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

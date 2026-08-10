from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin


class AiProviderConfig(TimestampMixin, Base):
    __tablename__ = "ai_provider_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    capability: Mapped[str] = mapped_column(
        String(32), nullable=False, default="text", server_default="text", index=True
    )
    provider_name: Mapped[str] = mapped_column(
        String(80), nullable=False, default="openai_compatible", server_default="openai_compatible"
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    api_key_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    dimensions: Mapped[int | None] = mapped_column(Integer)
    temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.2)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    streaming_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    last_test_status: Mapped[str] = mapped_column(String(20), nullable=False, default="passed")
    last_test_message: Mapped[str | None] = mapped_column(String(1000))
    last_test_time: Mapped[datetime | None] = mapped_column(DateTime)


class AiCallLog(Base):
    __tablename__ = "ai_call_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    feature: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    provider_config_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_provider_configs.id", ondelete="SET NULL"), index=True
    )
    model_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    base_url: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="running", index=True)
    streaming: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    input_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error_type: Mapped[str | None] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(String(1000))
    started_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    finished_time: Mapped[datetime | None] = mapped_column(DateTime)

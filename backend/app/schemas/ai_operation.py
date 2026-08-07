from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class AiProviderConfigInput(BaseModel):
    base_url: str = Field(min_length=8, max_length=500)
    model_name: str = Field(min_length=1, max_length=200)
    api_key: str | None = Field(default=None, max_length=1000)
    temperature: float = Field(default=0.2, ge=0, le=2)
    timeout_seconds: int = Field(default=60, ge=5, le=600)
    streaming_enabled: bool = True

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("接口地址必须以 http:// 或 https:// 开头")
        return normalized


class AiProviderConfigData(BaseModel):
    id: int | None
    source: str
    base_url: str | None
    model_name: str
    api_key_masked: str | None
    temperature: float
    timeout_seconds: int
    streaming_enabled: bool
    last_test_status: str | None = None
    last_test_message: str | None = None
    last_test_time: datetime | None = None
    updated_time: datetime | None = None


class AiConnectionTestData(BaseModel):
    success: bool
    model_name: str
    latency_ms: int
    message: str


class AiCallLogData(BaseModel):
    id: int
    request_id: str
    user_id: int | None
    username: str | None
    feature: str
    model_name: str
    status: str
    streaming: bool
    input_chars: int
    output_chars: int
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: int | None
    error_type: str | None
    error_message: str | None
    started_time: datetime
    finished_time: datetime | None


class AiOperationSummaryData(BaseModel):
    total_24h: int
    success_24h: int
    failed_24h: int
    running: int
    average_latency_ms: int | None
    success_rate: float
    active_model: str
    config_source: str

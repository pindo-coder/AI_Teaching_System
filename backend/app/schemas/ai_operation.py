from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


AiCapabilityName = Literal["text", "embedding", "vision", "asr", "image_generation"]


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
        if not normalized.startswith("https://"):
            raise ValueError("接口地址必须以 https:// 开头，禁止通过明文 HTTP 发送 API Key")
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


class AiCapabilityConfigInput(BaseModel):
    enabled: bool = True
    base_url: str = Field(default="", max_length=500)
    model_name: str = Field(default="", max_length=200)
    # Accepted on write but never serialized back in presets or API responses.
    api_key: str | None = Field(default=None, max_length=1000, exclude=True)
    timeout_seconds: int = Field(default=60, ge=5, le=600)
    dimensions: int | None = Field(default=None, ge=1, le=8192)
    temperature: float | None = Field(default=None, ge=0, le=2)
    streaming_enabled: bool | None = None

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if not normalized:
            return ""
        if not normalized.startswith("https://"):
            raise ValueError("接口地址必须以 https:// 开头，禁止通过明文 HTTP 发送 API Key")
        return normalized

    @field_validator("model_name")
    @classmethod
    def normalize_model_name(cls, value: str) -> str:
        return value.strip()

    @field_validator("api_key")
    @classmethod
    def normalize_capability_api_key(cls, value: str | None) -> str | None:
        normalized = (value or "").strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_enabled_config(self) -> "AiCapabilityConfigInput":
        if self.enabled and not self.base_url:
            raise ValueError("启用能力时必须配置接口地址")
        if self.enabled and not self.model_name:
            raise ValueError("启用能力时必须配置模型名称")
        return self


class AiAllProviderConfigInput(BaseModel):
    provider_name: str = Field(min_length=1, max_length=80)
    api_key: str | None = Field(default=None, max_length=1000)
    capabilities: dict[AiCapabilityName, AiCapabilityConfigInput] = Field(
        min_length=1,
        max_length=5,
    )

    @field_validator("provider_name")
    @classmethod
    def normalize_provider_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("供应商名称不能为空")
        return normalized

    @field_validator("api_key")
    @classmethod
    def normalize_api_key(cls, value: str | None) -> str | None:
        normalized = (value or "").strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_capability_options(self) -> "AiAllProviderConfigInput":
        embedding = self.capabilities.get("embedding")
        if embedding and embedding.enabled and embedding.dimensions is None:
            raise ValueError("Embedding 能力必须配置 dimensions")
        for capability, config in self.capabilities.items():
            if capability != "embedding" and config.dimensions is not None:
                raise ValueError(f"{capability} 能力不支持 dimensions")
        return self


class AiCapabilityConfigData(BaseModel):
    id: int | None
    source: str
    capability: AiCapabilityName
    provider_name: str
    enabled: bool
    base_url: str | None
    model_name: str
    api_key_masked: str | None = None
    dimensions: int | None = None
    temperature: float
    timeout_seconds: int
    streaming_enabled: bool
    last_test_status: str | None = None
    last_test_message: str | None = None
    last_test_time: datetime | None = None
    updated_time: datetime | None = None


class AiAllProviderConfigData(BaseModel):
    provider_name: str
    api_key_masked: str | None
    capabilities: dict[AiCapabilityName, AiCapabilityConfigData]


class AiProviderPresetData(BaseModel):
    id: str
    name: str
    description: str
    capabilities: dict[AiCapabilityName, AiCapabilityConfigInput]


class AiProviderPresetsData(BaseModel):
    presets: list[AiProviderPresetData]


class AiCapabilityOperationResultData(BaseModel):
    capability: AiCapabilityName
    success: bool
    skipped: bool
    latency_ms: int | None = None
    message: str
    kept_previous: bool = False
    config: AiCapabilityConfigData | None = None


class AiAllConfigOperationData(BaseModel):
    provider_name: str
    capabilities: dict[AiCapabilityName, AiCapabilityOperationResultData]


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


class AiModelTokenUsageData(BaseModel):
    model_name: str
    call_count: int
    tokenized_calls: int
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None


class AiOperationSummaryData(BaseModel):
    total_24h: int
    success_24h: int
    failed_24h: int
    running: int
    average_latency_ms: int | None
    success_rate: float
    prompt_tokens_24h: int | None
    completion_tokens_24h: int | None
    total_tokens_24h: int | None
    tokenized_calls_24h: int
    model_token_usage_24h: list[AiModelTokenUsageData]
    active_model: str
    config_source: str

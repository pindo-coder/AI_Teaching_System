import hashlib
import math
from dataclasses import dataclass
from typing import Any

from langchain_core.embeddings import Embeddings
from openai import OpenAI

from app.core.config import settings
from app.services.ai_operation_service import AiProviderConfigService


class EmbeddingDimensionMismatchError(RuntimeError):
    """Embedding 服务的实际维数与当前索引配置不一致。"""


@dataclass(frozen=True)
class EmbeddingProfile:
    provider: str
    model: str
    dimensions: int

    @property
    def fingerprint(self) -> str:
        raw = f"{self.provider}:{self.model}:{self.dimensions}:rag-v2"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]

    @property
    def version(self) -> str:
        return f"{self.provider}:{self.model}:{self.dimensions}:{self.fingerprint}"


def _embedding_runtime_config():
    """Resolve the active DB config while preserving the legacy env behaviour.

    ``resolve_capability`` also exposes an environment fallback.  Rebuilding the
    environment branch here is intentional: older deployments and tests may
    replace this module's settings object, and the existing DashScope aliases
    must continue to behave exactly as before.
    """

    config = AiProviderConfigService.resolve_capability("embedding")
    if config.source == "database":
        return config

    provider = str(settings.embedding_provider or "").strip().lower()
    api_key = settings.embedding_api_key
    base_url = settings.embedding_base_url
    model = settings.embedding_model
    if provider == "dashscope":
        api_key = settings.dashscope_api_key or api_key
        base_url = base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        model = model if model != "text-embedding-3-small" else "text-embedding-v4"
    return config.__class__(
        config_id=None,
        source="environment",
        capability="embedding",
        provider_name=provider,
        enabled=True,
        base_url=base_url,
        api_key=api_key,
        model_name=model,
        dimensions=settings.embedding_dimensions,
        temperature=0.0,
        timeout_seconds=getattr(settings, "llm_timeout_seconds", 60),
        streaming_enabled=False,
    )


def _effective_dimensions(*, provider: str, model: str, configured: int | None) -> int:
    if provider == "mock":
        return DeterministicEmbeddings.dimensions
    if provider == "dashscope" and model in {
        "text-embedding-v1",
        "text-embedding-v2",
    }:
        return 1536
    return int(configured or settings.embedding_dimensions)


def configured_embedding_dimensions() -> int:
    """返回模型真正会产生的维数，而不是盲目信任通用配置。

    DashScope v1/v2 固定返回 1536 维；v3/v4 才支持 dimensions 参数。
    mock 始终为 256 维。新增模型默认使用显式配置，并由响应校验兜底。
    """
    config = _embedding_runtime_config()
    return _effective_dimensions(
        provider=config.provider_name,
        model=config.model_name,
        configured=config.dimensions,
    )


def get_embedding_profile() -> EmbeddingProfile:
    config = _embedding_runtime_config()
    return EmbeddingProfile(
        provider=config.provider_name,
        model=config.model_name,
        dimensions=_effective_dimensions(
            provider=config.provider_name,
            model=config.model_name,
            configured=config.dimensions,
        ),
    )


class DeterministicEmbeddings(Embeddings):
    """开发测试用的确定性向量，不应作为生产语义检索模型。"""

    dimensions = 256

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        normalized = "".join(text.lower().split())
        tokens = [normalized[index : index + 2] for index in range(max(1, len(normalized) - 1))]
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            vector[index] += 1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


class OpenAICompatibleEmbeddings(Embeddings):
    """直接调用 /embeddings，兼容 DashScope 等 OpenAI 风格服务。"""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        dimensions: int | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        client_options: dict[str, Any] = {"api_key": api_key, "base_url": base_url}
        if timeout_seconds is not None:
            client_options["timeout"] = timeout_seconds
        self.client = OpenAI(**client_options)
        self.model = model
        self.dimensions = dimensions

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        output: list[list[float]] = []
        # 百炼 text-embedding-v4 同步接口单批最多 10 条；小批次也能兼容其他 OpenAI 风格服务。
        for start in range(0, len(texts), 10):
            kwargs = {"model": self.model, "input": texts[start:start + 10]}
            if self.dimensions and self.model in {"text-embedding-v3", "text-embedding-v4"}:
                kwargs["dimensions"] = self.dimensions
            response = self.client.embeddings.create(**kwargs)
            ordered = sorted(response.data, key=lambda item: item.index)
            vectors = [item.embedding for item in ordered]
            expected = self.dimensions
            if expected is None:
                raise RuntimeError("Embedding 维数未配置")
            invalid = next((len(vector) for vector in vectors if len(vector) != expected), None)
            if invalid is not None:
                raise EmbeddingDimensionMismatchError(
                    f"Embedding 维数不一致：模型 {self.model} 返回 {invalid} 维，"
                    f"当前索引配置要求 {expected} 维。请重建索引，禁止复用旧集合。"
                )
            output.extend(vectors)
        return output

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


def get_embeddings() -> Embeddings:
    config = _embedding_runtime_config()
    provider = config.provider_name.strip().lower()
    if not config.enabled:
        raise RuntimeError("Embedding 能力已禁用")
    if provider == "mock":
        return DeterministicEmbeddings()
    if not config.api_key:
        raise RuntimeError("EMBEDDING_API_KEY 或 DASHSCOPE_API_KEY 未配置")
    if not config.base_url:
        raise RuntimeError("EMBEDDING_BASE_URL 未配置")
    if not config.model_name:
        raise RuntimeError("EMBEDDING_MODEL 未配置")
    options: dict[str, Any] = {
        "api_key": config.api_key,
        "base_url": config.base_url,
        "model": config.model_name,
        "dimensions": _effective_dimensions(
            provider=provider,
            model=config.model_name,
            configured=config.dimensions,
        ),
    }
    if config.source == "database":
        options["timeout_seconds"] = config.timeout_seconds
    return OpenAICompatibleEmbeddings(
        **options,
    )

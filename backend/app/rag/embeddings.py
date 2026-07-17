import hashlib
import math

from langchain_core.embeddings import Embeddings
from openai import OpenAI

from app.core.config import settings


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

    def __init__(self, *, api_key: str, base_url: str, model: str, dimensions: int | None = None) -> None:
        self.client = OpenAI(api_key=api_key, base_url=base_url)
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
            output.extend(item.embedding for item in ordered)
        return output

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


def get_embeddings() -> Embeddings:
    if settings.embedding_provider == "mock":
        return DeterministicEmbeddings()
    if settings.embedding_provider in {"openai_compatible", "dashscope"}:
        if not settings.embedding_api_key:
            raise RuntimeError("EMBEDDING_API_KEY 或 DASHSCOPE_API_KEY 未配置")
        base_url = settings.embedding_base_url
        model = settings.embedding_model
        if settings.embedding_provider == "dashscope":
            base_url = base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1"
            model = model if model != "text-embedding-3-small" else "text-embedding-v4"
        if not base_url:
            raise RuntimeError("EMBEDDING_BASE_URL 未配置")
        return OpenAICompatibleEmbeddings(api_key=settings.embedding_api_key, base_url=base_url, model=model,
                                           dimensions=settings.embedding_dimensions)
    raise RuntimeError(f"不支持的 EMBEDDING_PROVIDER：{settings.embedding_provider}")

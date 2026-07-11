import hashlib
import math

from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings

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


def get_embeddings() -> Embeddings:
    if settings.embedding_provider == "mock":
        return DeterministicEmbeddings()
    if settings.embedding_provider == "openai_compatible":
        if not settings.embedding_api_key:
            raise RuntimeError("EMBEDDING_API_KEY 未配置")
        return OpenAIEmbeddings(
            api_key=settings.embedding_api_key,
            base_url=settings.embedding_base_url,
            model=settings.embedding_model,
        )
    raise RuntimeError(f"不支持的 EMBEDDING_PROVIDER：{settings.embedding_provider}")

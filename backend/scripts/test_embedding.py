"""检查 Embedding 配置并发送一条非敏感测试文本。"""

from app.core.config import settings
from app.rag.embeddings import get_embeddings


def main() -> None:
    print(f"provider={settings.embedding_provider}")
    print(f"model={settings.embedding_model}")
    if settings.embedding_provider == "mock":
        print("warning=当前为 mock 模式，不会调用真实 Embedding 服务")
    embeddings = get_embeddings()
    vector = embeddings.embed_query("思政课教材知识库 Embedding 连通性测试")
    print(f"success=向量生成成功，维度={len(vector)}")


if __name__ == "__main__":
    main()

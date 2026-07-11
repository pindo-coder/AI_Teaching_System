# 系统架构

```text
Vue 3 前端
  ↓ REST API
FastAPI
  ├─ 认证与业务服务
  ├─ SQLAlchemy → SQLite
  └─ AI/RAG 服务 → LangChain → Chroma → 模型 API
```

后端遵循轻量分层：API 负责协议和校验，Service 负责编排业务，Repository 负责数据访问，RAG 模块负责文档入库、检索与生成。

阶段 1 暂不引入 Service 和 Repository 的空实现，待阶段 2 出现实际业务后按需建立，避免无业务逻辑的过度抽象。

数据库地址通过 `DATABASE_URL` 配置。业务代码不依赖 SQLite 专属查询，为后续切换 PostgreSQL 保留空间。

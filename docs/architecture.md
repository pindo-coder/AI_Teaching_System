# 系统架构

```text
浏览器 / 教学工作台
  ↓ HTTPS (80/443)
Caddy 网关（自动 TLS / 安全头）
  ↓ HTTP (内网)
Nginx 前端静态资源 & /api/ 反向代理（Vue 3 + TypeScript + Vite + Pinia + Element Plus）
  ↓ REST / SSE (/api/v1)
FastAPI 后端（Python 3.12）
  ├─ API 层 (app/api/v1/endpoints)：协议校验、鉴权依赖、限流与 SSE 流式输出
  ├─ Service 层 (app/services)：课程/任务/课堂/作业/新闻/Agent 执行与课件编排
  ├─ Repository & ORM 层 (app/repositories, app/models)：SQLAlchemy 2 + Alembic 迁移
  │    └─ 本地开发 SQLite / 生产外部 MySQL 8+ (DATABASE_URL)
  ├─ RAG 与知识库层 (app/rag)：文档解析、分块、Chroma 向量检索与引用溯源
  └─ 教学成果与课件流水线 (app/services/presentation_runtime)：PPT Master + LibreOffice / Poppler / ffprobe
```

## 核心模块说明

- **前端应用（`frontend/`）**：基于 Vue 3、TypeScript、Vite、Pinia、Vue Router 与 Element Plus 构建，采用路由级代码分割和工作台侧边栏异步按需加载；通过统一设计令牌（`src/styles/tokens.css`）和主题系统管理样式，并内置部署后 Chunk 失效自动刷新恢复机制。
- **后端分层（`backend/app/`）**：
  - `api/`：路由注册、JWT + `token_version` 鉴权与角色权限校验、统一响应包络（`ApiResponse`）及错误处理器。
  - `services/`：封装业务规则、AI 助教与多步 Agent 运行时（规划、审批、执行、校验）、新闻抓取及课件生成。
  - `repositories/` & `models/`：数据访问与 ORM 定义；通过 Alembic 管理数据库迁移，兼容本地 SQLite 与生产 MySQL 8+，并通过 `DATABASE_URL` 切换。
  - `rag/`：教材与课程资料文本提取、切块、ChromaDB 持久化索引与证据检索，支持按角色和审核状态过滤可见范围。
  - `core/`：环境配置、安全策略（JWT、密码哈希、媒体签名令牌、代理可信边界限流）以及基于 `ContextVar` 的 `request_id` 全链路日志追踪。
- **持久化与部署（`docker-compose.yml`、`deploy/`）**：
  - 生产环境通过 Caddy 暴露 80/443，Nginx 托管前端静态构建并将 `/api/` 转发至内网 FastAPI 容器。
  - 业务数据存储于外部 MySQL；上传资料、临时媒体、Chroma 索引、生成的 PPTX/Word 教学成果分别挂载独立 Docker volume。

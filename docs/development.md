# 开发说明

## 阶段划分

1. 项目骨架、配置、SQLite 与 SQLAlchemy 模型
2. JWT 用户系统、角色权限、课程与章节系统
3. 嵌入式 AI 组件和 LangChain 模型调用（已完成）
4. 文档上传、Chroma 与 RAG 检索（已完成）
5. UI、异常处理、日志和测试优化（已完成）

## 约定

- 后端模块使用 `snake_case`，前端 Vue 组件使用 `PascalCase`。
- 密钥及环境差异配置只写入 `.env`。
- API 统一使用 `/api/v1` 前缀。
- SQLite 文件位于 `backend/data/`，不会提交到版本库。
- 上传资料和 Chroma 数据不会提交到版本库。
- MVP 启动时使用 SQLAlchemy 创建数据表；需要多人协作或进入部署阶段时引入 Alembic。
- 每个 HTTP 响应包含 `X-Request-ID`，错误响应包含相同的 `request_id`，便于定位日志。
- AI 与知识库服务记录课程、章节、任务和分块数量，不记录 API 密钥或完整用户密码。

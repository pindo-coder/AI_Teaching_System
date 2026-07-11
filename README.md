# 高校思政课 AI 智能教学辅助平台

面向高校思政课程的 AI 教学辅助平台 MVP。系统围绕课程、章节、知识点和学习阶段组织 AI 能力，而非提供通用聊天入口。

MVP 阶段 0～5 已完成：用户与课程系统、阶段化 AI 助手、RAG 知识库、统一错误处理、请求日志、安全校验和验收数据均已具备。

## 项目结构

- `frontend/`：Vue 3、Vite、TypeScript、Vue Router、Pinia、Element Plus
- `backend/`：FastAPI、SQLAlchemy、SQLite
- `knowledge_base/`：原始资料与 Chroma 持久化目录（阶段 4 使用）
- `docs/`：架构、API 与开发说明

## 环境要求

- Node.js 20+
- Python 3.11+

## 启动后端

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

访问：

- 健康检查：`http://localhost:8000/api/v1/health`
- OpenAPI 文档：`http://localhost:8000/docs`

开发环境首次启动会按照 `.env` 中的 `BOOTSTRAP_ADMIN_USERNAME` 和
`BOOTSTRAP_ADMIN_PASSWORD` 创建管理员。创建完成后建议清空管理员密码配置。

## 启动前端

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

访问 `http://localhost:5173`。开发服务器会将 `/api` 请求代理至后端的 8000 端口。

## 测试

```bash
cd backend
pytest
```

```bash
cd frontend
npm run type-check
npm run build
```

## 配置原则

运行配置从 `.env` 读取，仓库只提交 `.env.example`。不要提交真实 API 密钥、数据库文件、上传资料或 Chroma 数据。

公开注册账号固定为 `student`。课程和章节写操作仅 `admin` 可用，所有登录用户均可查看课程并记录学习进度。

## AI 模式

默认配置 `AI_MOCK_MODE=true`，用于不消耗模型额度地验证完整业务流程。接入 OpenAI 兼容模型 API 时配置：

```env
AI_MOCK_MODE=false
LLM_API_KEY=your-api-key
LLM_BASE_URL=https://your-provider.example/v1
LLM_MODEL=your-model-name
```

AI 请求必须携带课程、章节和学习阶段。存在已入库资料时，系统优先使用 Chroma 检索结果；尚未上传资料时回退到章节正文。

## 知识库与 Embedding

教师或管理员可以从“课程知识库”页面上传可复制文本的 PDF、TXT 和 Markdown。扫描版 PDF 暂不包含 OCR，应先转为可检索文本。

开发环境默认使用确定性模拟 Embedding：

```env
EMBEDDING_PROVIDER=mock
```

接入 BGE-M3 或其他 OpenAI 兼容 Embedding API：

```env
EMBEDDING_PROVIDER=openai_compatible
EMBEDDING_API_KEY=your-embedding-key
EMBEDDING_BASE_URL=https://your-provider.example/v1
EMBEDDING_MODEL=BAAI/bge-m3
```

模拟 Embedding 仅用于验证入库与检索流程，真实教材检索应配置语义 Embedding 服务。

## 本地验收数据

```bash
cd backend
python -m scripts.seed_demo
```

验收账号：

- 管理员：`admin` / `Admin@123456`
- 学生：`student_demo` / `Student@123456`

示例数据包含一门课程、两个章节和一份已向量化的 Markdown 课程资料。上述账号和密码仅用于本地 MVP 验收，部署前必须修改。

## 当前 MVP 边界

- 默认 AI 与 Embedding 均为本地模拟模式，需配置 API 才能评价真实模型效果。
- PDF 支持文本型文件，扫描版需要先 OCR。
- 文档入库使用同步处理，适合 MVP 规模。
- 当前为本地开发服务器，不等同于公网生产部署。

# 高校思政课 AI 智能教学辅助平台

面向高校思政课程的 AI 教学辅助平台 MVP。系统围绕课程、章节、知识点和学习阶段组织 AI 能力，而非提供通用聊天入口。

MVP 阶段 0～5 已完成：用户与课程系统、阶段化 AI 助手、分层 RAG 资料中心、统一错误处理、请求日志、安全校验和验收数据均已具备。

当前版本还包含专题个人笔记、1/2/4/7/15/30 天间隔复习，以及基于 SSE 的 AI 流式输出。相关设计参考与许可说明见 [`THIRD_PARTY_NOTICES.md`](./THIRD_PARTY_NOTICES.md)。

## 项目结构

- `frontend/`：Vue 3、Vite、TypeScript、Vue Router、Pinia、Element Plus
- `backend/`：FastAPI、SQLAlchemy，支持 SQLite/MySQL
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

学生和教师均可公开注册；教师账号需要管理员审核后才能进入教学功能。课程和章节写操作仅 `admin` 可用，所有已授权用户均可查看课程并记录学习进度。

## AI 模式

默认配置 `AI_MOCK_MODE=true`，用于不消耗模型额度地验证完整业务流程。接入 OpenAI 兼容模型 API 时配置：

```env
AI_MOCK_MODE=false
LLM_API_KEY=your-api-key
LLM_BASE_URL=https://your-provider.example/v1
LLM_MODEL=your-model-name
```

AI 请求必须携带课程、章节和学习阶段。存在已入库资料时，系统优先使用 Chroma 检索结果；尚未上传资料时回退到章节正文。

## 资料中心与 Embedding

资料中心按“中央材料—教材正文—地方材料”三层管理可核验原文。中央材料仅管理员可导入、确认教材/专题范围并发布；教材继续沿用版本管理、自动专题拆分和 PDF 页码校准；地方材料可由管理员或已审核教师导入，教师资料默认限定到本人教学班。支持可复制文本的 PDF、TXT、Markdown，中央材料还支持公开 HTTPS 原文归档。扫描版 PDF 暂不包含 OCR，应先转为可检索文本。

AI 检索先做专题相关性过滤，再按中央材料、教材正文、地方材料的权威层级加权。单次回答最多使用 2 条中央材料、至少 2 条教材依据、最多 1 条地方材料；某一层没有相关原文时不会为凑数量捏造来源。中央网页保留原网址，PDF 引用保留物理页与校准后的印刷页码。

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

接入阿里云百炼 DashScope Embedding：

```env
EMBEDDING_PROVIDER=dashscope
DASHSCOPE_API_KEY=your-dashscope-key
DASHSCOPE_EMBEDDING_MODEL=text-embedding-v4
EMBEDDING_DIMENSIONS=1024
```

DashScope 默认使用 `https://dashscope.aliyuncs.com/compatible-mode/v1`。切换模型后不要直接覆盖旧集合，使用安全重建脚本：

```bash
cd backend
PYTHONPATH=. python -m scripts.rebuild_precise_index
# 确认构建与数量检查正常后再原子切换
PYTHONPATH=. python -m scripts.rebuild_precise_index --activate
PYTHONPATH=. python -m scripts.rebuild_study_note_index
```

教材与个人笔记都会按当前模型和维度进入独立 collection。旧 Chroma collection 会保留；删除 `knowledge_base/chroma/active_index.json` 即可回退教材索引到环境变量或默认集合。

## 切换 MySQL

本地开发默认使用 SQLite；服务器可以在 `backend/.env` 中切换：

```env
DATABASE_URL=mysql+pymysql://ai_teaching:密码@127.0.0.1:3306/ai_teaching?charset=utf8mb4
```

先创建数据库和用户，再执行初始化：

```bash
cd backend
PYTHONPATH=. python scripts/init_database.py
```

初始化脚本适用于 SQLite 和 MySQL；正式环境应使用独立数据库用户，不要使用 root。

## 升级现有数据库与教材

已有服务器数据库按以下顺序升级。执行前先备份 MySQL、上传目录和 Chroma 目录：

```bash
cd backend
alembic upgrade head
PYTHONPATH=. python -m scripts.bootstrap_default_class
PYTHONPATH=. python -m scripts.migrate_existing_citations
PYTHONPATH=. python -m scripts.rebuild_precise_index --activate
```

迁移后，管理员应进入“资料中心 → 教材正文 → 引用校准”，确认自动识别的章、节、知识点、PDF 页和印刷页码，再发布教材版本；中央材料需要确认教材/专题关联后才能发布。升级前无法识别层级的补充资料进入“待分类”，不会直接参与新回答。教学班支持主讲教师、协作教师、名单导入、入班审批、分组和同课程同学期唯一在班规则。

模拟 Embedding 仅用于验证入库与检索流程，真实教材检索应配置语义 Embedding 服务。

## 本地验收数据

```bash
cd backend
python -m scripts.seed_demo
```

示例数据包含一门课程、两个章节和一份已向量化的 Markdown 课程资料。上述账号和密码仅用于本地 MVP 验收，部署前必须修改。

## 当前 MVP 边界

- 默认 AI 与 Embedding 均为本地模拟模式，需配置 API 才能评价真实模型效果。
- PDF 支持文本型文件，扫描版需要先 OCR。
- 文档入库使用同步处理，适合 MVP 规模。
- 当前为本地开发服务器，不等同于公网生产部署。

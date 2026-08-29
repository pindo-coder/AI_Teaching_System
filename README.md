# 高校思政课 AI 智能教学辅助平台

面向高校思政课程的 AI 教学辅助平台 MVP。系统围绕课程、章节、知识点和学习阶段组织 AI 能力，而非提供通用聊天入口。

完整的项目定位、用户角色、功能范围、业务闭环、系统架构和当前状态见
[`docs/project-overview.md`](./docs/project-overview.md)。

MVP 阶段 0～5 已完成：用户与课程系统、阶段化 AI 助手、分层 RAG 资料中心、统一错误处理、请求日志、安全校验和验收数据均已具备。

当前版本还包含专题个人笔记、1/2/4/7/15/30 天间隔复习，以及基于 SSE 的 AI 流式输出。相关设计参考与许可说明见 [`THIRD_PARTY_NOTICES.md`](./THIRD_PARTY_NOTICES.md)。

## 项目结构

- `frontend/`：Vue 3、Vite、TypeScript、Vue Router、Pinia、Element Plus
- `backend/`：FastAPI、SQLAlchemy，支持 SQLite/MySQL
- `knowledge_base/`：原始资料与 Chroma 持久化目录（阶段 4 使用）
- `docs/`：架构、API 与开发说明

## 环境要求

- Node.js 24+
- Python 3.11+

## 启动后端

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd presentation_runtime
pnpm install
cd ..
cp .env.example .env
# 已有 SQLite 数据库升级代码后，先执行迁移；新库也可以直接执行。
PYTHONPATH=. alembic upgrade head
uvicorn app.main:app --reload
```

本地使用 SQLite 时，如果通过 `DATABASE_URL` 指定了已有数据库文件，启动前必须对
同一个数据库执行 `PYTHONPATH=. alembic upgrade head`。`create_all()` 只能创建缺失的
表，不能为已经存在的表补充新字段。检查当前迁移版本：

```bash
PYTHONPATH=. alembic current
```

本地密码找回和邮箱验证默认使用 `MAIL_BACKEND=console`，验证码内容会直接输出在后端终端，
无需准备真实发件邮箱。部署到服务器时再切换为 `MAIL_BACKEND=smtp` 并填写 SMTP 发件账号和授权码。

访问：

- 存活检查：`http://localhost:8000/api/v1/health`
- 数据库就绪检查：`http://localhost:8000/api/v1/ready`
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

## 图片与语音输入

Chat 支持图片理解和语音转文字，Agent 暂不接收媒体附件。图片作为用户临时材料，不能替代教材或权威资料；语音会先转成可编辑文字，再进入原有教材 RAG。两项能力均调用阿里云百炼兼容 API，小服务器不加载本地视觉或语音模型。

```env
DASHSCOPE_API_KEY=your-dashscope-key
AI_VISION_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
AI_VISION_MODEL=qwen3-vl-plus

AI_ASR_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
AI_ASR_MODEL=qwen3-asr-flash
```

`DASHSCOPE_API_KEY` 与下方 DashScope Embedding 共用，不需要再申请或配置媒体 Key；如需拆分账号或额度，仍可通过 `AI_VISION_API_KEY`、`AI_ASR_API_KEY` 单独覆盖。默认每轮最多 2 张 JPEG/PNG/WebP，浏览器先将长边压到 2048px，服务端再按 5 MB/张分块落盘并验证文件魔数；录音最长 60 秒、10 MB，支持 WebM/WAV/MP3/MP4/OGG。语音转写成功、图片回答结束后，前端会立即请求删除临时资产。媒体表和迁移同时兼容 SQLite 与 MySQL；Docker 部署会把临时文件写入独立 `ai_media` volume。

## 教师备课 Agent 与教学成果

教师备课工作区采用“设置任务—构建证据—生成课纲—生成成果—预览发布”流程，每次只展示一个阶段，避免把任务、证据、课纲和成果挤在同一窗口。证据快照需要教师确认后才能生成课纲；课纲确认后可以生成可编辑的 PPTX、Word 教案和课堂活动设计。成果生成后仍保持草稿，只有教师在最后一步勾选确认，才会发布到指定教学班。

PPTX 由公开可部署的 PptxGenJS 运行时生成，需要受支持的 Node.js 24+：

```bash
cd backend/presentation_runtime
pnpm install
```

如果后端服务进程找不到 `node`，在 `backend/.env` 中配置绝对路径：

```env
GENERATED_ARTIFACT_DIRECTORY=../knowledge_base/generated_artifacts
PRESENTATION_NODE_BINARY=/usr/bin/node
```

课纲、PPT 内容、教案和课堂活动共用现有 `LLM_API_KEY`；教材检索继续使用现有 Embedding 配置，不需要新增 API Key。PPT 可见页面不展示资料编号或“资料依据”，来源信息仅保留在演讲者备注和后台元数据中，供教师核验。

PPT 采用“教学内容策划 Agent + 视觉设计 Agent”二阶段生成。第一阶段形成逐页教学叙事，第二阶段根据本次专题提炼独有视觉母题、配色和自由画布坐标，再由 PptxGenJS 使用 PowerPoint 原生图形生成可编辑文件。固定版式仅在视觉设计结果校验失败时作为安全回退；程序仍会控制字数、边界和合法颜色，避免自由生成造成文件损坏。

教师还可以在生成前设置使用场景、视觉风格、内容密度、精确页数和课堂互动偏好。页数支持 6～30 页加减或直接输入，内容 Agent 与服务端会共同保证最终文件页数准确。系统在内容与视觉生成后继续执行质量审查，标记文字拥挤、内容遗漏、画布异常等问题；教师可只修改指定页面，或恢复最近 10 个 PPT 版本，不必每次整套重做。

可选的阿里云百炼多模态能力会为 1～3 个适合视觉表达的正文页生成无文字辅助插图，并在模型调用后立即把临时图片下载到本地课件目录。标题页、总结页、政策文件原文页和政治人物肖像不参与自动配图；任何单页生成失败都会自动回退为 PowerPoint 原生图形，不阻断整套课件。配置示例：

```env
PPT_MULTIMODAL_ENABLED=true
# 可复用 DASHSCOPE_API_KEY；如需隔离额度，也可设置独立 Key。
PPT_MULTIMODAL_API_KEY=your-dashscope-key
PPT_MULTIMODAL_BASE_URL=https://dashscope.aliyuncs.com/api/v1
PPT_MULTIMODAL_MODEL=wan2.7-image-pro
PPT_MULTIMODAL_MAX_IMAGES=3
PPT_MULTIMODAL_TIMEOUT_SECONDS=180
```

最后一步支持一次确认后同时发布 PPT 和选定课堂讨论。PPT 会复制到独立发布目录，学生可从课堂互动页下载；讨论会成为该教学班的课堂活动。发布接口不会被 Agent 自动调用，重复向同一教学班发布同一个备课任务会被拒绝。

支持上传 `.pptx` 作为风格参考。首版会提取模板的画幅比例、主题色、字体和版式名称，并交给视觉设计 Agent 使用；上传文件仅对本人可见，管理员可按需设为共享。该能力目前不等同于完整复制 PowerPoint 母版、动画和复杂对象，如需严格沿用学校统一母版，应在导出后通过 PowerPoint 替换主题并人工复核。

## 资料中心与 Embedding

资料中心按“中央材料—教材正文—地方材料”三层管理可核验原文。中央材料仅管理员可导入、确认教材/专题范围并发布；教材继续沿用版本管理、自动专题拆分和 PDF 页码校准；地方材料可由管理员或已审核教师导入，教师资料默认限定到本人教学班。支持可复制文本的 PDF、TXT、Markdown，中央材料还支持公开 HTTPS 原文归档。扫描版 PDF 暂不包含 OCR，应先转为可检索文本。

中央材料支持粘贴多条网址，或上传 CSV、XLSX、XLS 批量预览。系统会识别多工作表、非首行表头、常见中文字段名及 UTF-8/GBK CSV，并允许管理员在预览页调整字段映射、修改单元格、批量补充来源与标签、排除异常行。确认后任务进入后台，用户可离开页面并从任务中心查看持久化进度、处理明细和失败重试；服务重启会恢复未完成批次。缺失的标题、发布机关和日期仅从网页结构化元数据补全，无法核验时明确报错，不由模型猜测。

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
# 先验证接口和实际维数
PYTHONPATH=. python -m scripts.test_embedding
# 在新集合构建全部资料；数量和分层覆盖率全部通过后才会原子切换
PYTHONPATH=. python -m scripts.rebuild_precise_index --activate
PYTHONPATH=. python -m scripts.rebuild_study_note_index
```

教材与个人笔记都会按 Embedding 提供方、模型、实际维度和索引协议指纹进入独立 collection。每次接口返回都会校验向量维数，活动索引清单也会校验相同指纹；不匹配时系统明确中止并要求重建，不再把不同维数写入同一集合。DashScope `text-embedding-v1/v2` 固定按 1536 维处理，`text-embedding-v3/v4` 使用 `EMBEDDING_DIMENSIONS`。

原子切换前的活动清单会保存为 `knowledge_base/chroma/active_index.previous.json`，旧 Chroma collection 也会保留。回退时应同时恢复上一份清单和与其匹配的 Embedding 模型配置；不要只删除 `active_index.json`，否则会进入当前模型对应的全新空集合。

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

初始化脚本会执行 `alembic upgrade head`，适用于 SQLite 和 MySQL；正式环境应使用独立数据库用户，不要使用 root。应用启动不会再尝试为 MySQL 自动补表，数据库版本落后时会给出明确迁移提示。

## 升级现有数据库与教材

已有服务器数据库按以下顺序升级。执行前先备份 MySQL、上传目录和 Chroma 目录：

```bash
cd backend
alembic upgrade head
PYTHONPATH=. python -m scripts.bootstrap_default_class
PYTHONPATH=. python -m scripts.migrate_existing_citations
PYTHONPATH=. python -m scripts.rebuild_precise_index --activate
```

迁移后可执行只读兼容性检查，确认 revision、关键索引、MySQL `LONGTEXT` 和字符集：

```bash
PYTHONPATH=. python -m scripts.check_database_compatibility
```

`20260730_01` 迁移会创建 PPT 风格模板表，`20260731_01` 会创建教学成果发布记录表。升级完成后重启 FastAPI，教师即可在“课程备课 → PPT 生成偏好”上传并选择模板，并在最终核验后发布 PPT 与课堂讨论。

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
- 单文档入库使用同步处理；中央材料批量网址任务单批默认最多 500 条、最多并发处理 2 个批次，可通过环境变量调整。
- 当前为本地开发服务器，不等同于公网生产部署。

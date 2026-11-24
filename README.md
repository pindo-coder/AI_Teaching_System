# 思政红芯 · 高校思政课 AI 智能教学辅助平台

面向高校思政课程的 AI 教学辅助平台，服务于学生学习、教师备课与教学管理、管理员资料治理。系统围绕课程、教材专题、知识点和教学班组织 AI 能力，并将教材依据、学习过程和人工审核纳入业务流程。

## 当前功能

| 场景 | 已有能力 |
| --- | --- |
| 学生学习 | 课前预习、课后巩固、考前冲刺；带教材引用的 AI 流式问答；图片理解与语音转文字；教材批注、专题笔记、复习练习和 1/2/4/7/15/30 天间隔复习 |
| 教学管理 | 教学班、学期、协作教师、名单导入、入班审批和分组；按阅读、AI 学习、笔记、练习和互动等实际行为统计任务完成进度 |
| 教师备课 | 证据确认、课纲确认、可编辑 PPTX、Word 教案、课堂活动；逐页修改、配图调整、断点续作、版本恢复和教师确认发布 |
| 课堂互动 | 教师课堂活动、学生观点提交、自由讨论与回贴，以及已发布课件下载 |
| 资料治理 | 中央材料、教材正文、地方材料三层资料中心；教材版本与页码校准；网址和表格批量导入；权威资料发现、教材匹配、差异证据与人工审核 |
| AI 与 Agent | 按角色和上下文调用受控工具的工作台 Agent；文本、Embedding、视觉、语音和图片生成独立配置、连接测试及调用审计 |

学生和教师可公开注册，教师需经管理员审核后进入教学功能。课程与章节写操作由管理员执行，教师资料和教学成果按用户、教学班及发布状态控制访问。填写邮箱的账号需先完成邮箱验证；支持邮箱验证码找回密码和管理员人工重置。

AI 生成内容用于辅助教学；资料发布、政策变化确认、任务发布和教学成果发布保留人工确认。设计参考与许可说明见 [`THIRD_PARTY_NOTICES.md`](./THIRD_PARTY_NOTICES.md)。

## 项目结构

- `frontend/`：Vue 3、Vite、TypeScript、Vue Router、Pinia、Element Plus
- `backend/app/`：FastAPI API、业务服务、权限控制与 SQLAlchemy 模型
- `backend/alembic/`：SQLite/MySQL 数据库迁移
- `backend/scripts/`：初始化、演示数据、索引重建、PPT 运行时安装与验收脚本
- `backend/presentation_runtime/`：锁定版本的 PPT Master 运行时配置，完整分发安装到 Git 忽略的 `vendor/`
- `backend/tests/`、`frontend/tests/`：后端测试和前端关键流程测试
- `knowledge_base/`：上传资料、Chroma 索引、临时媒体与生成成果的本地持久化目录
- `deploy/`、`docker-compose.yml`：Caddy 网关配置与容器部署
- `docs/`：项目设计、API、部署与专项验收说明

## 环境要求

- 前端：Node.js 24，使用仓库已有的 pnpm 锁文件安装依赖。
- 后端：建议 Python 3.12，与后端 Docker 镜像一致；依赖以 `backend/requirements.txt` 为准。
- 语音输入：需要 FFmpeg 提供的 `ffprobe`。
- PPT 生成与预览：需要完整 PPT Master 分发、LibreOffice、Poppler 和 Noto 中文字体，安装方法见下文。

根目录 `pyproject.toml` 声明 Python 3.13+，其依赖集与 Web 后端不同。下述后端启动流程使用独立虚拟环境和 `backend/requirements.txt`。

## 启动后端

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
# 仅首次创建配置；已有 .env 时直接检查和修改，避免覆盖。
cp .env.example .env
# 启动前编辑 .env，修改 JWT_SECRET_KEY 和 BOOTSTRAP_ADMIN_PASSWORD。
mkdir -p data
# 新库与已有数据库均先执行迁移。
PYTHONPATH=. alembic upgrade head
uvicorn app.main:app --reload
```

以上可启动核心服务；启用语音或 PPT 功能前，还需安装对应系统依赖。配置文件固定从 `backend/.env` 读取；以下后端命令均在 `backend/` 目录、已激活虚拟环境后执行。

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

仅在同时配置 `BOOTSTRAP_ADMIN_USERNAME` 和 `BOOTSTRAP_ADMIN_PASSWORD` 时，应用才会创建尚不存在的管理员；现有同名账号不会被重置密码。首次登录使用自己配置的密码，创建完成后可清空 `BOOTSTRAP_ADMIN_PASSWORD`。

## 启动前端

```bash
cd frontend
cp .env.example .env
corepack enable
pnpm install --frozen-lockfile
pnpm dev
```

访问 `http://localhost:5173`。开发服务器会将 `/api` 请求代理至后端的 8000 端口。

## 测试

```bash
cd backend
python -m pytest
```

```bash
cd frontend
pnpm test:workspace-ai
pnpm test:artifact-progress
pnpm test:agent-progress
pnpm test:lesson-publication
pnpm type-check
pnpm build
```

PPT 的真实导出、字体和预览链路另按下文执行 `verify_presentation_runtime.py --render-smoke`；仅运行模拟模式测试不能代替真实渲染验收。

## 配置原则

后端本地配置参考 `backend/.env.example`，前端参考 `frontend/.env.example`，Compose 部署参考根目录 `.env.production.example`。不要提交真实 `.env`、API 密钥、数据库文件、上传资料或 Chroma 数据。

管理员可在“AI 运行中心”页面配置、测试和启用文本、Embedding、视觉、语音与图片生成能力。通常优先使用数据库中当前生效的能力配置（包括显式关闭），没有保存配置时使用环境配置；因此修改 `.env` 不一定会覆盖管理页面的现有设置。本地垂类模型的功能分流由 `LLM_TEACHER_*` 单独控制。

管理页面保存的 API Key 使用 `AI_CONFIG_ENCRYPTION_KEY` 加密，未设置时使用 `JWT_SECRET_KEY` 派生密钥。部署时应设置独立且稳定的加密密钥；修改用于解密的密钥后，需要重新保存已有 AI 凭据。

## AI 模式

示例配置默认使用 `AI_MOCK_MODE=true` 和 `EMBEDDING_PROVIDER=mock`，用于验证文本生成与检索流程。接入真实文本模型、且未部署本地垂类模型时配置：

```env
AI_MOCK_MODE=false
LLM_TEACHER_ENABLED=false
LLM_API_KEY=your-api-key
LLM_BASE_URL=https://your-provider.example/v1
LLM_MODEL=your-model-name
```

`backend/.env.example` 默认开启 `LLM_TEACHER_ENABLED=true`，将学生学习助手、`note_` 笔记任务和时政研学笔记路由到 `http://127.0.0.1:8001/v1` 的 `sz-teacher-v1` 服务。只有已部署该 OpenAI 兼容服务时才保留开启；教师备课、PPT、教案和 Agent 规划继续使用通用文本能力。需要调整时设置 `LLM_TEACHER_BASE_URL`、`LLM_TEACHER_MODEL` 和 `LLM_TEACHER_FEATURES`。

章节学习助手请求包含课程、专题和学习阶段；工作台 Agent 可先解析上下文或提示选择专题。RAG 仅检索当前用户可见的资料，没有检索到相应教材正文时补充章节正文。`AI_MOCK_MODE` 不会统一关闭视觉、语音和图片生成 API，纯离线验收还应保持这些能力未配置或显式关闭。

## 图片与语音输入

Chat 支持图片理解和语音转文字，Agent 暂不接收媒体附件。图片作为用户临时材料，不能替代教材或权威资料；语音会先转成可编辑文字，再进入原有教材 RAG。默认接入阿里云百炼兼容 API，也可在能力管理中独立配置，小服务器不加载本地视觉或语音模型。非容器环境需安装 `ffprobe`，缺失时语音上传会禁用；浏览器录音需要 localhost 或 HTTPS 安全上下文。

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

PPT 使用单一的 **PPT Master SVG 工作流**：已确认课纲和证据 → 严格逐页方案 → 逐页 SVG 设计与有限修复 → 原生可编辑 PPTX → 最终文件渲染预览。已移除旧 PptxGenJS/自由画布导出链路，不在失败时偷偷切回旧引擎。

完整依赖由 `backend/presentation_runtime/ppt-master.lock.json` 锁定（MIT、版本 6.7.0、提交与完整目录哈希）。安装器保留上游完整分发及署名检查，不在请求期间下载或执行模型生成的程序。

```bash
cd backend
pip install -r requirements.txt
# Ubuntu/Debian（仅安装依赖，不影响数据库）：
sudo apt-get install libreoffice-impress poppler-utils fonts-noto-cjk
python scripts/install_ppt_master.py
PYTHONPATH=. python scripts/verify_presentation_runtime.py
```

GitHub 不通时，在可信机器下载锁文件指定提交的完整源码包，上传后离线安装：

```bash
python scripts/install_ppt_master.py --archive /path/to/ppt-master-source.tgz
```

注意：`presentation_runtime/vendor/` 被 Git 忽略，单独上传 git archive **不会包含运行时**。发布前必须在目标环境按锁文件安装或使用经校验的离线包，再运行检查。Docker 镜像构建时自动完成安装；镜像应在本地/CI 构建，小规格生产服务器只接收产物。已有 node_modules 不再被新课件使用，不要为本次升级贸然删除其他服务依赖。

课件继续使用当前文本模型配置，无需新增文本 API Key。6～30 页精确页数、教师确认发布、教材引用备注、Word 教案与课堂活动入口均保留。上传 PPTX 模板目前作为**配色风格参考**，并非原母版、字体或复杂布局的逐项复刻。

新预览来自最终 PPTX 经 LibreOffice 渲染的 PNG，需登录并通过任务所有权校验后读取。系统检查内容覆盖、原生文字、页数、SVG 结构和非空渲染；这些不是视觉美观或教学事实的自动保证，仍需教师核验。失败时保留已成功成果和旧文件，不填空白页、不静默删要点。单页修改生成独立版本，最近 10 个带文件的版本可直接恢复；历史旧版继续下载，仅有 JSON 而无文件的快照不可恢复。

图解标签必须在逐页方案的 `diagram_labels` 中声明，并逐字取自本页标题、结论或正文；设计阶段允许使用这些标签，不允许自行新增事实。图片默认使用圆角矩形原生裁剪；教师也可选圆形，此时采用方形图源并居中裁剪，图片与边框共用同一几何形状，避免矩形图片叠在圆形装饰框上。

“继续生成未完成部分”会核对任务所有者、输入、证据、模型及提示词指纹，仅复用同一输入下已校验的页面和已下载插图，再重试缺失部分或导出；输入变化、首次升级前的旧草稿或没有可用检查点时会安全重建。主动“重新生成”仍创建新作业。检查点保存在任务私有产物目录，无需数据库迁移。前端分别展示课纲状态与本次成果状态，失败后保留的文件明确标为“上一版”，不把旧文件当作本次成功。

运行配置：

```env
GENERATED_ARTIFACT_DIRECTORY=../knowledge_base/generated_artifacts
PPT_MASTER_DIRECTORY=presentation_runtime/vendor/ppt-master
PPT_OFFICE_BINARY=soffice
# 若本地无系统 Noto 字体，可指定包含官方 NotoSansCJKsc-Regular.otf 的目录：
# PPT_FONT_DIRECTORY=/absolute/path/to/fonts
PPT_EXPORT_TIMEOUT_SECONDS=120
PPT_RENDER_TIMEOUT_SECONDS=300
# 宿主机正式部署使用 systemd；本地/普通容器保持 auto。
PPT_RENDER_ISOLATION=auto
PPT_RENDER_MEMORY_LIMIT_MB=512
PPT_RENDER_MIN_MEMORY_MB=192
PPT_RENDER_RESERVE_MB=128
PPT_RENDER_MEMORY_WAIT_SECONDS=20
PPT_PAGE_REPAIR_ATTEMPTS=2
PPT_JOB_TIMEOUT_SECONDS=1800
```

小规格实例保持后端单 worker，进程内同一时间只处理一套 PPT，避免多个 LibreOffice/模型作业争抢内存；多进程/多实例部署需要外部队列。每页设计失败最多修复 2 次，整套作业 30 分钟预算；取消在阶段和页面边界生效，不强行中断已发送的模型请求。

原生导出另有同一成果根目录的跨进程文件锁。Linux systemd 宿主机可将编译、PDF 渲染、PNG 转换分别放入受限瞬态单元，保留 Web 内存余量；瞬时资源不足先有界等待，持续不足则保留断点。PDF 渲染单独默认 5 分钟，不是整套生成仅限 5 分钟。普通容器/本地的 process 模式不等同于独立硬资源隔离。具体权限、限制和验收见 [PPT 渲染资源保护](docs/ppt-render-isolation.md)。

上线前还应运行 `PYTHONPATH=. python scripts/verify_presentation_runtime.py --render-smoke`，以临时公开合成内容实际完成中文 PPTX → PDF → PNG 检查；不调用付费模型、不写数据库，临时文件自动清理。仅检查工具安装不等于渲染链路已通过。正式切换流程见 [PPT 上线检查清单](docs/ppt-release-checklist.md)。

新版发布请求绑定 `expected_ppt_revision`；版本已变化时返回 409，必须重新核验。重生成失败后保留的上一版必须另行确认 `allow_previous_ppt`，补生成教案不会清除这项标记。原有无版本号的旧格式课件仍兼容发布；已发布课件使用独立副本，学生下载保留教师指定文件名。选择历史版本只是预览，不直接发布；需先设为当前版本。一个任务仍只允许向同一教学班发布一次，不静默覆盖已经发布给学生的内容。

成果存储维护默认仅输出候选清单：`PYTHONPATH=. python scripts/maintain_ppt_artifacts.py --days 30`。只有先停止后端且不存在活动任务，才可传入 `--apply --offline`，把超过保留期且未被数据库引用的原生版本、非最新检查点移入 `.ppt-quarantine/<批次号>`。当前版本、历史引用、发布副本、旧格式文件、公共配图及最新检查点均不清理；符号链接和损坏检查点保守跳过。可用 `--restore <批次号> --offline` 恢复，拒绝覆盖原路径。不自动执行、不永久删除；**同盘隔离不会立即释放磁盘空间**，确认备份与保留期后再由管理员另行处理隔离区。

课件风格先从教学专题提炼关键词、视觉意象与配色缘由，再统一整套图文画风，不把“现代课堂蓝”当作通用默认风格。每页先声明 `visual_brief`：教学意图、逐字来自正文的概念依据、插图/图解/文字的选择。流程、分类与抽象关系优先使用可编辑图解，具体情境使用插图，并列出必需可见元素与区别于其他图的场景。按页数设定最多 1～3 张插图的预算（6 页最多 2 张），不是必须用满的配额。

配图只填充已校验且不遮挡正文的槽位。默认复用已配置的 `vision` 能力对生成图做教学语义复核；明确不符合时不嵌入，保留文字课件并提示原因。不配置视觉能力、复核异常或关闭复核时显示“待教师核验”，不冒称通过。复核属于模型辅助判断，不能证明理论、历史事实或素材授权正确。插图和裁剪边框分别由图像模型与应用负责，避免把图片容器画进图源。

教师在逐页预览的“配图设置”中可查看实际发送的提示词、编辑场景描述并仅重生成一张图。这是后台异步任务，原课件保留至新图及成品验证成功，再创建可恢复的新版本；正文、SVG 版式与其他图片不变。旧版本冲突、取消、服务重启或出图失败不会覆盖原文件。此入口只处理已有插图槽位，不把图解自动改为插画。

不配置或配图失败时显示明确提示，导出时移除未填充空槽，保留同一 SVG 工作流。已生成图片进入私有检查点；部分配图失败后可仅补未完成插图，不重复请求已经成功的图片。配置示例：

```env
PPT_MULTIMODAL_ENABLED=true
# 可复用 DASHSCOPE_API_KEY；如需隔离额度，也可设置独立 Key。
PPT_MULTIMODAL_API_KEY=your-dashscope-key
PPT_MULTIMODAL_BASE_URL=https://dashscope.aliyuncs.com/api/v1
PPT_MULTIMODAL_MODEL=wan2.7-image-pro
PPT_MULTIMODAL_MAX_IMAGES=3
PPT_MULTIMODAL_TIMEOUT_SECONDS=180
PPT_IMAGE_REVIEW_ENABLED=true
```

最后一步支持一次确认后同时发布 PPT 和选定课堂讨论。PPT 会复制到独立发布目录，学生可从课堂互动页下载；讨论会成为该教学班的课堂活动。发布接口不会被 Agent 自动调用，重复向同一教学班发布同一个备课任务会被拒绝。

支持上传 `.pptx` 作为风格参考。解析时会记录画幅比例、主题色、字体和版式名称，当前 SVG 生成流程主要应用其中的配色；上传文件仅对本人可见，管理员可按需设为共享。该能力目前不等同于完整复制 PowerPoint 母版、字体、动画和复杂对象，如需严格沿用学校统一母版，应在导出后通过 PowerPoint 替换主题并人工复核。

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
EMBEDDING_MODEL=text-embedding-v4
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

## 权威资料发现与教材匹配

管理员可维护权威 HTTPS 来源白名单，手动启动发现任务，查看网页正文快照、去重结果、教材章节匹配和差异证据，再决定是否导入正式资料或确认变化提醒。资料候选与政策变化由管理员审核，候选发现不会自动修改已发布教材。

基础部署使用 BM25、向量与中文词项召回、RRF 融合和确定性门控。BGE 精排与 NLI 为可选能力，依赖位于 `backend/requirements-matching.txt`，默认不安装、不启用。小规格服务器应先使用基础路径；相关阈值和模型开关见 `backend/.env.example`。

自动调度默认关闭：`AUTHORITY_DISCOVERY_SCHEDULER_ENABLED=false`。先确认来源白名单和抓取质量，再按需开启。流程及匹配说明见 [资料发现第一阶段](docs/authority-discovery-phase1.md)与[教材匹配说明](docs/authority-discovery-phase2.md)。

## 切换 MySQL

本地开发默认使用 SQLite；服务器可以在 `backend/.env` 中切换。容器部署请使用外部 MySQL 主机名，`127.0.0.1` 仅适用于后端直接运行在数据库所在宿主机：

```env
DATABASE_URL=mysql+pymysql://ai_teaching:密码@mysql.example.internal:3306/ai_teaching?charset=utf8mb4
```

先创建数据库和用户，再执行初始化：

```bash
cd backend
PYTHONPATH=. python scripts/init_database.py
```

初始化脚本会执行 `alembic upgrade head`，适用于 SQLite 和 MySQL；正式环境应使用独立数据库用户，不要使用 root。应用启动不会再尝试为 MySQL 自动补表，数据库版本落后时会给出明确迁移提示。

## 升级现有数据库与教材

已有数据库升级代码时，先备份业务数据库、上传目录、Chroma 索引与生成成果，再执行结构迁移：

```bash
cd backend
PYTHONPATH=. alembic upgrade head
```

只有从尚未引入教学班或精确引用的早期版本升级时，才按需执行以下数据迁移；普通版本更新不必重复执行。`bootstrap_default_class` 会把旧用户与教学数据归入默认试点班，并将已有教师设为已审核，执行前应确认这符合原系统的账号状态。

```bash
PYTHONPATH=. python -m scripts.bootstrap_default_class
PYTHONPATH=. python -m scripts.migrate_existing_citations
# Embedding 或索引协议变化时，还需重建相应索引。
PYTHONPATH=. python -m scripts.rebuild_precise_index --activate
PYTHONPATH=. python -m scripts.rebuild_study_note_index
```

迁移后可执行只读兼容性检查，确认 revision、关键索引、MySQL `LONGTEXT` 和字符集：

```bash
PYTHONPATH=. python -m scripts.check_database_compatibility
```

以当前代码的 Alembic `head` 为准，完整执行迁移；PPT 模板、教学成果、邮箱验证、教材批注及任务完成条件等均有对应结构变更，不应只执行早期 PPT 相关迁移。升级完成后重启后端，并同步更新前端。

迁移后，管理员应进入“资料中心 → 教材正文 → 引用校准”，确认自动识别的章、节、知识点、PDF 页和印刷页码，再发布教材版本；中央材料需要确认教材/专题关联后才能发布。升级前无法识别层级的补充资料进入“待分类”，不会直接参与新回答。教学班支持主讲教师、协作教师、名单导入、入班审批、分组和同课程同学期唯一在班规则。

模拟 Embedding 仅用于验证入库与检索流程，真实教材检索应配置语义 Embedding 服务。

## 本地验收数据

```bash
cd backend
python -m scripts.seed_demo
```

首次对空库执行时，会创建一门课程、三个专题、一份已向量化的 Markdown 示例资料，以及学生账号 `student_demo` / `Student@123456`。管理员仍由 `BOOTSTRAP_ADMIN_*` 配置创建，密码以自己的 `.env` 为准；脚本末尾打印的固定管理员密码不能作为登录依据。已有同名课程或学生账号会复用，已有课程不会自动补齐专题。

演示脚本会写入数据库并入库或重建示例资料索引，仅用于本地验收。运行前确认使用本地数据库和 `EMBEDDING_PROVIDER=mock`。

## 部署

仓库提供 Docker Compose 部署：Caddy 负责 HTTPS，前端由 Nginx 提供静态文件并代理 API，后端连接外部 MySQL。Compose 不包含 MySQL 服务，数据库与业务账号需提前准备。

根目录 `.env.production.example` 是部署配置模板；必须填写数据库地址、JWT 密钥、初始管理员密码和 SMTP 配置，并将站点地址及 CORS 改为实际访问地址。Compose 使用 `--env-file .env.production` 做变量插值，只会把 `docker-compose.yml` 中显式声明的变量传入容器。增加本地模型、AI 加密密钥或其他自定义配置时，应同时补充后端容器的环境变量。

镜像应在本地或 CI 构建，再交付到生产服务器；宿主机部署保持后端单 worker。数据库、上传资料、Chroma 索引、生成成果与发布副本应一起备份。具体步骤见 [部署说明](docs/deployment.md)、[PPT 上线检查清单](docs/ppt-release-checklist.md)和 [PPT 渲染资源保护](docs/ppt-render-isolation.md)。

## 当前边界

- 示例配置的文本 AI 与 Embedding 均为模拟模式；真实模型效果需要配置服务后单独验收。本地学习模型服务不随项目自动部署。
- PDF 支持文本型文件，扫描版需要先 OCR。
- 单文档入库使用同步处理；中央材料批量网址任务单批默认最多 500 条、最多并发处理 2 个批次，可通过环境变量调整。
- 后台任务调度与 PPT 作业以单进程部署为基线，多进程、多实例需要外部任务队列和全局并发控制。
- PPT 风格模板主要提供配色参考；最终渲染与结构检查不代替教师对内容、版式和配图的审核。
- 仓库包含部署配置，但本地启动、自动化测试通过不代表公网环境、真实模型和数据恢复已完成验收。

## 相关文档

- [API 说明](docs/api.md)
- [部署说明](docs/deployment.md)
- [PPT 运行时](backend/presentation_runtime/README.md)
- [PPT 断点续作](docs/ppt-checkpoint-resume.md)
- [第三方许可与设计参考](THIRD_PARTY_NOTICES.md)

早期项目定位和架构演进可参考 [项目说明](docs/project-overview.md)与[开发说明](docs/development.md)；其中阶段编号、测试数量和旧 PPT 引擎描述属于历史记录，当前运行依赖与启动方式以上文及代码为准。

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
# 启用课件生成时还需 LibreOffice、Poppler、中文字体，详见下方 PPT 运行时章节。
python scripts/install_ppt_master.py
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
PPT_PAGE_REPAIR_ATTEMPTS=2
PPT_JOB_TIMEOUT_SECONDS=1800
```

小规格实例保持后端单 worker，进程内同一时间只处理一套 PPT，避免多个 LibreOffice/模型作业争抢内存；多进程/多实例部署需要外部队列。每页设计失败最多修复 2 次，整套作业 30 分钟预算；取消在阶段和页面边界生效，不强行中断已发送的模型请求。

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

# 权威资料发现（第一阶段）

第一阶段提供“白名单来源 → 后台发现 → 正文快照 → 去重 → 候选池 → 管理员确认”的闭环。候选材料在审核前不会进入正式中央材料检索范围。

## 管理入口

管理员登录后进入“资料动态”（`/material-discovery`），可以：

- 查看并勾选中国政府网、教育部、求是网等默认来源；
- 新增、编辑、启停白名单来源，并配置抓取周期、请求间隔、全文权限与提醒权限；
- 按主题词启动后台发现任务，页面关闭后任务仍会继续；
- 查看来源抓取状态、任务阶段、正文和待审核数量；
- 停止运行中的任务，查看失败原因并重新排队；
- 打开候选材料原文，查看正文快照和相关性说明；
- 将候选材料驳回、标记重复，或选择教材后发布到中央材料层。

## API

- `GET/POST/PATCH /api/v1/knowledge/discovery/sources`
- `POST/GET /api/v1/knowledge/discovery/jobs`
- `POST /api/v1/knowledge/discovery/jobs/{id}/retry`
- `POST /api/v1/knowledge/discovery/jobs/{id}/cancel`
- `GET /api/v1/knowledge/discovery/candidates`
- `GET /api/v1/knowledge/discovery/candidates/{id}/snapshots`
- `POST /api/v1/knowledge/discovery/candidates/{id}/review`

所有接口仅管理员可用。发布动作复用现有中央材料流程，会保存来源网址、正文快照和知识库索引。

## 来源与定时调度

来源表支持 HTML 栏目、RSS 和 Sitemap 三种适配器。默认来源只用于初始化白名单，管理员可以停用或调整抓取周期。栏目标题只用于优先排序，系统会读取正文后再次核验主题词，避免“标题未写主题词”造成漏抓，也避免仅凭来源等级收录无关材料。

定时调度默认关闭，确认来源配置后在 `backend/.env` 开启：

```dotenv
AUTHORITY_DISCOVERY_SCHEDULER_ENABLED=true
AUTHORITY_DISCOVERY_SCHEDULER_POLL_SECONDS=300
AUTHORITY_DISCOVERY_MAX_RUNNING=1
AUTHORITY_DISCOVERY_MAX_QUEUED=5
AUTHORITY_DISCOVERY_MAX_LINKS_PER_SOURCE=20
AUTHORITY_DISCOVERY_COOLDOWN_MINUTES=30
AUTHORITY_DISCOVERY_DAILY_FETCH_LIMIT=300
AUTHORITY_DISCOVERY_REQUEST_INTERVAL_SECONDS=3
AUTHORITY_DISCOVERY_MIN_RELEVANCE_SCORE=0.55
AUTHORITY_DISCOVERY_MIN_ASSOCIATION_SCORE=0.45
AUTHORITY_DISCOVERY_MIN_EXTRACTION_QUALITY=0.60
AUTHORITY_DISCOVERY_IMPORTANCE_THRESHOLD=0.60
```

调度器每个来源按 `fetch_interval_minutes` 创建任务；系统初始化的三个默认来源周期为 1440 分钟（每日一次），管理员可以单独调整。进程内只有一个受控 dispatcher，默认最多运行 1 个发现任务、排队 5 个任务。相同用户、来源、关键词和日期范围的手动任务在冷却时间内不会重复创建。单个来源失败会记录错误并继续处理其他来源；达到每日正文抓取上限后，剩余来源留到下一次任务处理。正式部署前建议先手动执行一次，确认正文解析与来源域名均符合预期。

候选材料的“主题相关度”不再混入来源等级；来源等级只参与权威性排序。系统会先检查正文质量，再应用主题相关度阈值和教材关联度阈值，未达到阈值的材料只计入任务的过滤统计，不进入待审核队列。候选列表按教学重要度排序，并展示正文质量、教材关联度、主题相关度和最近抓取时间。

任务开始前会通过数据库条件更新原子抢占排队记录，避免同一任务被多个 Web 进程重复执行。前端仅在确有排队或运行任务时每 10 秒读取一次轻量进度，页面进入后台或队列清空后停止查询；任务完成会立即唤醒 dispatcher 处理下一项。

生产环境建议使用单进程 Uvicorn（`workers=1`）。如果后续需要多实例或多 Worker，应将 dispatcher 迁移到 Redis 队列并增加分布式锁，避免多个进程重复抓取同一来源。

## 数据表

- `source_registries`：管理员来源白名单；
- `discovery_jobs`：发现任务与进度；
- `material_candidates`：待审核候选材料；
- `material_snapshots`：每次抓取的原文快照。

后续阶段会在候选池上增加全教材关联、确定性段落差异对比、政策变化表和教师提醒，不改变当前三层知识库的检索优先级。

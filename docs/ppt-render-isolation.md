# PPT 渲染资源保护

本次不修改教学内容、字体、成图配置、数据库结构或断点身份。已有页面与有效插图可继续复用。

## 分开的限制

- 整套工作流仍为 `PPT_JOB_TIMEOUT_SECONDS=1800`，在阶段切换和模型流消费时检查，不把它冒称为独立操作系统强制期限。
- 编译、检查及栅格化命令仍使用 `PPT_EXPORT_TIMEOUT_SECONDS=120`。
- LibreOffice 转 PDF 单独使用 `PPT_RENDER_TIMEOUT_SECONDS=300`，可配置 30–600 秒。
- 内核文件锁使同一成果根目录一次仅有一个导出；异常退出自动释放，等待超时保留断点，不重复调用模型。

## Linux systemd 宿主机

生产设置 `PPT_RENDER_ISOLATION=systemd`。需要 cgroup v2、memory/cpu 控制器、systemd-run/systemctl，以及当前服务用户创建瞬态服务的权限。
没有权限或环境不支持时拒绝执行，不自动降级成不受限进程。不需要也不应给 Web 用户配置无限制的 sudo。

PPT 编译、LibreOffice 与 Poppler 分别运行在随机命名的 `ai-ppt-render-*.service`，与 Web 服务不共用单元：

- `MemoryMax` 默认最多 512 MiB，且按可用内存减去 128 MiB 预留动态调低；LibreOffice 不足 192 MiB 预算时不启动。该预留是在已运行的网站、MySQL 等实际用量之外额外保留，并非把 Web 总内存限制为 128 MiB。
- 导出入口、编译与 PNG 缩略图转换的最低预算为 128 MiB；只有真正启动 LibreOffice 时才要求 192 MiB。不在编译入口提前要求 Office 预算，避免小服务器长期卡在尚未启动渲染的门槛。
- 瞬时资源不足时最多等待 `PPT_RENDER_MEMORY_WAIT_SECONDS=20` 秒，不启动额外进程；资源恢复再继续，持续不足则保留断点。
- 内存读取结合 MemAvailable 与当前 cgroup/祖先剩余额度；Linux 读取失败时不绕过检查。资源不足日志和提示包含当前可用量、额外预留及本阶段最低预算，避免将准入拒绝误判为渲染进程已经 OOM。
- `MemorySwapMax=0`，默认 `CPUQuota=100%`（一个逻辑核）、`TasksMax=64`，降低 CPU/IO 优先级。
- 独立 `RuntimeMaxSec` 与 `TimeoutStopSec=5`，`KillMode=control-group`、`OOMPolicy=kill`。
- 子任务不继承 Web 服务的数据库/模型密钥；只传入原有允许的运行时、字体环境变量。
- 超时、异常、取消/中断后停止本次随机单元，同时清理启动客户端进程组；不根据进程名杀其他 LibreOffice。

资源限制用于保护网站，不保证小内存上所有课件都能成功。若达到上限，应保留成果、增加资源或迁移渲染节点，不能关闭保护重试。
`MemoryMax` 限的是独立渲染任务，不能把同样限制直接施加到整个 Web 服务上。

## 本地与容器

`auto` 在可检测到 systemd/cgroup v2 的 Linux 上选择 systemd；其他环境使用 `process`。
`process` 保留文件锁、Linux 内存准入、进程组清理和有界超时，但不是独立的硬内存/CPU 隔离。
macOS 本地不读取 Linux 内存信息。普通 Compose 无 systemd，不能把配置写成 systemd 后假定能工作，
也不能把共享后端容器的总内存限制冒称为独立渲染保护。生产容器需单独渲染 worker/容器及配额。

## 验证与部署

```bash
cd backend
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/test_ppt_process.py tests/test_ppt_checkpoint.py tests/test_ppt_resume_images.py tests/test_ppt_workflow.py
```

本地故障注入覆盖独立单元参数、低内存拒绝、锁竞争、超时/异常清理和已有插图复用；不能冒称真实 Linux cgroup 验收。
宿主机另做小额内存限制/超时探针与中文真实渲染，持续检查公网 ready。问题课件验证使用已有断点，不调用文本或成图模型。

先在候选代码目录测试，再备份待替换代码和 systemd 配置；切换前确认无排队/运行任务。异常恢复备份，不恢复旧数据库覆盖用户新数据。
没有数据库迁移或前端发布，网页字体、已有成果和所有 AI 配置保持不变。

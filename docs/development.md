# 开发说明

## 环境要求

- **后端**：Python 3.12（与生产容器及 CI 一致）
- **前端**：Node.js 24+ 与 pnpm 10+
- **可选系统依赖**（仅本地运行课件成品渲染验收时需要）：LibreOffice（`soffice`）、Poppler（`pdftoppm`）、`ffprobe`

## 本地开发启动

### 1. 后端

```bash
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env
# 初始化或升级本地数据库结构
PYTHONPATH=. .venv/bin/alembic upgrade head
# 启动开发服务
PYTHONPATH=. .venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

> 生产镜像只安装 `backend/requirements.txt`；测试与静态检查工具（`pytest`、`ruff`）维护在 `backend/requirements-dev.txt`。

### 2. 前端

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

## 质量门禁与本地验证

提交前建议在本地执行与 GitHub Actions CI（`.github/workflows/ci.yml`）一致的检查：

```bash
# 后端静态检查（高信号语法与未定义名称检查）
ruff check --config backend/pyproject.toml backend/app backend/tests

# 后端单元测试（本地无 LibreOffice/Poppler 时跳过 3 个课件成品渲染用例）
cd backend
PYTHONPATH=. .venv/bin/pytest -q \
  --ignore=tests/test_ppt_workflow.py \
  --ignore=tests/test_ppt_process.py \
  --ignore=tests/test_agents.py

# 前端测试、类型检查与生产构建
cd frontend
pnpm test
pnpm type-check
pnpm build
```

专项工作流：
- MySQL 迁移回归：`.github/workflows/mysql-migrations.yml`
- PPT 课件渲染全链路验收（含 LibreOffice/Poppler）：`.github/workflows/presentation-workflow.yml`

## 开发约定

- **命名规范**：后端 Python 模块使用 `snake_case`，前端 Vue 组件使用 `PascalCase`。
- **配置与密钥**：敏感配置及环境差异项仅写入 `.env` / `.env.production`，严禁提交真实密钥、公网 IP 或数据库文件到版本库。
- **API 规范**：所有接口统一使用 `/api/v1` 前缀；SSE 错误帧只返回脱敏提示，不向外暴露原始异常堆栈。
- **数据库迁移**：模型字段变更必须通过 Alembic 生成并验证迁移脚本（同时兼顾 SQLite 与 MySQL 兼容性）；`backend/data/` 下的本地 SQLite 文件、上传资料与 Chroma 索引均不纳入 Git。
- **可观测性**：每个 HTTP 响应自动携带 `X-Request-ID`，并通过 `ContextVar` 注入所有服务端日志（`[req=<id>]`），便于按请求串联排查问题。
- **安全边界**：媒体访问使用短期签名令牌，鉴权依赖服务端角色与 `token_version`；日志不得记录 API 密钥、重置令牌或明文密码。

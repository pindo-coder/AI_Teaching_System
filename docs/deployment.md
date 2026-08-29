# Docker 部署说明

## 服务器要求

- Ubuntu Server 22.04 或 24.04
- 推荐 4 核 CPU、8 GB 内存、100 GB SSD
- Docker Engine 24+ 与 Docker Compose v2
- 安全组开放 22、80、443（含 443/UDP，可用于 HTTP/3）
- 正式公网部署需有一个已解析到服务器公网 IP 的域名

## 首次部署

```bash
git clone https://github.com/pindo-coder/AI_Teaching_System.git
cd AI_Teaching_System
cp .env.production.example .env.production
```

编辑 `.env.production`，至少修改：

```env
JWT_SECRET_KEY=足够长的随机字符串
BOOTSTRAP_ADMIN_PASSWORD=强管理员密码
DATABASE_URL=mysql+pymysql://用户名:密码@外部MySQL主机:3306/数据库名?charset=utf8mb4
APP_SITE_ADDRESS=teaching.example.edu.cn

# 密码找回邮件（生产不能使用 console）
MAIL_BACKEND=smtp
MAIL_HOST=smtp.example.edu.cn
MAIL_PORT=465
MAIL_USERNAME=发件邮箱账号
MAIL_PASSWORD=发件邮箱授权码
MAIL_FROM=no-reply@example.edu.cn
MAIL_USE_SSL=true
PASSWORD_RESET_URL=https://你的域名/reset-password
# 验证页面地址（验证码邮件不再生成验证链接，保留配置仅供兼容）
EMAIL_VERIFICATION_URL=https://你的域名/verify-email
```

Compose 不启动内置 MySQL。`DATABASE_URL` 中的主机必须能从 `backend`
容器访问，例如云数据库的内网 DNS 或同一 Docker 网络中的独立数据库服务名；
不要使用 `127.0.0.1` 或 `localhost`，它们在容器中指向后端容器自身。首次启动时
后端会先执行 `alembic upgrade head`，因此数据库和最小权限业务账号需要提前创建。

本次认证升级新增邮箱验证、密码重置令牌和会话版本字段。没有邮箱的旧账号仍可由
管理员生成临时密码；临时密码登录后必须修改。

启动：

```bash
docker compose --env-file .env.production up -d --build
docker compose ps
docker compose logs -f --tail=100
```

`APP_SITE_ADDRESS` 填写正式域名后，Caddy 会自动申请并续期证书，访问
`https://你的域名/`。请确保域名的 A/AAAA 记录已指向本机，80 与 443 端口可从
公网访问；否则证书签发会失败。暂时没有域名的内网或 IP 验证环境可保留 `:80`，
通过 `http://服务器IP/` 访问，但这不符合正式公网验收要求。

公网只暴露 Caddy 的 80/443，前端 Nginx 和后端均仅在 Compose 内网开放；API 继续
经前端 Nginx 的 `/api/` 转发，数据库和 Chroma 不开放公网端口。证书和 Caddy
运行配置分别持久化在 `caddy_data`、`caddy_config` volume 中。

### 暂无域名时使用公网 IP 证书

Let's Encrypt 的 `shortlived` ACME profile 支持签发公网 IP 证书，有效期约 160
小时，因此必须依赖 Caddy 持续运行和自动续期。它适合作为申请、备案正式域名前的
试用方案。以当前服务器为例，在 `.env.production` 中配置：

```env
APP_SITE_ADDRESS=47.105.125.153
CADDYFILE_PATH=./deploy/Caddyfile.ip
```

然后执行上面的 Compose 启动命令，并确保阿里云安全组和主机防火墙同时允许
80/TCP、443/TCP；443/UDP 仅用于 HTTP/3，可选。证书首次签发后访问
`https://47.105.125.153/`。不要手工删除 `caddy_data` volume，否则会丢失 ACME
账户和现有证书。取得已备案域名后，应将地址换成正式域名，并恢复
`CADDYFILE_PATH=./deploy/Caddyfile`，使用常规域名证书。

若服务器已由宿主机 Nginx 占用 80 端口，不要启动 Compose 网关抢占端口。可使用
`deploy/Caddyfile.ip-proxy` 让 Caddy 仅监听 443，并设置
`APP_UPSTREAM=127.0.0.1:80`。该配置关闭 HTTP challenge，使用 443 上的
TLS-ALPN challenge 签发证书，同时以 `default_sni` 兼容不发送 SNI 的裸 IP 客户端。

镜像固定包含 Node.js 24 LTS、PPT 渲染脚本和生产依赖。构建阶段会检查脚本可解析、
`pptxgenjs` 可加载，并验证非 root 运行用户能写入教学成果目录。部署后可再次执行：

```bash
docker compose --env-file .env.production run --rm --no-deps backend \
  python scripts/verify_presentation_runtime.py
```

镜像同时包含 `ffprobe`。录音上传后由服务端读取真实时长，不采用浏览器上报值；
临时图片和录音默认每位用户合计不超过 50 MB，并在 24 小时后由启动清理及请求侧
清理共同删除。非容器部署必须安装 `ffprobe`，否则语音入口会保持安全禁用。

## 更新版本

```bash
git pull --ff-only
docker compose --env-file .env.production up -d --build
```

## 数据备份

业务数据库位于外部 MySQL；上传资料、临时媒体、Chroma 和生成的 PPTX/Word
教学成果分别存放在 Docker volume 中。其中 `generated_artifacts` 包含草稿、模板和
已发布课件，必须纳入备份。生产试点至少每日执行数据库及云盘快照；重要教材原文件
建议额外备份到对象存储。

查看 volume：

```bash
docker volume ls
```

不要执行 `docker compose down -v`，该命令会删除业务数据。

## 时间与历史数据兼容

- 已明确时间基准的新字段使用 UTC naive；为避免让未标记的历史 `func.now()` 字段出现新旧基准混用，升级不会全局修改 MySQL 会话时区。
- JSON/SSE 只对已知 UTC 或自带 offset 的时间点补充 `Z`/offset；来源不明的历史 naive 时间保留原样，不猜测时区。
- 中国权威 RSS 未携带时区或使用 `CST` 时，按中国标准时间（UTC+8）解释；服务端生成的研学笔记也按该业务时区显示来源时间。
- 旧版任务截止时间和 RSS 发布时间曾以中国本地 wall time 写入。升级只增加时间基准标记，保留原值并在读取时换算，不自动回填或改写历史时间。
- 其他历史 naive 时间可能来自 UTC、宿主机本地时间或数据库会话时间，无法仅凭数值可靠判断来源。升级不会批量平移这些字段；如确需清理，应先备份、抽样核对原部署时区，再执行经过审核的一次性脚本。

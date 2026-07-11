# Docker 部署说明

## 服务器要求

- Ubuntu Server 22.04 或 24.04
- 推荐 4 核 CPU、8 GB 内存、100 GB SSD
- Docker Engine 24+ 与 Docker Compose v2
- 安全组开放 22、80；配置 HTTPS 后开放 443

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
```

启动：

```bash
docker compose --env-file .env.production up -d --build
docker compose ps
docker compose logs -f --tail=100
```

访问 `http://服务器公网IP/`。API 只通过 Nginx 的 `/api/` 暴露，数据库和 Chroma 不开放公网端口。

## 更新版本

```bash
git pull --ff-only
docker compose --env-file .env.production up -d --build
```

## 数据备份

业务数据库、上传资料和 Chroma 分别存放在三个 Docker volume 中。生产试点至少每日执行云盘快照；重要教材原文件建议额外备份到对象存储。

查看 volume：

```bash
docker volume ls
```

不要执行 `docker compose down -v`，该命令会删除业务数据。

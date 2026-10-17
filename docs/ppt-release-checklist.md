# PPT 原生工作流上线检查清单

适用于 `codex/ppt-generation-upgrade`。此清单不是已经完成部署的证明；各目标环境需单独验收。

## 1. 发布物与兼容

- 将新增的 `ppt_*` 服务、`lesson_artifact_state.py`、schema、前端组件/工具、脚本、测试和锁文件纳入提交。先核对 `git status --short`，不要用仅包含已跟踪差异的包遗漏未跟踪新文件。
- 前后端作为同一版本发布；缓存旧前端的客户端收到版本未绑定/变更 409 时，刷新后重新确认，不能取消服务端校验。
- 运行时 vendor 和字体不在 Git 包中。按锁文件安装完整 PPT Master，离线安装时校验完整分发，不复制未知版本或只有一个导出脚本。
- 新增依赖包含 Python 包、LibreOffice Impress、Poppler 和 Noto CJK；旧 Node/PptxGenJS 依赖不能代替。不要删除旧环境，保留回滚条件。
- 本次无数据库迁移。旧文件保持原路径；旧格式支持下载、内容摘要和发布，单页修改需重新生成。仅 JSON 的历史快照不可恢复文件。
- 上传模板只作为配色参考，不承诺原母版/动画复刻。教学内容及图片仍由教师核验。

## 2. 自动验收

后端在隔离库/临时目录运行：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/test_ppt_workflow.py tests/test_agents.py \
  tests/test_agent_run_events.py \
  tests/test_ppt_checkpoint.py tests/test_ppt_resume_images.py \
  tests/test_lesson_publication_safety.py tests/test_ppt_retention.py \
  tests/test_ppt_mysql_integration.py \
  tests/test_small_server_multimodal_hardening.py tests/test_container_deployment_contract.py
```

`test_ppt_mysql_integration.py` 未设置 `PPT_MYSQL_TEST_URL` 时跳过，不能称为 MySQL 实测通过。
CI 使用专用 MySQL 8.0 服务。手动运行只允许本机 `ppt_ci` 用户的 `ppt_workflow_ci` 可丢弃测试库；
测试会创建/清空该专用库的表，绝不能传入生产连接。

成图密钥轮换与仅补缺图的断点规则、v4 兼容范围见 [PPT 断点与缺失插图补全](ppt-checkpoint-resume.md)。

前端在 `frontend/` 运行：

```bash
corepack pnpm test:artifact-progress
corepack pnpm test:agent-progress
corepack pnpm test:lesson-publication
corepack pnpm test:workspace-ai
corepack pnpm build
```

## 3. 目标服务器预检（先不切换）

- 为当前代码、前端 dist、数据库和生成成果目录做可恢复备份，记录当前版本、服务启动方式及端口。
- 在独立候选版本目录/虚拟环境准备依赖，不覆盖 `.env`、数据库、知识库、模型配置和运行中任务。
- 使用目标服务实际用户、解释器、PATH 和候选环境执行：

```bash
PYTHONPATH=. /候选虚拟环境/bin/python -m scripts.check_database_compatibility
PYTHONPATH=. /候选虚拟环境/bin/python scripts/verify_presentation_runtime.py --render-smoke
```

第一条只读检查目标数据库版本/字段/索引；第二条实际检查中文渲染，不请求 AI，不写数据库，临时文件自动清理。
确认 systemd 环境能找到 `soffice`、`pdftoppm`、`fc-match`，成果目录可写。
保持后端单 worker；内存不足或依赖检查不通过，不接入付费生成作业。

## 4. 切换与业务验收

- 等待/取消活动任务后再切换，避免重启中断模型生成；原子替换前端，前后端使用同一发布版本。
- 检查服务、`/api/v1/ready`、真实站点 Host/SNI 和静态资源版本，不只检查 localhost 默认虚拟主机。
- 使用受控测试账号及公开合成资料，真实生成至少一套 6 页 PPT，验证自定义名称、中文字形、下载与 PNG 预览；需要配图则验证配置的真实图像服务。
- 在专用测试教学班发布，确认学生下载文件名及内容；不能向真实教学班做冒烟发布。
- 核验旧课件下载、历史预览/恢复、错误版本 409，以及失败后发布上一版必须额外勾选。
- 观察生成期间峰值内存、耗时、磁盘和服务日志，再决定开放范围。无压测记录不能承诺小规格服务器并发容量。

## 5. 回滚与维护

异常时停止接入新作业，将后端代码/环境与前端一起回退至备份版本；不做数据库 downgrade，保留所有新旧成果文件和现场日志。
旧后台可能不理解新 JSON 的编辑结构，回滚后不要修改新版课件；可保留下载并等待新版修复。

维护脚本默认 dry-run，线上不自动清理。仅在后端停止且没有排队/运行任务的维护窗口，
执行 `maintain_ppt_artifacts.py --days 30 --apply --offline`，记录隔离批次号。
文件仍在同盘可恢复隔离区，不会自动永久删除，也不会立即释放同盘空间。
恢复需停机并执行 `--restore <批次号> --offline`；原路径存在则拒绝覆盖。
隔离区的最终删除/迁出应由管理员在备份、保留期和引用清单核对后另行确认。

# PPT Master 应用运行时

官方技能：`hugohe3/ppt-master`，MIT，锁定版本 6.7.0。
精确提交、完整分发树哈希和文件数量见 `ppt-master.lock.json`。

## 安装与完整性

在 backend 目录执行：

```bash
python scripts/install_ppt_master.py
# 离线环境：
python scripts/install_ppt_master.py --archive /path/to/official-source.tgz
PYTHONPATH=. python scripts/verify_presentation_runtime.py
```

安装后的 `vendor/ppt-master/SKILL.md` 是未改写的原始技能入口。整个配套目录
（工作流、设计参考、模板、图标、脚本、LICENSE 和署名门禁）完整保留。
不要只上传 SKILL.md 或单独复制某个脚本。vendor 被 Git 忽略，部署时必须安装。

应用读取 `references/shared-standards-core.md` 的设计基线供逐页模型使用，保存技能版本元数据，
执行官方 SVG 检查与原生 PPTX 编译器。应用适配层额外负责鉴权、资料范围、已确认内容绑定、
SVG 安全白名单、最终文件渲染与中文字形检查、不可变版本与发布确认。

这不是完整上游交互式工作流的无条件执行器：不会给模型开放 Shell，不自动执行
SKILL.md 中任意命令，不声称支持上游所有建模板、原生模板填充、动画和旁白路由。
本轮支持教学课件生成与单页修改；上传模板仍仅是配色参考。

## 中文字体

Ubuntu/Debian 安装 `fonts-noto-cjk`；同时需要 `libreoffice-impress` 和 `poppler-utils`。
无系统 Noto 字体的本地环境，可把官方 `NotoSansCJKsc-Regular.otf` 与 OFL 许可一起
放在 `presentation_runtime/fonts/`（Git 忽略，自动发现），或设置 `PPT_FONT_DIRECTORY`。
不要从本机安装目录拷贝专有字体到服务器。字体不嵌入 PPTX，接收端仍需字体或合适替代字体。

## 边界与验收

旧 PptxGenJS 引擎已移除。旧成品保留下载，不删除现有数据。
页面内容由已校验方案绑定，模型只能设计位置、形状和配色；不能靠截断内容通过验收。
`ppt_drafts/` 是旧私有诊断草稿；`ppt_jobs/` 存放输入指纹、逐页设计和续作检查点。
两者可能包含教学资料和模型原始文本，不应挂载为公开静态目录。只能通过任务所有权校验后的接口读取成品。
检查点只复用相同所有者、输入、证据与模型版本下的未完成作业，不复用无指纹的旧诊断稿。
草稿和历史产物当前不自动清理，容量治理应在备份/保留策略明确后另行配置。

结构和字形检查不等同于视觉或事实的全自动保证，发布前仍需教师审阅。
保持后端单 worker；多实例必须另加外部任务队列和全局并发控制。

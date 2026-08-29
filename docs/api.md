# API 说明

基础路径：`/api/v1`。除注册、登录和健康检查外，接口均要求 Bearer JWT。

## 系统与认证

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 服务健康检查 |
| GET | `/ready` | 服务与数据库就绪检查 |
| POST | `/auth/register` | 注册学生账号 |
| POST | `/auth/login` | 登录并获取 JWT |
| GET | `/auth/me` | 获取当前用户 |
| POST | `/auth/email/verification/request` | 发送 6 位邮箱验证码（需登录） |
| POST | `/auth/email/verification/confirm` | 使用邮箱和 6 位验证码确认验证 |
| POST | `/auth/password-reset/request` | 申请密码重置验证码；未验证邮箱会先发送邮箱验证验证码 |
| POST | `/auth/password-reset/confirm` | 使用用户名/邮箱、6 位验证码和新密码完成重置 |
| POST | `/auth/password/change` | 登录后修改密码 |
| GET | `/auth/users` | 管理员查看用户列表 |
| GET | `/auth/password-reset/pending` | 管理员查看待人工重置请求 |
| POST | `/auth/users/{id}/temporary-password` | 管理员重置为统一临时密码（默认 12345678） |

`/auth/password-reset/request` 返回 `next_step`：已验证邮箱为 `email`（发送密码重置验证码），未验证邮箱为
`verify_email`（发送 6 位验证码，验证后重新申请），没有邮箱的历史用户名为 `admin`（进入管理员人工处理队列）。

## 课程与章节

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/courses` | 登录用户 | 课程列表 |
| GET | `/courses/{id}` | 登录用户 | 课程详情及章节 |
| POST | `/courses` | admin | 创建课程 |
| PUT | `/courses/{id}` | admin | 更新课程 |
| DELETE | `/courses/{id}` | admin | 删除课程 |
| GET | `/courses/{id}/chapters` | 登录用户 | 章节列表 |
| POST | `/courses/{id}/chapters` | admin | 创建章节 |
| GET | `/chapters/{id}` | 登录用户 | 章节详情 |
| PUT | `/chapters/{id}` | admin | 更新章节 |
| DELETE | `/chapters/{id}` | admin | 删除章节 |

## 学习

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/dashboard` | 当前课程、章节及综合进度 |
| GET | `/learning/progress` | 当前用户学习记录 |
| PUT | `/learning/progress` | 新增或更新阶段学习进度 |

### 教师任务时间

`POST /assignments` 的 `due_time` 必须是带 `Z` 或 UTC offset 的 ISO 8601
时间（例如 `2026-08-20T10:00:00+08:00`）；缺少时区的值会被拒绝。任务截止与
完成时间在响应中统一返回 UTC `Z`。其他没有历史时间基准标记的 naive 字段不会
由通用响应层猜测为 UTC。

## AI 辅助

### POST `/ai/assist`

请求必须指定课程、章节、学习阶段和任务类型：

```json
{
  "course_id": 1,
  "chapter_id": 1,
  "learning_stage": "preview",
  "task_type": "chapter_summary",
  "question": "帮我总结本章重点"
}
```

任务类型支持 `question_answer`、`chapter_summary`、`preview_questions`、
`review_outline` 和 `mock_questions`。响应包含 `grounded`、`model` 与 `sources`；
当前章节无资料时不会调用模型，并明确返回资料不足。

Chat 请求可额外传 `attachment_ids: [1, 2]` 引用本人已上传图片；每轮最多两张，Agent 模式不接受该字段。语音先通过转写接口得到文字，不直接进入 `/ai/assist`。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/ai/media/capabilities` | 返回图片/语音是否可用及服务端限制 |
| POST | `/ai/media/assets` | 分块上传本人图片或录音（multipart） |
| GET | `/ai/media/assets` | 列出本人临时媒体资产 |
| GET | `/ai/media/assets/{id}` | 获取本人媒体资产元数据 |
| DELETE | `/ai/media/assets/{id}` | 删除本人媒体资产及磁盘文件 |
| POST | `/ai/media/assets/{id}/transcribe` | 把本人录音转成可编辑文字 |

## 资料中心与知识库

资料管理接口仅 `teacher` 和 `admin` 可用。中央材料的导入、范围确认、发布、归档和索引维护仅限 `admin`；教师只能维护本人上传且绑定本人教学班的地方材料。教材接口继续使用原有版本与校准流程。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/knowledge/documents` | 上传、解析、切分并向量化文件 |
| GET | `/knowledge/documents` | 获取文档列表，可按课程过滤 |
| GET | `/knowledge/documents/{id}` | 获取文档详情 |
| DELETE | `/knowledge/documents/{id}` | 删除原文件、数据库记录和向量 |
| POST | `/knowledge/documents/{id}/reindex` | 根据原文件重新建立索引 |
| POST | `/knowledge/search` | 调试课程/章节向量检索 |
| GET | `/knowledge/materials` | 按权限列出中央、教材、地方或待分类资料 |
| POST | `/knowledge/materials` | 上传中央或地方资料文件 |
| POST | `/knowledge/materials/url` | 管理员归档公开 HTTPS 中央原文 |
| GET | `/knowledge/materials/{id}/suggestions` | 获取教材与专题关联建议 |
| PUT | `/knowledge/materials/{id}/scopes` | 人工确认教材、专题、教学班和知识点范围 |
| POST | `/knowledge/materials/{id}/publish` | 发布已核验的中央或地方资料 |
| POST | `/knowledge/materials/{id}/archive` | 归档资料并停止参与新回答 |
| PUT | `/knowledge/materials/{id}/classification` | 管理员确认升级前资料的层级 |

教材上传使用 `multipart/form-data`，字段包括 `file`、`source_title`、`course_id`、
可选的 `chapter_id` 和 `knowledge_point`。中央/地方材料还需要 `publisher`、
`published_date`、JSON 数组格式的 `course_ids`、`chapter_ids`、
`teaching_class_ids` 与 `knowledge_tags`。中央材料上传后处于待确认状态，只有确认范围并发布后才进入 AI 检索。

统一成功响应结构：

```json
{"success": true, "message": "操作成功", "data": {}}
```

# API 说明

基础路径：`/api/v1`。除注册、登录和健康检查外，接口均要求 Bearer JWT。

## 系统与认证

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 服务健康检查 |
| POST | `/auth/register` | 注册学生账号 |
| POST | `/auth/login` | 登录并获取 JWT |
| GET | `/auth/me` | 获取当前用户 |

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

## 知识库

知识库接口仅 `teacher` 和 `admin` 可用。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/knowledge/documents` | 上传、解析、切分并向量化文件 |
| GET | `/knowledge/documents` | 获取文档列表，可按课程过滤 |
| GET | `/knowledge/documents/{id}` | 获取文档详情 |
| DELETE | `/knowledge/documents/{id}` | 删除原文件、数据库记录和向量 |
| POST | `/knowledge/documents/{id}/reindex` | 根据原文件重新建立索引 |
| POST | `/knowledge/search` | 调试课程/章节向量检索 |

上传使用 `multipart/form-data`，字段包括 `file`、`source_title`、`course_id`、
可选的 `chapter_id` 和 `knowledge_point`。

统一成功响应结构：

```json
{"success": true, "message": "操作成功", "data": {}}
```

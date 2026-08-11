# 权威资料发现第二阶段：关联与差异证据

## 目标

在第一阶段“来源白名单—后台发现—正文快照—候选材料池”的基础上，补齐发布前的证据链。候选材料不会因为自动分析而直接进入正式知识库，管理员仍需确认关联范围并发布。

## 已实现流程

```text
候选材料
  → 全教材标题/正文关联建议
  → 与关联专题正文、已发布中央材料逐句比对
  → 生成新旧原文证据卡
  → 管理员确认 / 观察 / 驳回
  → 管理员确认
  → 发布/重建当前向量索引
  → 相关教师站内提醒
```

## 数据结构

- `material_candidates` 增加 `suggested_course_ids`、`suggested_chapter_ids`、`suggested_knowledge_tags`、`association_confidence` 和 `association_reason`。
- 新增 `policy_changes`，保存旧资料/教材专题、新材料、原文片段、相似度、变化类型、重要程度、提醒建议和审核状态。
- 迁移文件：`backend/alembic/versions/20260803_02_policy_changes.py`。

## 关联规则

系统对当前全部课程专题执行分层匹配：先从材料标题和高价值政策句构造压缩查询，分别执行教材 BM25、当前活动向量集合和词项证据召回，再使用 RRF 融合不同量纲的排名。融合候选可选用开源 `BAAI/bge-reranker-v2-m3` Cross-Encoder 精排，最终最多给出 3 个达到阈值的专题；没有真实匹配时允许返回空结果，不再强制回退 Top 3。配置真实 LLM 时，模型只能在合法候选 ID 内提供辅助说明，不得删除已通过可复现门槛的网页候选，也不能覆盖检索置信度。向量、精排或模型服务异常时自动退回保守的确定性路径，不会拖垮后台任务。建议范围只用于审核页面，不会自动写入中央材料的正式作用域。

中央材料对比同时识别旧版单一 `course_id` 和新版 `document_course_scopes` 多教材作用域，避免已发布中央材料因作用域存储方式不同而漏出对比集合。

## 差异规则

旧依据优先限定为建议专题正文和明确绑定同一章节的已发布中央材料。旧版只有课程作用域的材料必须先通过 Cross-Encoder 文档级复核；精排模型不可用时不进入课程级降级集合，避免跨章节误配。新旧句段先经过 BGE 相关性门控和可选中文 NLI 中立关系过滤，再使用 `SequenceMatcher` 描述字面变化幅度。证据按“主题置信度 × 变化幅度 × 政策重要度”排序，最多保留 3 条；低字面相似度不再单独构成高价值证据。章节匹配置信度保存在候选材料，句对证据置信度单独保存在 `policy_changes.evidence_confidence`。

网页候选保留和重要提醒使用不同阈值。主题筛选支持完整关键词和中文二元组覆盖匹配，关键词在正文中明确命中即可继续进入教材匹配，而不再要求标题必须命中。达到主题或章节低门槛但低于人工审核阈值的弱关联网页不会直接丢弃，而是保留到观察区继续提供原文和候选证据；它们不会生成重要级管理员通知。教学重要度同样受主题与章节门槛上限约束，不能只因为来源级别高就显示红色“重要”。只有主题审核条件成立，且章节匹配置信度与句对证据置信度同时达到 `AUTHORITY_MATCHING_ALERT_SCORE` 时，差异卡才允许显示“建议提醒”。这样提高来源发现召回率时不会同步放大紧急误报。

## 可选开源模型

基础安装始终可运行确定性降级路径。需要本地开源精排和 NLI 时安装并启用：

```bash
pip install -r requirements-matching.txt
```

```dotenv
AUTHORITY_MATCHING_RERANKER_ENABLED=true
AUTHORITY_MATCHING_RERANKER_MODEL=BAAI/bge-reranker-v2-m3
AUTHORITY_MATCHING_NLI_ENABLED=true
AUTHORITY_MATCHING_NLI_MODEL=IDEA-CCNL/Erlangshen-Roberta-110M-NLI
```

首次启用会加载模型，生产部署应提前准备模型缓存。任一模型加载或推理失败时只记录一次降级原因，并继续使用章节约束和确定性词项门控。

离线标注结果可以用以下命令计算章节 `Precision@1`、`Recall@3`、证据句对准确率、跨章节误配率和无匹配准确率：

```bash
python -m scripts.evaluate_material_matching path/to/evaluation.json
```

## 管理员操作

“资料动态”页面的候选材料详情中可以：

- 点击“重新分析”刷新全教材关联和差异证据；
- 查看建议置信度、专题数量和新旧原文；
- 对每条证据选择“确认并提醒教师”“加入观察”或“误判”；
- 继续使用原有“发布到中央材料”流程，发布前仍由管理员选择教材范围。

接口集中在 `/api/v1/knowledge/discovery`：

- `POST /candidates/{id}/analyze`
- `GET /candidates/{id}/changes`
- `GET /changes`
- `POST /changes/{id}/review`

## 第三阶段衔接说明

- 确认变化不会绕过候选材料的正式发布。候选材料尚未发布时，证据状态为 `waiting_publish`，不会参与正式 RAG，也不会向教师发送“已生效”提醒。
- 候选材料已经发布时，系统使用当前 Embedding profile 调用知识库重建流程，完成后将证据标记为 `synced`，并按关联教材通知已审核教师。
- 重建失败会保留 `failed` 状态和错误信息，可由管理员调用 `POST /changes/{id}/sync` 重试；重复同步和重复提醒均幂等。
- 站内提醒接口为 `/api/v1/notifications`，支持未读列表、单条已读和全部已读；正式提醒包含来源网址、政策变化证据编号和关联课程范围。

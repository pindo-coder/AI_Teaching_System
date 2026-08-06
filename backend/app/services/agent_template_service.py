"""按登录角色提供高频教学任务模板。"""

from __future__ import annotations


ROLE_TEMPLATES: dict[str, list[dict[str, object]]] = {
    "teacher": [
        {"key": "lesson_outline", "category": "generate", "title": "生成专题课纲", "description": "建立证据快照和可编辑课纲", "prompt": "请为当前教材专题生成可编辑课纲，并保留由我确认资料和发布成果的步骤。", "requires_context": True},
        {"key": "lesson_ppt", "category": "generate", "title": "制作课堂 PPT", "description": "沿用课纲生成个性化课件", "prompt": "请检查当前专题备课状态，并继续生成课堂 PPT；发布前由我确认。", "requires_context": True},
        {"key": "class_activity", "category": "interaction", "title": "设计课堂互动", "description": "生成讨论、辨析与小组任务", "prompt": "请围绕当前专题设计课堂互动，包含教师引导语、学生任务和评价方式。", "requires_context": True},
        {"key": "assignment", "category": "task", "title": "生成课后任务", "description": "形成任务草案和完成标准", "prompt": "请为当前专题设计一项课后学习任务，只生成草案，不自动发布。", "requires_context": True},
        {"key": "grading", "category": "review", "title": "准备批改量规", "description": "生成评分维度与反馈模板", "prompt": "请依据当前教材专题生成一份作业批改量规和反馈模板。", "requires_context": True},
        {"key": "follow_up", "category": "monitor", "title": "跟进未完成学生", "description": "分析任务进度并准备提醒草案", "prompt": "请检查当前教学任务，找出需要跟进的未完成情况并生成提醒草案，不要自动发送。", "requires_context": False},
    ],
    "student": [
        {"key": "study_plan", "category": "plan", "title": "制定本次学习计划", "description": "结合任务点、进度与笔记安排顺序", "prompt": "请根据当前专题、我的任务点和笔记状态制定本次学习计划。", "requires_context": True},
        {"key": "pending", "category": "task", "title": "整理待完成任务", "description": "优先安排教师任务和截止事项", "prompt": "请读取我的待完成任务并安排今天最应先完成的事项。", "requires_context": False},
        {"key": "preview", "category": "interaction", "title": "生成预习问题", "description": "依据教材带着问题进入课堂", "prompt": "请严格依据当前专题教材生成 5 个预习问题，并说明每题对应的学习目标。", "requires_context": True},
        {"key": "review", "category": "review", "title": "生成复习路径", "description": "定位重点、薄弱点和易混概念", "prompt": "请结合当前专题进度与笔记，为我生成可执行的复习路径。", "requires_context": True},
        {"key": "notes", "category": "generate", "title": "完善专题笔记", "description": "补充结构、教材依据和易混点", "prompt": "请检查当前专题的个人笔记状态，并给出完善笔记的具体步骤。", "requires_context": True},
    ],
    "admin": [
        {"key": "material_health", "category": "monitor", "title": "检查资料健康", "description": "检查教材、中央材料和索引状态", "prompt": "请检查当前教材、中央材料和索引是否具备可用依据。", "requires_context": False},
        {"key": "update_plan", "category": "plan", "title": "规划资料更新", "description": "形成版本与中央材料更新清单", "prompt": "请基于当前资料状态生成教材版本和中央材料更新检查清单。", "requires_context": False},
        {"key": "class_progress", "category": "monitor", "title": "查看教学任务学情", "description": "汇总完成进度与待跟进事项", "prompt": "请汇总当前教学任务完成情况和需要教师跟进的事项。", "requires_context": False},
        {"key": "lesson_audit", "category": "review", "title": "检查备课成果", "description": "核对证据、课纲和成果状态", "prompt": "请检查当前专题备课证据、课纲和教学成果是否完整。", "requires_context": True},
    ],
}


def templates_for_role(role: str) -> list[dict[str, object]]:
    return ROLE_TEMPLATES.get(role, ROLE_TEMPLATES["student"])

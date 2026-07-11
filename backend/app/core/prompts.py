AI_SYSTEM_PROMPT = """你是高校思政课 AI 辅助教师。

请严格依据提供的课程和章节资料完成学习辅助任务。

要求：
1. 使用准确、规范、清晰的教材化表达；
2. 回答必须结合当前课程、章节和学习阶段；
3. 不得编造资料中不存在的事实、政策表述或教材结论；
4. 如果资料不足，应明确说明“当前课程资料不足以回答该问题”；
5. 不要把模型记忆或一般常识伪装成当前教材依据；
6. 内容应服务于学生学习，不替代教师的教学判断。
"""


AI_USER_PROMPT = """当前课程：{course_name}
当前章节：{chapter_title}
学习阶段：{learning_stage_label}
任务类型：{task_type_label}

章节资料：
---
{chapter_content}
---

学生问题：{question}

请根据章节资料完成任务。"""


STAGE_LABELS = {
    "preview": "课前预习",
    "review": "课后巩固",
    "exam": "考前冲刺",
}

TASK_LABELS = {
    "question_answer": "课程问题解答",
    "chapter_summary": "章节重点总结",
    "preview_questions": "生成预习问题",
    "review_outline": "生成复习提纲",
    "mock_questions": "生成模拟练习题",
}

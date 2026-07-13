from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chapter import Chapter
from app.models.learning_progress import LearningProgress
from app.models.learning_task import LearningEvent, LearningTaskPoint, UserTaskProgress
from app.schemas.task import LearningEventCreate, TaskPointRead, TaskProgressSummary


TASK_TEMPLATES = {
    "preview": [
        ("chapter_opened", "查看专题导览", "了解本专题研究的问题和学习目标。", 20, {"event": "chapter_opened"}),
        ("reading_preview", "预读教材原文", "阅读本章教材内容，形成整体认识。", 35, {"event": "reading_progress", "min_percent": 80}),
        ("ai_preview", "生成预习问题", "围绕当前章节生成并查看预习问题。", 20, {"event": "ai_assist_used", "tasks": ["preview_questions"]}),
        ("preview_question", "提交课前问题", "提交至少一个与本章相关的学习问题。", 25, {"event": "question_submitted", "min_count": 1}),
    ],
    "review": [
        ("reading_review", "回看教材重点", "完成本章教材重点回看。", 30, {"event": "reading_progress", "min_percent": 80}),
        ("ai_review", "生成复习提纲", "使用 AI 梳理本章观点、概念和逻辑关系。", 25, {"event": "ai_assist_used", "tasks": ["chapter_summary", "review_outline"]}),
        ("note_saved", "保存个人学习笔记", "用自己的语言沉淀本章理解，形成可复习笔记。", 30, {"event": "note_saved", "min_length": 30}),
        ("review_question", "完成课后自测", "提交一个课后巩固问题或答案。", 15, {"event": "question_submitted", "min_count": 1}),
    ],
    "exam": [
        ("reading_exam", "速览核心原文", "在冲刺前回顾本章核心教材内容。", 25, {"event": "reading_progress", "min_percent": 80}),
        ("ai_exam", "梳理重点考点", "使用 AI 生成本章考点或模拟题。", 25, {"event": "ai_assist_used", "tasks": ["mock_questions", "review_outline"]}),
        ("exam_question", "完成模拟练习", "提交一道模拟题答案或完成一次练习。", 35, {"event": "quiz_completed", "min_count": 1}),
        ("exam_review", "查看薄弱点", "根据练习结果回看一个薄弱知识点。", 15, {"event": "question_submitted", "min_count": 1}),
    ],
}


class TaskService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def ensure_tasks(self, course_id: int, chapter_id: int, stage: str) -> list[LearningTaskPoint]:
        tasks = list(self.db.scalars(select(LearningTaskPoint).where(
            LearningTaskPoint.chapter_id == chapter_id,
            LearningTaskPoint.learning_stage == stage,
        ).order_by(LearningTaskPoint.sort_order)).all())
        if tasks:
            return tasks
        for index, (task_type, title, description, weight, rule) in enumerate(TASK_TEMPLATES[stage], 1):
            task = LearningTaskPoint(course_id=course_id, chapter_id=chapter_id, learning_stage=stage,
                                     task_type=task_type, title=title, description=description,
                                     weight=weight, sort_order=index, completion_rule=rule)
            self.db.add(task)
            tasks.append(task)
        self.db.flush()
        return tasks

    def summary(self, user_id: int, course_id: int, chapter_id: int, stage: str) -> TaskProgressSummary:
        chapter = self.db.get(Chapter, chapter_id)
        if chapter is None or chapter.course_id != course_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="章节与课程不匹配")
        tasks = self.ensure_tasks(course_id, chapter_id, stage)
        progresses = {item.task_point_id: item for item in self.db.scalars(select(UserTaskProgress).where(
            UserTaskProgress.user_id == user_id,
            UserTaskProgress.task_point_id.in_([task.id for task in tasks]),
        )).all()}
        reads = [TaskPointRead.model_validate(task).model_copy(update={
            "status": progresses[task.id].status if task.id in progresses else "not_started",
            "progress_value": progresses[task.id].progress_value if task.id in progresses else 0,
            "evidence_summary": progresses[task.id].evidence_summary if task.id in progresses else "",
            "completed_time": progresses[task.id].completed_time if task.id in progresses else None,
        }) for task in tasks]
        total_weight = sum(task.weight for task in tasks) or 1
        done_weight = sum(task.weight for task in tasks if progresses.get(task.id, None) and progresses[task.id].status == "completed")
        return TaskProgressSummary(course_id=course_id, chapter_id=chapter_id, learning_stage=stage,
                                   completed_count=sum(item.status == "completed" for item in reads), total_count=len(reads),
                                   progress=round(done_weight / total_weight * 100), tasks=reads)

    def record(self, user_id: int, payload: LearningEventCreate) -> TaskProgressSummary:
        chapter = self.db.get(Chapter, payload.chapter_id)
        if chapter is None or chapter.course_id != payload.course_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="章节与课程不匹配")
        self.db.add(LearningEvent(user_id=user_id, course_id=payload.course_id, chapter_id=payload.chapter_id,
                                  learning_stage=payload.learning_stage, event_type=payload.event_type,
                                  event_data=payload.event_data))
        tasks = self.ensure_tasks(payload.course_id, payload.chapter_id, payload.learning_stage)
        for task in tasks:
            if task.completion_rule.get("event") != payload.event_type:
                continue
            current = self.db.scalar(select(UserTaskProgress).where(UserTaskProgress.user_id == user_id,
                                                                    UserTaskProgress.task_point_id == task.id))
            if current is None:
                current = UserTaskProgress(user_id=user_id, task_point_id=task.id)
                self.db.add(current)
            current.status = "in_progress"
            current.progress_value = max(current.progress_value or 0, self._event_progress(task, payload))
            current.evidence_summary = self._evidence(task, payload)
            if current.progress_value >= 100:
                current.status = "completed"
                current.completed_time = current.completed_time or datetime.utcnow()
        self.db.flush()
        summary = self.summary(user_id, payload.course_id, payload.chapter_id, payload.learning_stage)
        progress = self.db.scalar(select(LearningProgress).where(
            LearningProgress.user_id == user_id, LearningProgress.chapter_id == payload.chapter_id,
            LearningProgress.learning_stage == payload.learning_stage))
        if progress is None:
            progress = LearningProgress(user_id=user_id, course_id=payload.course_id, chapter_id=payload.chapter_id,
                                        learning_stage=payload.learning_stage, progress=summary.progress)
            self.db.add(progress)
        else:
            progress.progress = summary.progress
        self.db.commit()
        return summary

    @staticmethod
    def _event_progress(task: LearningTaskPoint, payload: LearningEventCreate) -> int:
        rule = task.completion_rule
        data = payload.event_data
        if "min_percent" in rule:
            return min(100, int(float(data.get("percent", 0)) / rule["min_percent"] * 100))
        if "min_count" in rule:
            return 100 if int(data.get("count", 1)) >= rule["min_count"] else 50
        if "min_length" in rule:
            return 100 if len(str(data.get("content", ""))) >= rule["min_length"] else 40
        if rule.get("tasks"):
            return 100 if data.get("task_type") in rule["tasks"] else 0
        return 100

    @staticmethod
    def _evidence(task: LearningTaskPoint, payload: LearningEventCreate) -> str:
        data = payload.event_data
        if payload.event_type == "reading_progress":
            return f"已阅读 {int(float(data.get('percent', 0)))}%"
        if payload.event_type == "ai_assist_used":
            return "已使用章节 AI 辅助"
        if payload.event_type == "note_saved":
            return "已保存章节笔记"
        return "已记录学习行为"

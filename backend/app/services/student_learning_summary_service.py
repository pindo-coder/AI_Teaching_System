"""Build an evidence-based seven-day learning summary for one student."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.time import to_utc_naive, utc_iso, utc_now
from app.models.chapter import Chapter
from app.models.course import Course
from app.models.learning_progress import LearningProgress
from app.models.learning_task import LearningEvent, LearningTaskPoint, UserTaskProgress
from app.models.review_practice import ReviewPractice
from app.models.study_chat_message import StudyChatMessage
from app.models.study_note import StudyNote
from app.services.assignment_service import AssignmentService


EVENT_LABELS = {
    "chapter_opened": "打开专题",
    "reading_progress": "阅读记录",
    "ai_assist_used": "AI 辅助",
    "question_submitted": "问题提交",
    "note_saved": "笔记保存",
    "activity_submitted": "活动提交",
    "quiz_completed": "练习完成",
}

COMPLETED_ITEM_LIMIT = 10


class StudentLearningSummaryService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def summarize(self, user_id: int, *, now: datetime | None = None, days: int = 7) -> dict[str, Any]:
        end = to_utc_naive(now) if now is not None else utc_now()
        start = end - timedelta(days=days)

        events = list(self.db.scalars(select(LearningEvent).where(
            LearningEvent.user_id == user_id,
            LearningEvent.created_time >= start,
            LearningEvent.created_time <= end,
        )).all())
        event_counts = Counter(item.event_type for item in events)
        active_course_ids = {item.course_id for item in events}
        active_chapter_ids = {item.chapter_id for item in events}

        recent_progress = list(self.db.scalars(select(LearningProgress).where(
            LearningProgress.user_id == user_id,
            LearningProgress.last_study_time >= start,
            LearningProgress.last_study_time <= end,
        )).all())
        active_course_ids.update(item.course_id for item in recent_progress)
        active_chapter_ids.update(item.chapter_id for item in recent_progress)

        # “最近完成”以不可变的完成时间为准；进行中任务仍以最近更新时间判断
        # 本期是否活跃。不能用 updated_time 统计已完成项，否则历史任务被同步
        # 或重新保存后会被误报成最近完成。
        task_rows = list(self.db.execute(
            select(UserTaskProgress, LearningTaskPoint, Course.name, Chapter.title)
            .join(LearningTaskPoint, LearningTaskPoint.id == UserTaskProgress.task_point_id)
            .join(Course, Course.id == LearningTaskPoint.course_id)
            .join(Chapter, Chapter.id == LearningTaskPoint.chapter_id)
            .where(
                UserTaskProgress.user_id == user_id,
                or_(
                    and_(
                        UserTaskProgress.status == "completed",
                        UserTaskProgress.completed_time.is_not(None),
                        UserTaskProgress.completed_time >= start,
                        UserTaskProgress.completed_time <= end,
                    ),
                    and_(
                        UserTaskProgress.status == "in_progress",
                        UserTaskProgress.updated_time >= start,
                        UserTaskProgress.updated_time <= end,
                    ),
                ),
            )
        ).all())
        completed_task_rows = sorted(
            (row for row in task_rows if row[0].status == "completed" and row[0].completed_time),
            key=lambda row: row[0].completed_time,
            reverse=True,
        )
        completed_tasks = len(completed_task_rows)
        in_progress_tasks = sum(progress.status == "in_progress" for progress, *_ in task_rows)
        completed_task_items = [
            {
                "task_point_id": task.id,
                "course_id": task.course_id,
                "course_name": course_name,
                "chapter_id": task.chapter_id,
                "chapter_title": chapter_title,
                "learning_stage": task.learning_stage,
                "task_type": task.task_type,
                "title": task.title,
                "completed_time": utc_iso(progress.completed_time),
                "evidence_summary": progress.evidence_summary,
            }
            for progress, task, course_name, chapter_title in completed_task_rows[:COMPLETED_ITEM_LIMIT]
        ]
        active_course_ids.update(task.course_id for _progress, task, *_ in task_rows)
        active_chapter_ids.update(task.chapter_id for _progress, task, *_ in task_rows)

        notes = list(self.db.scalars(select(StudyNote).where(
            StudyNote.user_id == user_id,
            StudyNote.updated_time >= start,
            StudyNote.updated_time <= end,
        )).all())
        practices = list(self.db.scalars(select(ReviewPractice).where(
            ReviewPractice.user_id == user_id,
            ReviewPractice.answered_at.is_not(None),
            ReviewPractice.answered_at >= start,
            ReviewPractice.answered_at <= end,
        )).all())
        correct_practices = sum(item.is_correct is True for item in practices)
        ai_chat_count = len(list(self.db.scalars(select(StudyChatMessage.id).where(
            StudyChatMessage.user_id == user_id,
            StudyChatMessage.role == "user",
            StudyChatMessage.created_time >= start,
            StudyChatMessage.created_time <= end,
        )).all()))

        assignments = AssignmentService(self.db).student_assignments(user_id, include_completed=True)
        assignment_counts = Counter(item["status"] for item in assignments)
        completed_assignment_rows = sorted(
            (
                item for item in assignments
                if item["status"] == "completed"
                and item["completed_time"]
                and start <= item["completed_time"] <= end
            ),
            key=lambda item: item["completed_time"],
            reverse=True,
        )
        completed_recent = len(completed_assignment_rows)
        completed_assignment_items = [
            {
                "assignment_id": item["id"],
                "course_id": item["course_id"],
                "course_name": item["course_name"],
                "chapter_id": item["chapter_id"],
                "chapter_title": item["chapter_title"],
                "title": item["title"],
                "completed_time": utc_iso(item["completed_time"]),
            }
            for item in completed_assignment_rows[:COMPLETED_ITEM_LIMIT]
        ]
        active_course_ids.update(item["course_id"] for item in completed_assignment_rows)
        active_chapter_ids.update(item["chapter_id"] for item in completed_assignment_rows)

        chapter_names = {
            chapter_id: title for chapter_id, title in self.db.execute(
                select(Chapter.id, Chapter.title).where(Chapter.id.in_(active_chapter_ids))
            ).all()
        } if active_chapter_ids else {}
        activity_by_chapter = Counter(item.chapter_id for item in events)
        active_topics = [
            {"chapter_id": chapter_id, "chapter_title": chapter_names.get(chapter_id, "未命名专题"), "event_count": count}
            for chapter_id, count in activity_by_chapter.most_common(3)
        ]

        incorrect_by_chapter = Counter(item.chapter_id for item in practices if item.is_correct is False)
        weak_points = [
            f"{chapter_names.get(chapter_id, '相关专题')}复习练习答错 {count} 题"
            for chapter_id, count in incorrect_by_chapter.most_common(3)
        ]
        stalled = [
            f"{chapter_title}：{task.title}（{progress.progress_value}%）"
            for progress, task, _course_name, chapter_title in task_rows
            if progress.status == "in_progress" and task.task_type not in {"ai_preview", "ai_review", "ai_exam"}
        ][:3]
        weak_points.extend(item for item in stalled if item not in weak_points)

        suggestions: list[str] = []
        if assignment_counts["overdue"]:
            suggestions.append(f"先处理 {assignment_counts['overdue']} 项逾期教师任务")
        if practices and correct_practices < len(practices):
            suggestions.append("回看错题对应专题，并在复习页再次练习")
        if in_progress_tasks:
            suggestions.append("继续完成已有进度的任务点，避免重复从头开始")
        if not notes and (events or recent_progress):
            suggestions.append("把本周重点用自己的语言补充到专题笔记")
        if not suggestions:
            suggestions.append("选择一个近期专题继续学习，并完成一个可验证任务点")

        return {
            "period": {"days": days, "start": utc_iso(start), "end": utc_iso(end)},
            "active": {
                "course_count": len(active_course_ids), "chapter_count": len(active_chapter_ids),
                "topics": active_topics,
            },
            "task_points": {
                "completed": completed_tasks,
                "in_progress": in_progress_tasks,
                "completed_items": completed_task_items,
                "completed_items_truncated": completed_tasks > len(completed_task_items),
            },
            "assignments": {
                "completed_in_period": completed_recent,
                "pending": assignment_counts["not_started"] + assignment_counts["in_progress"],
                "overdue": assignment_counts["overdue"],
                "completed_items": completed_assignment_items,
                "completed_items_truncated": completed_recent > len(completed_assignment_items),
            },
            "learning_actions": {
                "events": {EVENT_LABELS.get(key, key): value for key, value in event_counts.items()},
                "notes_updated": len(notes),
                "practice_answered": len(practices),
                "practice_correct": correct_practices,
                "ai_assist_events": event_counts["ai_assist_used"],
                "ai_chat_questions": ai_chat_count,
            },
            "weak_points": weak_points[:3],
            "suggestions": suggestions[:3],
        }

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chapter import Chapter
from app.models.learning_task import LearningEvent
from app.models.review_practice import ReviewPractice
from app.models.study_note import StudyNote
from app.schemas.learning import LearningFootprint, LearningFootprintActivity
from app.schemas.task import LearningTelemetryCreate
from app.core.time import utc_now
from app.models.learning_progress import LearningProgress


EVENT_LABELS = {
    "chapter_opened": "打开专题",
    "reading_progress": "阅读教材",
    "ai_assist_used": "使用 AI 辅助",
    "question_submitted": "提出学习问题",
    "note_saved": "保存学习笔记",
    "activity_submitted": "提交课堂活动",
    "quiz_completed": "完成练习",
}


class LearningFootprintService:
    """Summarize meaningful learning evidence without exposing task-point scoring."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def record(self, user_id: int, payload: LearningTelemetryCreate) -> LearningFootprint:
        chapter = self.db.get(Chapter, payload.chapter_id)
        if chapter is None or chapter.course_id != payload.course_id:
            raise ValueError("章节与课程不匹配")
        self.db.add(LearningEvent(
            user_id=user_id,
            course_id=payload.course_id,
            chapter_id=payload.chapter_id,
            learning_stage=payload.learning_stage,
            event_type=payload.event_type,
            event_data=payload.event_data,
        ))
        progress = self.db.scalar(select(LearningProgress).where(
            LearningProgress.user_id == user_id,
            LearningProgress.course_id == payload.course_id,
            LearningProgress.chapter_id == payload.chapter_id,
            LearningProgress.learning_stage == payload.learning_stage,
        ))
        if progress is None:
            progress = LearningProgress(
                user_id=user_id,
                course_id=payload.course_id,
                chapter_id=payload.chapter_id,
                learning_stage=payload.learning_stage,
                progress=1,
            )
            self.db.add(progress)
        else:
            progress.progress = max(progress.progress, 1)
            progress.last_study_time = utc_now()
        self.db.commit()
        return self.summary(user_id, payload.course_id, payload.chapter_id, payload.learning_stage)

    def summary(self, user_id: int, course_id: int, chapter_id: int, stage: str) -> LearningFootprint:
        chapter = self.db.get(Chapter, chapter_id)
        if chapter is None or chapter.course_id != course_id:
            raise ValueError("章节与课程不匹配")

        events = list(self.db.scalars(select(LearningEvent).where(
            LearningEvent.user_id == user_id,
            LearningEvent.course_id == course_id,
            LearningEvent.chapter_id == chapter_id,
            LearningEvent.learning_stage == stage,
        ).order_by(LearningEvent.created_time.desc(), LearningEvent.id.desc()).limit(8)).all())
        note = self.db.scalar(select(StudyNote).where(
            StudyNote.user_id == user_id, StudyNote.course_id == course_id, StudyNote.chapter_id == chapter_id,
        ))
        practice_rows = list(self.db.scalars(select(ReviewPractice).where(
            ReviewPractice.user_id == user_id,
            ReviewPractice.course_id == course_id,
            ReviewPractice.chapter_id == chapter_id,
        )).all()) if stage == "exam" else []
        practice_complete = bool(practice_rows) and all(item.answered_at is not None for item in practice_rows)

        # Reading telemetry is emitted at several scroll thresholds. Show one
        # recent item per activity type so the footprint remains meaningful.
        activities: list[LearningFootprintActivity] = []
        seen_event_types: set[str] = set()
        for item in events:
            if item.event_type in seen_event_types:
                continue
            seen_event_types.add(item.event_type)
            activities.append(LearningFootprintActivity(
                event_type=item.event_type,
                label=EVENT_LABELS.get(item.event_type, "学习活动"),
                created_time=item.created_time,
                learning_stage=stage,
            ))
            if len(activities) >= 4:
                break
        outputs: list[str] = []
        has_note_event = any(item.event_type == "note_saved" for item in events)
        if note and note.content.strip() and (stage == "review" or has_note_event):
            outputs.append("已保存章节笔记")
        if any(item.event_type == "question_submitted" for item in events):
            outputs.append("已提出学习问题")
        if practice_complete or any(item.event_type == "quiz_completed" for item in events):
            outputs.append("已完成练习")
        if any(item.event_type == "activity_submitted" for item in events):
            outputs.append("已提交课堂活动")

        if outputs:
            status, status_label = "has_output", "已有学习产出"
        elif events:
            status, status_label = "in_progress", "学习中"
        else:
            status, status_label = "not_started", "未开始"

        if status == "not_started":
            next_action = "先阅读本专题导览，建立整体认识"
        elif stage == "review" and "已保存章节笔记" not in outputs:
            next_action = "用自己的话保存一份章节笔记"
        elif stage == "exam" and "已完成练习" not in outputs:
            next_action = "完成一道练习，检查核心观点是否掌握"
        else:
            next_action = "回到专题内容，继续整理或检验自己的理解"

        return LearningFootprint(
            course_id=course_id,
            chapter_id=chapter_id,
            learning_stage=stage,
            status=status,
            status_label=status_label,
            last_activity_time=events[0].created_time if events else None,
            activities=activities,
            outputs=outputs,
            next_action=next_action,
        )

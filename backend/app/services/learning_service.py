from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.learning_progress import LearningProgress
from app.models.user import User
from app.repositories.course_repository import ChapterRepository, CourseRepository
from app.repositories.learning_repository import LearningRepository
from app.schemas.learning import DashboardData, LearningFootprintActivity, ProgressRead, ProgressUpdate
from app.schemas.course import ChapterRead, CourseRead
from app.schemas.user import UserRead
from app.services.learning_footprint_service import LearningFootprintService


class LearningService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.learning = LearningRepository(db)
        self.courses = CourseRepository(db)
        self.chapters = ChapterRepository(db)

    def list_progress(self, user_id: int) -> list[LearningProgress]:
        return self.learning.list_for_user(user_id)

    def update_progress(self, user_id: int, payload: ProgressUpdate) -> LearningProgress:
        chapter = self.chapters.get(payload.chapter_id)
        if chapter is None or chapter.course_id != payload.course_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="章节与课程不匹配")
        return self.learning.upsert(user_id=user_id, **payload.model_dump())

    def dashboard(self, user: User) -> DashboardData:
        progress = self.learning.list_for_user(user.id)
        latest = progress[0] if progress else None
        course = self.courses.get(latest.course_id) if latest else None
        chapter = self.chapters.get(latest.chapter_id) if latest else None
        # Preserve the old numeric field for API compatibility, but no longer
        # build task-point summaries just to render the dashboard.
        overall = round(sum(item.progress for item in progress) / len(progress)) if progress else 0

        footprints = []
        if course and chapter:
            footprint_service = LearningFootprintService(self.db)
            footprints = [
                footprint_service.summary(user.id, course.id, chapter.id, stage)
                for stage in ("preview", "review", "exam")
            ]

        outputs = list(dict.fromkeys(output for item in footprints for output in item.outputs))
        recent_activities = sorted(
            (activity for item in footprints for activity in item.activities),
            key=lambda activity: activity.created_time,
            reverse=True,
        )[:6]
        if outputs:
            learning_status, learning_status_label = "has_output", "已有学习产出"
        elif recent_activities:
            learning_status, learning_status_label = "in_progress", "学习中"
        else:
            learning_status, learning_status_label = "not_started", "未开始"

        next_footprint = next((item for item in footprints if item.status == "in_progress"), None)
        next_footprint = next_footprint or next((item for item in footprints if item.status == "not_started"), None)
        next_footprint = next_footprint or (footprints[-1] if footprints else None)
        return DashboardData(
            user=UserRead.model_validate(user),
            current_course=CourseRead.model_validate(course) if course else None,
            current_chapter=ChapterRead.model_validate(chapter) if chapter else None,
            recent_progress=[ProgressRead.model_validate(item) for item in progress[:5]],
            overall_progress=overall,
            learning_status=learning_status,
            learning_status_label=learning_status_label,
            stage_footprints=footprints,
            recent_activities=[LearningFootprintActivity.model_validate(item) for item in recent_activities],
            outputs=outputs,
            next_action=next_footprint.next_action if next_footprint else "先选择一个教材专题开始学习",
        )

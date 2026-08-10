from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.learning_progress import LearningProgress
from app.models.learning_task import LearningTaskPoint, UserTaskProgress
from app.models.user import User
from app.repositories.course_repository import ChapterRepository, CourseRepository
from app.repositories.learning_repository import LearningRepository
from app.schemas.learning import DashboardData, ProgressRead, ProgressUpdate
from app.schemas.course import ChapterRead, CourseRead
from app.schemas.user import UserRead
from app.services.task_service import TaskService


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
        effective_progress: list[int] = []
        task_service = TaskService(self.db)
        for item in progress:
            evidence_count = int(self.db.scalar(
                select(func.count(UserTaskProgress.id))
                .join(LearningTaskPoint, LearningTaskPoint.id == UserTaskProgress.task_point_id)
                .where(
                    UserTaskProgress.user_id == user.id,
                    LearningTaskPoint.chapter_id == item.chapter_id,
                    LearningTaskPoint.learning_stage == item.learning_stage,
                )
            ) or 0)
            effective_progress.append(
                task_service.summary(
                    user.id, item.course_id, item.chapter_id, item.learning_stage
                ).progress if evidence_count else item.progress
            )
        overall = round(sum(effective_progress) / len(effective_progress)) if effective_progress else 0
        return DashboardData(
            user=UserRead.model_validate(user),
            current_course=CourseRead.model_validate(course) if course else None,
            current_chapter=ChapterRead.model_validate(chapter) if chapter else None,
            recent_progress=[ProgressRead.model_validate(item) for item in progress[:5]],
            overall_progress=overall,
        )

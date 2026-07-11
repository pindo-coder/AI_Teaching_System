from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.learning_progress import LearningProgress
from app.models.user import User
from app.repositories.course_repository import ChapterRepository, CourseRepository
from app.repositories.learning_repository import LearningRepository
from app.schemas.learning import DashboardData, ProgressRead, ProgressUpdate
from app.schemas.course import ChapterRead, CourseRead
from app.schemas.user import UserRead


class LearningService:
    def __init__(self, db: Session) -> None:
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
        overall = round(sum(item.progress for item in progress) / len(progress)) if progress else 0
        return DashboardData(
            user=UserRead.model_validate(user),
            current_course=CourseRead.model_validate(course) if course else None,
            current_chapter=ChapterRead.model_validate(chapter) if chapter else None,
            recent_progress=[ProgressRead.model_validate(item) for item in progress[:5]],
            overall_progress=overall,
        )

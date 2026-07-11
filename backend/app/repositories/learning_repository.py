from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.learning_progress import LearningProgress


class LearningRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_for_user(self, user_id: int) -> list[LearningProgress]:
        query = (
            select(LearningProgress)
            .where(LearningProgress.user_id == user_id)
            .order_by(LearningProgress.last_study_time.desc())
        )
        return list(self.db.scalars(query).all())

    def upsert(
        self, *, user_id: int, course_id: int, chapter_id: int, learning_stage: str, progress: int
    ) -> LearningProgress:
        query = select(LearningProgress).where(
            LearningProgress.user_id == user_id,
            LearningProgress.chapter_id == chapter_id,
            LearningProgress.learning_stage == learning_stage,
        )
        record = self.db.scalar(query)
        if record is None:
            record = LearningProgress(
                user_id=user_id,
                course_id=course_id,
                chapter_id=chapter_id,
                learning_stage=learning_stage,
                progress=progress,
            )
            self.db.add(record)
        else:
            record.progress = progress
        self.db.commit()
        self.db.refresh(record)
        return record

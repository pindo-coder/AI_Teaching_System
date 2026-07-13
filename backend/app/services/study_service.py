from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chapter import Chapter
from app.models.course import Course
from app.models.review_schedule import ReviewSchedule
from app.models.study_note import StudyNote
from app.models.study_chat_message import StudyChatMessage
from app.schemas.study import StudyChatHistorySave


REVIEW_INTERVALS = [1, 2, 4, 7, 15, 30]


class StudyService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def require_chapter(self, chapter_id: int) -> Chapter:
        chapter = self.db.get(Chapter, chapter_id)
        if chapter is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="专题不存在")
        return chapter

    def get_note(self, user_id: int, chapter_id: int) -> StudyNote | None:
        self.require_chapter(chapter_id)
        return self.db.scalar(select(StudyNote).where(StudyNote.user_id == user_id, StudyNote.chapter_id == chapter_id))

    def list_notes(self, user_id: int) -> list[dict[str, object]]:
        query = (
            select(StudyNote, Course.name, Chapter.title)
            .join(Course, Course.id == StudyNote.course_id)
            .join(Chapter, Chapter.id == StudyNote.chapter_id)
            .where(StudyNote.user_id == user_id)
            .order_by(StudyNote.updated_time.desc(), StudyNote.id.desc())
        )
        return [
            {
                "id": note.id,
                "user_id": note.user_id,
                "course_id": note.course_id,
                "chapter_id": note.chapter_id,
                "content": note.content,
                "created_time": note.created_time,
                "updated_time": note.updated_time,
                "course_name": course_name,
                "chapter_title": chapter_title,
            }
            for note, course_name, chapter_title in self.db.execute(query).all()
        ]

    def delete_note(self, user_id: int, note_id: int) -> None:
        note = self.db.scalar(select(StudyNote).where(StudyNote.id == note_id, StudyNote.user_id == user_id))
        if note is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="学习笔记不存在")
        schedule = self.db.scalar(select(ReviewSchedule).where(ReviewSchedule.user_id == user_id, ReviewSchedule.chapter_id == note.chapter_id))
        if schedule is not None:
            self.db.delete(schedule)
        self.db.delete(note)
        self.db.commit()

    def list_chat_history(self, user_id: int, chapter_id: int) -> list[StudyChatMessage]:
        self.require_chapter(chapter_id)
        return list(self.db.scalars(select(StudyChatMessage).where(
            StudyChatMessage.user_id == user_id,
            StudyChatMessage.chapter_id == chapter_id,
        ).order_by(StudyChatMessage.created_time, StudyChatMessage.id)).all())

    def save_chat_history(self, user_id: int, payload: StudyChatHistorySave) -> list[StudyChatMessage]:
        chapter = self.require_chapter(payload.chapter_id)
        if chapter.course_id != payload.course_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="专题与教材不匹配")
        self.db.add_all([
            StudyChatMessage(user_id=user_id, course_id=payload.course_id, chapter_id=payload.chapter_id,
                             role="user", content=payload.question.strip(), sources=[]),
            StudyChatMessage(user_id=user_id, course_id=payload.course_id, chapter_id=payload.chapter_id,
                             role="assistant", content=payload.answer.strip(), model=payload.model,
                             sources=payload.sources),
        ])
        self.db.commit()
        return self.list_chat_history(user_id, payload.chapter_id)

    def save_note(self, user_id: int, chapter_id: int, content: str) -> StudyNote:
        chapter = self.require_chapter(chapter_id)
        note = self.db.scalar(select(StudyNote).where(StudyNote.user_id == user_id, StudyNote.chapter_id == chapter_id))
        if note is None:
            note = StudyNote(user_id=user_id, course_id=chapter.course_id, chapter_id=chapter.id, content=content.strip())
            self.db.add(note)
        else:
            note.content = content.strip()
        self.db.commit()
        self.db.refresh(note)
        return note

    def activate_review(self, user_id: int, chapter_id: int) -> ReviewSchedule:
        chapter = self.require_chapter(chapter_id)
        record = self.db.scalar(select(ReviewSchedule).where(ReviewSchedule.user_id == user_id, ReviewSchedule.chapter_id == chapter_id))
        if record is None:
            record = ReviewSchedule(
                user_id=user_id,
                course_id=chapter.course_id,
                chapter_id=chapter.id,
                review_count=0,
                interval_days=1,
                next_review_at=datetime.now() + timedelta(days=1),
            )
            self.db.add(record)
            self.db.commit()
            self.db.refresh(record)
        return record

    def complete_review(self, user_id: int, chapter_id: int) -> ReviewSchedule:
        record = self.activate_review(user_id, chapter_id)
        now = datetime.now()
        record.review_count += 1
        record.interval_days = REVIEW_INTERVALS[min(record.review_count, len(REVIEW_INTERVALS) - 1)]
        record.last_reviewed_at = now
        record.next_review_at = now + timedelta(days=record.interval_days)
        self.db.commit()
        self.db.refresh(record)
        return record

    def due_reviews(self, user_id: int) -> list[dict[str, object]]:
        query = (
            select(ReviewSchedule, Course.name, Chapter.title)
            .join(Course, Course.id == ReviewSchedule.course_id)
            .join(Chapter, Chapter.id == ReviewSchedule.chapter_id)
            .where(ReviewSchedule.user_id == user_id, ReviewSchedule.next_review_at <= datetime.now())
            .order_by(ReviewSchedule.next_review_at)
        )
        return [
            {
                "id": record.id,
                "course_id": record.course_id,
                "chapter_id": record.chapter_id,
                "course_name": course_name,
                "chapter_title": chapter_title,
                "review_count": record.review_count,
                "interval_days": record.interval_days,
                "next_review_at": record.next_review_at,
                "last_reviewed_at": record.last_reviewed_at,
            }
            for record, course_name, chapter_title in self.db.execute(query).all()
        ]

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.chapter import Chapter
from app.models.course import Course


class CourseRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list(self) -> list[Course]:
        return list(self.db.scalars(select(Course).order_by(Course.id.desc())).all())

    def get(self, course_id: int, *, with_chapters: bool = False) -> Course | None:
        query = select(Course).where(Course.id == course_id)
        if with_chapters:
            query = query.options(selectinload(Course.chapters))
        return self.db.scalar(query)

    def create(self, *, name: str, description: str | None) -> Course:
        course = Course(name=name.strip(), description=description)
        self.db.add(course)
        self.db.commit()
        self.db.refresh(course)
        return course

    def save(self, course: Course) -> Course:
        self.db.commit()
        self.db.refresh(course)
        return course

    def delete(self, course: Course) -> None:
        self.db.delete(course)
        self.db.commit()


class ChapterRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_by_course(self, course_id: int) -> list[Chapter]:
        query = select(Chapter).where(Chapter.course_id == course_id).order_by(Chapter.sort_order, Chapter.id)
        return list(self.db.scalars(query).all())

    def get(self, chapter_id: int) -> Chapter | None:
        return self.db.get(Chapter, chapter_id)

    def create(self, *, course_id: int, title: str, content: str | None, sort_order: int) -> Chapter:
        chapter = Chapter(course_id=course_id, title=title.strip(), content=content, sort_order=sort_order)
        self.db.add(chapter)
        self.db.commit()
        self.db.refresh(chapter)
        return chapter

    def save(self, chapter: Chapter) -> Chapter:
        self.db.commit()
        self.db.refresh(chapter)
        return chapter

    def delete(self, chapter: Chapter) -> None:
        self.db.delete(chapter)
        self.db.commit()

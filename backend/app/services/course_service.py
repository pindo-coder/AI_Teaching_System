from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.chapter import Chapter
from app.models.course import Course
from app.repositories.course_repository import ChapterRepository, CourseRepository
from app.schemas.course import ChapterCreate, ChapterUpdate, CourseCreate, CourseUpdate


class CourseService:
    def __init__(self, db: Session) -> None:
        self.courses = CourseRepository(db)
        self.chapters = ChapterRepository(db)

    def require_course(self, course_id: int, *, with_chapters: bool = False) -> Course:
        course = self.courses.get(course_id, with_chapters=with_chapters)
        if course is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="课程不存在")
        return course

    def require_chapter(self, chapter_id: int) -> Chapter:
        chapter = self.chapters.get(chapter_id)
        if chapter is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="章节不存在")
        return chapter

    def create_course(self, payload: CourseCreate) -> Course:
        return self.courses.create(name=payload.name, description=payload.description)

    def update_course(self, course_id: int, payload: CourseUpdate) -> Course:
        course = self.require_course(course_id)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(course, field, value.strip() if field == "name" and value else value)
        return self.courses.save(course)

    def create_chapter(self, course_id: int, payload: ChapterCreate) -> Chapter:
        self.require_course(course_id)
        return self.chapters.create(course_id=course_id, **payload.model_dump())

    def update_chapter(self, chapter_id: int, payload: ChapterUpdate) -> Chapter:
        chapter = self.require_chapter(chapter_id)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(chapter, field, value.strip() if field == "title" and value else value)
        return self.chapters.save(chapter)

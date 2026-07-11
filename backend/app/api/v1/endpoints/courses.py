from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_roles
from app.db.session import get_db
from app.models.user import User
from app.repositories.course_repository import ChapterRepository, CourseRepository
from app.schemas.common import ApiResponse
from app.schemas.course import (
    ChapterCreate,
    ChapterRead,
    ChapterUpdate,
    CourseCreate,
    CourseDetail,
    CourseRead,
    CourseUpdate,
)
from app.services.course_service import CourseService


router = APIRouter(tags=["courses"])
admin_only = require_roles("admin")


@router.get("/courses", response_model=ApiResponse[list[CourseRead]])
def list_courses(
    _: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ApiResponse[list[CourseRead]]:
    courses = CourseRepository(db).list()
    return ApiResponse(data=[CourseRead.model_validate(course) for course in courses])


@router.get("/courses/{course_id}", response_model=ApiResponse[CourseDetail])
def get_course(
    course_id: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ApiResponse[CourseDetail]:
    course = CourseService(db).require_course(course_id, with_chapters=True)
    return ApiResponse(data=CourseDetail.model_validate(course))


@router.post("/courses", response_model=ApiResponse[CourseRead], status_code=status.HTTP_201_CREATED)
def create_course(
    payload: CourseCreate, _: User = Depends(admin_only), db: Session = Depends(get_db)
) -> ApiResponse[CourseRead]:
    course = CourseService(db).create_course(payload)
    return ApiResponse(message="课程创建成功", data=CourseRead.model_validate(course))


@router.put("/courses/{course_id}", response_model=ApiResponse[CourseRead])
def update_course(
    course_id: int,
    payload: CourseUpdate,
    _: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> ApiResponse[CourseRead]:
    course = CourseService(db).update_course(course_id, payload)
    return ApiResponse(message="课程更新成功", data=CourseRead.model_validate(course))


@router.delete("/courses/{course_id}", response_model=ApiResponse[dict[str, int]])
def delete_course(
    course_id: int, _: User = Depends(admin_only), db: Session = Depends(get_db)
) -> ApiResponse[dict[str, int]]:
    service = CourseService(db)
    course = service.require_course(course_id)
    service.courses.delete(course)
    return ApiResponse(message="课程删除成功", data={"id": course_id})


@router.get("/courses/{course_id}/chapters", response_model=ApiResponse[list[ChapterRead]])
def list_chapters(
    course_id: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ApiResponse[list[ChapterRead]]:
    CourseService(db).require_course(course_id)
    chapters = ChapterRepository(db).list_by_course(course_id)
    return ApiResponse(data=[ChapterRead.model_validate(chapter) for chapter in chapters])


@router.post(
    "/courses/{course_id}/chapters",
    response_model=ApiResponse[ChapterRead],
    status_code=status.HTTP_201_CREATED,
)
def create_chapter(
    course_id: int,
    payload: ChapterCreate,
    _: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> ApiResponse[ChapterRead]:
    chapter = CourseService(db).create_chapter(course_id, payload)
    return ApiResponse(message="章节创建成功", data=ChapterRead.model_validate(chapter))


@router.get("/chapters/{chapter_id}", response_model=ApiResponse[ChapterRead])
def get_chapter(
    chapter_id: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ApiResponse[ChapterRead]:
    chapter = CourseService(db).require_chapter(chapter_id)
    return ApiResponse(data=ChapterRead.model_validate(chapter))


@router.put("/chapters/{chapter_id}", response_model=ApiResponse[ChapterRead])
def update_chapter(
    chapter_id: int,
    payload: ChapterUpdate,
    _: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> ApiResponse[ChapterRead]:
    chapter = CourseService(db).update_chapter(chapter_id, payload)
    return ApiResponse(message="章节更新成功", data=ChapterRead.model_validate(chapter))


@router.delete("/chapters/{chapter_id}", response_model=ApiResponse[dict[str, int]])
def delete_chapter(
    chapter_id: int, _: User = Depends(admin_only), db: Session = Depends(get_db)
) -> ApiResponse[dict[str, int]]:
    service = CourseService(db)
    chapter = service.require_chapter(chapter_id)
    service.chapters.delete(chapter)
    return ApiResponse(message="章节删除成功", data={"id": chapter_id})

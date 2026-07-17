from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_roles
from app.db.session import get_db
from app.models.user import User
from app.repositories.course_repository import ChapterRepository, CourseRepository
from app.repositories.knowledge_repository import KnowledgeRepository
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
from app.services.chapter_extractor import extract_chapters
from app.rag.document_loader import extract_text
from app.services.knowledge_service import KnowledgeService
from app.services.citation_service import CitationService


router = APIRouter(tags=["courses"])
admin_only = require_roles("admin")


@router.get("/courses", response_model=ApiResponse[list[CourseRead]])
def list_courses(
    _: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ApiResponse[list[CourseRead]]:
    courses = CourseRepository(db).list()
    return ApiResponse(data=[CourseRead.model_validate(course) for course in courses])


@router.post("/courses/import", response_model=ApiResponse[CourseRead], status_code=status.HTTP_201_CREATED)
async def import_course(
    name: str = Form(..., min_length=1, max_length=100),
    description: str | None = Form(None, max_length=2000),
    file: UploadFile | None = File(None),
    _: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> ApiResponse[CourseRead]:
    """创建教材课程，并可在同一次导入中建立第一份知识库资料。"""
    course = CourseService(db).create_course(CourseCreate(name=name, description=description))
    if file is not None:
        content = await file.read()
        filename = file.filename or "教材资料.txt"
        text = extract_text(filename, content)
        source_title = (file.filename or "教材资料").rsplit(".", 1)[0]
        course_service = CourseService(db)
        chapters = []
        for sort_order, (title, chapter_content) in enumerate(extract_chapters(text), start=1):
            chapters.append(course_service.create_chapter(
                course.id,
                ChapterCreate(title=title, content=chapter_content, sort_order=sort_order),
            ))
        document = KnowledgeService(db).ingest(
            filename=filename,
            content=content,
            source_title=source_title,
            course_id=course.id,
            chapter_id=None,
            knowledge_point=None,
            defer_index=True,
        )
        CitationService(db).auto_calibrate(document.id, chapters)
    message = "教材、专题和知识库已自动建立" if file else "教材创建成功"
    return ApiResponse(message=message, data=CourseRead.model_validate(course))


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
    # 清理该教材的原始资料与 Chroma 向量，避免删除课程后留下孤立知识库数据。
    knowledge_service = KnowledgeService(db)
    for document in KnowledgeRepository(db).list(course_id=course_id):
        knowledge_service.delete(document.id)
    service.courses.delete(course)
    return ApiResponse(message="教材及其知识库资料删除成功", data={"id": course_id})


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

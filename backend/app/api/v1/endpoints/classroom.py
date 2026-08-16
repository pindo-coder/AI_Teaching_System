from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_roles
from app.core.time import utc_now
from app.db.session import get_db
from app.models.chapter import Chapter
from app.models.classroom import ClassroomActivity, ClassroomResponse, DiscussionReply, DiscussionThread
from app.models.course import Course
from app.models.user import User
from app.models.teaching_class import ClassMembership, TeachingClass, TeachingClassMaterial, TeachingClassTeacher
from app.schemas.classroom import (
    ActivityCreate, ActivityRead, DiscussionAuthor, DiscussionCreate, DiscussionReplyCreate,
    DiscussionReplyRead, DiscussionReplyUpdate, DiscussionThreadRead, DiscussionUpdate,
    ResponseCreate, ResponseRead,
)
from app.schemas.common import ApiResponse


router = APIRouter(prefix="/classroom", tags=["classroom"])


def _class_access(db: Session, user: User, class_id: int) -> None:
    if user.role == "admin":
        return
    if user.role == "student":
        allowed = db.scalar(select(ClassMembership.id).where(
            ClassMembership.teaching_class_id == class_id, ClassMembership.user_id == user.id,
            ClassMembership.status == "active",
        ))
    else:
        allowed = db.scalar(select(TeachingClass.id).where(
            TeachingClass.id == class_id,
            (TeachingClass.owner_id == user.id) | TeachingClass.id.in_(select(TeachingClassTeacher.teaching_class_id).where(TeachingClassTeacher.user_id == user.id)),
        ))
    if allowed is None:
        raise HTTPException(status_code=403, detail="你无权访问该教学班讨论")


def _thread_read(thread: DiscussionThread, author: User) -> DiscussionThreadRead:
    return DiscussionThreadRead(
        id=thread.id, teaching_class_id=thread.teaching_class_id, course_id=thread.course_id,
        chapter_id=thread.chapter_id, activity_id=thread.activity_id, title=thread.title,
        content=thread.content, status=thread.status, is_pinned=thread.is_pinned,
        reply_count=thread.reply_count, last_replied_time=thread.last_replied_time,
        created_time=thread.created_time, updated_time=thread.updated_time,
        author=DiscussionAuthor(id=author.id, name=author.username, role=author.role),
    )


def _reply_read(reply: DiscussionReply, author: User) -> DiscussionReplyRead:
    return DiscussionReplyRead(
        id=reply.id, thread_id=reply.thread_id, parent_reply_id=reply.parent_reply_id,
        content="该回贴已删除" if reply.status == "deleted" else reply.content,
        status=reply.status, created_time=reply.created_time,
        updated_time=reply.updated_time,
        author=DiscussionAuthor(id=author.id, name=author.username, role=author.role),
    )


@router.get("/activities", response_model=ApiResponse[list[ActivityRead]])
def list_activities(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ApiResponse[list[ActivityRead]]:
    statement = select(ClassroomActivity).where(ClassroomActivity.status == "published")
    if current_user.role == "student":
        class_ids = select(ClassMembership.teaching_class_id).where(
            ClassMembership.user_id == current_user.id, ClassMembership.status == "active"
        )
        statement = statement.where(
            (ClassroomActivity.teaching_class_id.is_(None)) | (ClassroomActivity.teaching_class_id.in_(class_ids))
        )
    elif current_user.role == "teacher":
        class_ids = select(TeachingClassTeacher.teaching_class_id).where(
            TeachingClassTeacher.user_id == current_user.id
        )
        statement = statement.where(
            (ClassroomActivity.teaching_class_id.is_(None)) | (ClassroomActivity.teaching_class_id.in_(class_ids))
        )
    activities = db.scalars(statement.order_by(ClassroomActivity.id.desc())).all()
    return ApiResponse(data=list(activities))


@router.post("/activities", response_model=ApiResponse[ActivityRead], status_code=status.HTTP_201_CREATED)
def publish_activity(payload: ActivityCreate, current_user: User = Depends(require_roles("teacher", "admin")), db: Session = Depends(get_db)) -> ApiResponse[ActivityRead]:
    if db.get(Course, payload.course_id) is None or db.scalar(select(Chapter).where(Chapter.id == payload.chapter_id, Chapter.course_id == payload.course_id)) is None:
        raise HTTPException(status_code=404, detail="教材或专题不存在")
    if payload.teaching_class_id is not None:
        from app.services.teaching_class_service import TeachingClassService
        TeachingClassService(db).require_teacher(payload.teaching_class_id, current_user)
        if db.scalar(select(TeachingClassMaterial.id).where(
            TeachingClassMaterial.teaching_class_id == payload.teaching_class_id,
            TeachingClassMaterial.course_id == payload.course_id,
        )) is None:
            raise HTTPException(status_code=400, detail="该教材未绑定到当前教学班")
    activity = ClassroomActivity(**payload.model_dump(), created_by=current_user.id)
    db.add(activity)
    db.commit()
    db.refresh(activity)
    return ApiResponse(message="课堂互动已发布", data=activity)


@router.post("/activities/{activity_id}/responses", response_model=ApiResponse[ResponseRead], status_code=status.HTTP_201_CREATED)
def submit_response(activity_id: int, payload: ResponseCreate, current_user: User = Depends(require_roles("student", "teacher", "admin")), db: Session = Depends(get_db)) -> ApiResponse[ResponseRead]:
    activity = db.get(ClassroomActivity, activity_id)
    if activity is None or activity.status != "published":
        raise HTTPException(status_code=404, detail="课堂互动不存在或已结束")
    if activity.teaching_class_id is not None and current_user.role == "student":
        membership = db.scalar(select(ClassMembership.id).where(
            ClassMembership.teaching_class_id == activity.teaching_class_id,
            ClassMembership.user_id == current_user.id,
            ClassMembership.status == "active",
        ))
        if membership is None:
            raise HTTPException(status_code=403, detail="你不属于该课堂互动所在教学班")
    response = ClassroomResponse(activity_id=activity_id, user_id=current_user.id, answer=payload.answer.strip())
    db.add(response)
    db.commit()
    db.refresh(response)
    return ApiResponse(message="观点提交成功", data=response)


@router.get("/discussions", response_model=ApiResponse[list[DiscussionThreadRead]])
def list_discussions(
    teaching_class_id: int | None = None,
    chapter_id: int | None = None,
    activity_id: int | None = None,
    keyword: str | None = Query(default=None, max_length=100),
    sort: str = Query(default="latest", pattern="^(latest|hot|unanswered)$"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=30, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[list[DiscussionThreadRead]]:
    statement = select(DiscussionThread)
    statement = statement.where(DiscussionThread.status.in_(["published", "closed"]))
    if current_user.role == "student":
        class_ids = select(ClassMembership.teaching_class_id).where(
            ClassMembership.user_id == current_user.id, ClassMembership.status == "active"
        )
        statement = statement.where(
            DiscussionThread.teaching_class_id.is_(None) | DiscussionThread.teaching_class_id.in_(class_ids)
        )
    elif current_user.role == "teacher":
        class_ids = select(TeachingClassTeacher.teaching_class_id).where(TeachingClassTeacher.user_id == current_user.id)
        owned_class_ids = select(TeachingClass.id).where(TeachingClass.owner_id == current_user.id)
        statement = statement.where(
            DiscussionThread.teaching_class_id.is_(None)
            | DiscussionThread.teaching_class_id.in_(class_ids.union(owned_class_ids))
        )
    if teaching_class_id is not None:
        _class_access(db, current_user, teaching_class_id)
        statement = statement.where(DiscussionThread.teaching_class_id == teaching_class_id)
    if chapter_id is not None:
        statement = statement.where(DiscussionThread.chapter_id == chapter_id)
    if activity_id is not None:
        statement = statement.where(DiscussionThread.activity_id == activity_id)
    if keyword and keyword.strip():
        term = f"%{keyword.strip()}%"
        statement = statement.where(DiscussionThread.title.like(term) | DiscussionThread.content.like(term))
    if sort == "hot":
        statement = statement.order_by(DiscussionThread.is_pinned.desc(), DiscussionThread.reply_count.desc(), DiscussionThread.updated_time.desc())
    elif sort == "unanswered":
        statement = statement.where(DiscussionThread.reply_count == 0).order_by(DiscussionThread.created_time.desc())
    else:
        statement = statement.order_by(DiscussionThread.is_pinned.desc(), DiscussionThread.updated_time.desc())
    threads = db.scalars(statement.offset(offset).limit(limit)).all()
    authors = {user.id: user for user in db.scalars(select(User).where(User.id.in_([item.author_id for item in threads]))).all()}
    return ApiResponse(data=[_thread_read(item, authors[item.author_id]) for item in threads if item.author_id in authors])


def _validate_discussion_context(payload: DiscussionCreate, current_user: User, db: Session) -> None:
    if payload.teaching_class_id is not None:
        _class_access(db, current_user, payload.teaching_class_id)
    if payload.course_id is not None and db.get(Course, payload.course_id) is None:
        raise HTTPException(status_code=404, detail="课程不存在")
    if payload.chapter_id is not None:
        if payload.course_id is None:
            raise HTTPException(status_code=422, detail="选择专题前请先选择课程")
        if db.scalar(select(Chapter.id).where(Chapter.id == payload.chapter_id, Chapter.course_id == payload.course_id)) is None:
            raise HTTPException(status_code=404, detail="专题不存在或不属于所选课程")
    if payload.teaching_class_id is not None and payload.course_id is not None and db.scalar(select(TeachingClassMaterial.id).where(
        TeachingClassMaterial.teaching_class_id == payload.teaching_class_id,
        TeachingClassMaterial.course_id == payload.course_id,
    )) is None:
        raise HTTPException(status_code=400, detail="该课程未绑定到当前教学班")
    if payload.activity_id is not None:
        if payload.teaching_class_id is None:
            raise HTTPException(status_code=400, detail="关联课堂活动时必须选择教学班")
        activity = db.get(ClassroomActivity, payload.activity_id)
        if activity is None or activity.teaching_class_id != payload.teaching_class_id:
            raise HTTPException(status_code=400, detail="关联的课堂活动无效")


@router.post("/discussions", response_model=ApiResponse[DiscussionThreadRead], status_code=status.HTTP_201_CREATED)
def create_discussion(
    payload: DiscussionCreate,
    current_user: User = Depends(require_roles("student", "teacher", "admin")),
    db: Session = Depends(get_db),
) -> ApiResponse[DiscussionThreadRead]:
    _validate_discussion_context(payload, current_user, db)
    title = payload.title.strip()
    content = payload.content.strip()
    if not title or not content:
        raise HTTPException(status_code=422, detail="讨论标题和内容不能为空")
    now = utc_now()
    thread = DiscussionThread(
        **payload.model_dump(exclude={"title", "content"}), title=title, content=content,
        author_id=current_user.id, created_time=now, updated_time=now,
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return ApiResponse(message="讨论已发布", data=_thread_read(thread, current_user))


def _get_thread_for_user(thread_id: int, current_user: User, db: Session) -> DiscussionThread:
    thread = db.get(DiscussionThread, thread_id)
    if thread is None or thread.status not in {"published", "closed"}:
        raise HTTPException(status_code=404, detail="讨论不存在或不可见")
    if thread.teaching_class_id is not None:
        _class_access(db, current_user, thread.teaching_class_id)
    return thread


def _is_thread_moderator(thread: DiscussionThread, current_user: User, db: Session) -> bool:
    if current_user.role == "admin":
        return True
    if current_user.role != "teacher" or thread.teaching_class_id is None:
        return False
    return db.scalar(select(TeachingClass.id).where(
        TeachingClass.id == thread.teaching_class_id,
        (TeachingClass.owner_id == current_user.id)
        | TeachingClass.id.in_(select(TeachingClassTeacher.teaching_class_id).where(
            TeachingClassTeacher.user_id == current_user.id
        )),
    )) is not None


@router.get("/discussions/{thread_id}", response_model=ApiResponse[DiscussionThreadRead])
def get_discussion(thread_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ApiResponse[DiscussionThreadRead]:
    thread = _get_thread_for_user(thread_id, current_user, db)
    author = db.get(User, thread.author_id)
    return ApiResponse(data=_thread_read(thread, author))


@router.patch("/discussions/{thread_id}", response_model=ApiResponse[DiscussionThreadRead])
def update_discussion(
    thread_id: int, payload: DiscussionUpdate, current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[DiscussionThreadRead]:
    thread = _get_thread_for_user(thread_id, current_user, db)
    if thread.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="只能编辑自己发布的讨论")
    values = payload.model_dump(exclude_unset=True)
    if "title" in values:
        thread.title = values["title"].strip()
    if "content" in values:
        thread.content = values["content"].strip()
    if not thread.title or not thread.content:
        raise HTTPException(status_code=422, detail="讨论标题和内容不能为空")
    thread.updated_time = utc_now()
    db.commit()
    db.refresh(thread)
    return ApiResponse(message="讨论已更新", data=_thread_read(thread, current_user))


@router.delete("/discussions/{thread_id}", response_model=ApiResponse[dict[str, int]])
def delete_discussion(
    thread_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> ApiResponse[dict[str, int]]:
    thread = _get_thread_for_user(thread_id, current_user, db)
    if thread.author_id != current_user.id and not _is_thread_moderator(thread, current_user, db):
        raise HTTPException(status_code=403, detail="你无权删除该讨论")
    thread.status = "deleted"
    thread.is_pinned = False
    thread.updated_time = utc_now()
    db.commit()
    return ApiResponse(message="讨论已删除", data={"id": thread.id})


@router.get("/discussions/{thread_id}/replies", response_model=ApiResponse[list[DiscussionReplyRead]])
def list_discussion_replies(thread_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ApiResponse[list[DiscussionReplyRead]]:
    _get_thread_for_user(thread_id, current_user, db)
    replies = db.scalars(select(DiscussionReply).where(
        DiscussionReply.thread_id == thread_id, DiscussionReply.status.in_(["published", "deleted"])
    ).order_by(DiscussionReply.created_time.asc())).all()
    authors = {user.id: user for user in db.scalars(select(User).where(User.id.in_([item.author_id for item in replies]))).all()}
    return ApiResponse(data=[_reply_read(item, authors[item.author_id]) for item in replies if item.author_id in authors])


@router.post("/discussions/{thread_id}/replies", response_model=ApiResponse[DiscussionReplyRead], status_code=status.HTTP_201_CREATED)
def create_discussion_reply(
    thread_id: int,
    payload: DiscussionReplyCreate,
    current_user: User = Depends(require_roles("student", "teacher", "admin")),
    db: Session = Depends(get_db),
) -> ApiResponse[DiscussionReplyRead]:
    thread = _get_thread_for_user(thread_id, current_user, db)
    if thread.status == "closed":
        raise HTTPException(status_code=400, detail="该讨论已关闭")
    if payload.parent_reply_id is not None:
        parent = db.get(DiscussionReply, payload.parent_reply_id)
        if parent is None or parent.thread_id != thread_id or parent.status != "published":
            raise HTTPException(status_code=400, detail="回复目标不存在")
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=422, detail="回贴内容不能为空")
    now = utc_now()
    reply = DiscussionReply(
        thread_id=thread_id, author_id=current_user.id, content=content,
        parent_reply_id=payload.parent_reply_id, created_time=now, updated_time=now,
    )
    db.add(reply)
    thread.reply_count += 1
    thread.last_replied_time = now
    thread.updated_time = now
    db.commit()
    db.refresh(reply)
    return ApiResponse(message="回贴成功", data=_reply_read(reply, current_user))


@router.patch("/discussions/replies/{reply_id}", response_model=ApiResponse[DiscussionReplyRead])
def update_discussion_reply(
    reply_id: int, payload: DiscussionReplyUpdate, current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[DiscussionReplyRead]:
    reply = db.get(DiscussionReply, reply_id)
    if reply is None or reply.status != "published":
        raise HTTPException(status_code=404, detail="回贴不存在")
    _get_thread_for_user(reply.thread_id, current_user, db)
    if reply.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="只能编辑自己的回贴")
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=422, detail="回贴内容不能为空")
    reply.content = content
    reply.updated_time = utc_now()
    db.commit()
    db.refresh(reply)
    return ApiResponse(message="回贴已更新", data=_reply_read(reply, current_user))


@router.delete("/discussions/replies/{reply_id}", response_model=ApiResponse[dict[str, int]])
def delete_discussion_reply(
    reply_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> ApiResponse[dict[str, int]]:
    reply = db.get(DiscussionReply, reply_id)
    if reply is None or reply.status != "published":
        raise HTTPException(status_code=404, detail="回贴不存在")
    thread = _get_thread_for_user(reply.thread_id, current_user, db)
    if reply.author_id != current_user.id and not _is_thread_moderator(thread, current_user, db):
        raise HTTPException(status_code=403, detail="你无权删除该回贴")
    reply.status = "deleted"
    reply.updated_time = utc_now()
    db.commit()
    return ApiResponse(message="回贴已删除", data={"id": reply.id})


@router.post("/discussions/{thread_id}/pin", response_model=ApiResponse[DiscussionThreadRead])
def pin_discussion(thread_id: int, current_user: User = Depends(require_roles("teacher", "admin")), db: Session = Depends(get_db)) -> ApiResponse[DiscussionThreadRead]:
    thread = _get_thread_for_user(thread_id, current_user, db)
    if not _is_thread_moderator(thread, current_user, db):
        raise HTTPException(status_code=403, detail="只有班级任课教师或管理员可以置顶")
    thread.is_pinned = not thread.is_pinned
    thread.updated_time = utc_now()
    db.commit()
    db.refresh(thread)
    author = db.get(User, thread.author_id)
    return ApiResponse(message="置顶状态已更新", data=_thread_read(thread, author))


@router.post("/discussions/{thread_id}/close", response_model=ApiResponse[DiscussionThreadRead])
def close_discussion(thread_id: int, current_user: User = Depends(require_roles("teacher", "admin")), db: Session = Depends(get_db)) -> ApiResponse[DiscussionThreadRead]:
    thread = _get_thread_for_user(thread_id, current_user, db)
    if not _is_thread_moderator(thread, current_user, db):
        raise HTTPException(status_code=403, detail="只有班级任课教师或管理员可以关闭讨论")
    thread.status = "published" if thread.status == "closed" else "closed"
    thread.updated_time = utc_now()
    db.commit()
    db.refresh(thread)
    author = db.get(User, thread.author_id)
    return ApiResponse(message="讨论状态已更新", data=_thread_read(thread, author))

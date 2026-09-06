from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_roles
from app.core.time import to_utc_naive, utc_now
from app.db.session import get_db
from app.models.chapter import Chapter
from app.models.classroom import ClassroomActivity, ClassroomResponse, DiscussionReply, DiscussionThread
from app.models.course import Course
from app.models.user import User
from app.models.teaching_class import ClassGroup, ClassGroupMember, ClassMembership, TeachingClass, TeachingClassMaterial, TeachingClassTeacher
from app.schemas.classroom import (
    ActivityCreate, ActivityRead, ActivityResponsesRead, DiscussionAuthor, DiscussionCreate,
    DiscussionReplyCreate, DiscussionReplyRead, DiscussionReplyUpdate, DiscussionThreadRead,
    DiscussionUpdate, ResponseCommentUpdate, ResponseCreate, ResponseRead,
)
from app.schemas.common import ApiResponse
from app.schemas.ai import AiAssistRequest
from app.services.ai_service import AiService


router = APIRouter(prefix="/classroom", tags=["classroom"])


def _activity_read(activity: ClassroomActivity, current_user: User, db: Session) -> ActivityRead:
    response_count = db.scalar(select(func.count(func.distinct(ClassroomResponse.user_id))).join(
        User, User.id == ClassroomResponse.user_id
    ).where(
        ClassroomResponse.activity_id == activity.id, User.role == "student"
    )) or 0
    my_response_count = db.scalar(select(func.count(ClassroomResponse.id)).where(
        ClassroomResponse.activity_id == activity.id, ClassroomResponse.user_id == current_user.id
    )) or 0
    return ActivityRead.model_validate(activity).model_copy(update={
        "response_count": int(response_count), "my_response_count": int(my_response_count),
    })


def _activity_or_404(activity_id: int, db: Session) -> ClassroomActivity:
    activity = db.get(ClassroomActivity, activity_id)
    if activity is None:
        raise HTTPException(status_code=404, detail="课堂互动不存在")
    return activity


def _check_activity_access(activity: ClassroomActivity, current_user: User, db: Session) -> None:
    if activity.teaching_class_id is None:
        return
    if current_user.role == "student":
        membership = db.scalar(select(ClassMembership.id).where(
            ClassMembership.teaching_class_id == activity.teaching_class_id,
            ClassMembership.user_id == current_user.id,
            ClassMembership.status == "active",
        ))
        if membership is None:
            raise HTTPException(status_code=403, detail="你不属于该课堂互动所在教学班")
    else:
        _class_access(db, current_user, activity.teaching_class_id)


def _response_read(response: ClassroomResponse, user_name: str) -> ResponseRead:
    return ResponseRead(
        id=response.id, activity_id=response.activity_id, user_id=response.user_id,
        user_name=user_name, answer=response.answer, attempt_no=response.attempt_no,
        group_id=response.group_id, teacher_comment=response.teacher_comment,
        ai_comment=response.ai_comment, commented_by=response.commented_by,
        commented_time=response.commented_time, created_time=response.created_time,
    )


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
    statement = select(ClassroomActivity).where(ClassroomActivity.status.in_(["published", "closed"]))
    if current_user.role == "student":
        class_ids = select(ClassMembership.teaching_class_id).where(
            ClassMembership.user_id == current_user.id, ClassMembership.status == "active"
        )
        statement = statement.where(
            (ClassroomActivity.teaching_class_id.is_(None)) | (ClassroomActivity.teaching_class_id.in_(class_ids))
        )
    elif current_user.role == "teacher":
        class_ids = select(TeachingClassTeacher.teaching_class_id).where(TeachingClassTeacher.user_id == current_user.id)
        owned_class_ids = select(TeachingClass.id).where(TeachingClass.owner_id == current_user.id)
        statement = statement.where(
            (ClassroomActivity.teaching_class_id.is_(None))
            | (ClassroomActivity.teaching_class_id.in_(class_ids.union(owned_class_ids)))
        )
    activities = db.scalars(statement.order_by(ClassroomActivity.id.desc())).all()
    return ApiResponse(data=[_activity_read(item, current_user, db) for item in activities])


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
    if payload.activity_type == "group":
        if payload.teaching_class_id is None or payload.grouping_mode not in {"manual", "random"}:
            raise HTTPException(status_code=400, detail="小组讨论必须选择教学班和分组方式")
        if not db.scalar(select(ClassGroup.id).where(ClassGroup.teaching_class_id == payload.teaching_class_id)):
            raise HTTPException(status_code=400, detail="请先完成教学班分组")
    if payload.activity_type != "group" and payload.grouping_mode is not None:
        raise HTTPException(status_code=400, detail="只有小组讨论需要分组方式")
    values = payload.model_dump()
    values["deadline_time"] = to_utc_naive(payload.deadline_time) if payload.deadline_time else None
    activity = ClassroomActivity(**values, created_by=current_user.id)
    db.add(activity)
    db.commit()
    db.refresh(activity)
    return ApiResponse(message="课堂互动已发布", data=_activity_read(activity, current_user, db))


@router.post("/activities/{activity_id}/responses", response_model=ApiResponse[ResponseRead], status_code=status.HTTP_201_CREATED)
def submit_response(activity_id: int, payload: ResponseCreate, current_user: User = Depends(require_roles("student", "teacher", "admin")), db: Session = Depends(get_db)) -> ApiResponse[ResponseRead]:
    activity = _activity_or_404(activity_id, db)
    if activity.status != "published":
        raise HTTPException(status_code=404, detail="课堂互动不存在或已结束")
    _check_activity_access(activity, current_user, db)
    if activity.deadline_time and activity.deadline_time < utc_now():
        raise HTTPException(status_code=400, detail="该课堂互动已超过截止时间")
    submitted_count = db.scalar(select(func.count(ClassroomResponse.id)).where(
        ClassroomResponse.activity_id == activity_id, ClassroomResponse.user_id == current_user.id
    )) or 0
    if submitted_count >= activity.response_limit:
        raise HTTPException(status_code=400, detail=f"该活动最多提交 {activity.response_limit} 次")
    group_id = None
    if activity.activity_type == "group":
        membership = db.execute(select(ClassGroupMember, ClassGroup).join(
            ClassGroup, ClassGroup.id == ClassGroupMember.group_id
        ).where(
            ClassGroupMember.teaching_class_id == activity.teaching_class_id,
            ClassGroupMember.user_id == current_user.id,
        )).first()
        if membership is None:
            raise HTTPException(status_code=400, detail="你还没有加入当前教学班的小组")
        group_member, group = membership
        if group.leader_user_id != current_user.id:
            raise HTTPException(status_code=403, detail="小组讨论仅限组长提交")
        group_id = group_member.group_id
    response = ClassroomResponse(
        activity_id=activity_id, user_id=current_user.id, answer=payload.answer.strip(),
        attempt_no=int(submitted_count) + 1, group_id=group_id,
    )
    db.add(response)
    db.commit()
    db.refresh(response)
    return ApiResponse(message="回答提交成功", data=_response_read(response, current_user.username))


@router.get("/activities/{activity_id}/responses", response_model=ApiResponse[ActivityResponsesRead])
def list_activity_responses(
    activity_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[ActivityResponsesRead]:
    activity = _activity_or_404(activity_id, db)
    _check_activity_access(activity, current_user, db)
    responses = db.scalars(select(ClassroomResponse).join(
        User, User.id == ClassroomResponse.user_id
    ).where(
        ClassroomResponse.activity_id == activity_id, User.role == "student"
    ).order_by(ClassroomResponse.created_time, ClassroomResponse.id)).all()
    users = {user.id: user for user in db.scalars(select(User).where(
        User.id.in_([item.user_id for item in responses])
    )).all()} if responses else {}
    anonymous_names: dict[int, str] = {}
    next_anonymous = 1
    response_items: list[ResponseRead] = []
    for item in responses:
        account = users.get(item.user_id)
        if account is None:
            continue
        if current_user.role in {"teacher", "admin"}:
            display_name = account.username
        elif item.user_id == current_user.id:
            display_name = "我的回答"
        else:
            if item.user_id not in anonymous_names:
                anonymous_names[item.user_id] = f"同学{next_anonymous}"
                next_anonymous += 1
            display_name = anonymous_names[item.user_id]
        response_items.append(_response_read(item, display_name))
    response_count = len({item.user_id for item in responses})
    return ApiResponse(data=ActivityResponsesRead(
        activity=_activity_read(activity, current_user, db),
        responses=response_items,
        response_count=response_count,
    ))


@router.patch("/activities/{activity_id}/responses/{response_id}", response_model=ApiResponse[ResponseRead])
def comment_activity_response(
    activity_id: int,
    response_id: int,
    payload: ResponseCommentUpdate,
    current_user: User = Depends(require_roles("teacher", "admin")),
    db: Session = Depends(get_db),
) -> ApiResponse[ResponseRead]:
    activity = _activity_or_404(activity_id, db)
    _check_activity_access(activity, current_user, db)
    response = db.scalar(select(ClassroomResponse).where(
        ClassroomResponse.id == response_id, ClassroomResponse.activity_id == activity_id
    ))
    if response is None:
        raise HTTPException(status_code=404, detail="学生回答不存在")
    response.teacher_comment = payload.teacher_comment.strip() or None
    response.commented_by = current_user.id
    response.commented_time = utc_now()
    db.commit()
    db.refresh(response)
    student = db.get(User, response.user_id)
    return ApiResponse(message="教师点评已保存", data=_response_read(response, student.username if student else "学生"))


@router.post("/activities/{activity_id}/responses/{response_id}/ai-review", response_model=ApiResponse[ResponseRead])
def ai_review_activity_response(
    activity_id: int,
    response_id: int,
    current_user: User = Depends(require_roles("teacher", "admin")),
    db: Session = Depends(get_db),
) -> ApiResponse[ResponseRead]:
    activity = _activity_or_404(activity_id, db)
    _check_activity_access(activity, current_user, db)
    response = db.scalar(select(ClassroomResponse).where(
        ClassroomResponse.id == response_id, ClassroomResponse.activity_id == activity_id
    ))
    if response is None:
        raise HTTPException(status_code=404, detail="学生回答不存在")
    result = AiService(db, user=current_user).assist(AiAssistRequest(
        course_id=activity.course_id,
        chapter_id=activity.chapter_id,
        learning_stage="review",
        task_type="question_answer",
        question=(
            "请作为课堂助教，基于当前专题教材，对下面这份学生回答生成简洁、具体、可执行的点评。"
            "请分别指出回答中的优点、需要补充的教材依据和一个改进建议，不要虚构教材内容。\n\n"
            f"课堂问题：{activity.question}\n学生回答：{response.answer}"
        ),
        assistant_role="teacher",
    ))
    response.ai_comment = result.answer.strip() or None
    response.commented_by = current_user.id
    response.commented_time = utc_now()
    db.commit()
    db.refresh(response)
    student = db.get(User, response.user_id)
    return ApiResponse(message="AI 辅助点评已生成", data=_response_read(response, student.username if student else "学生"))


@router.post("/activities/{activity_id}/close", response_model=ApiResponse[ActivityRead])
def close_activity(
    activity_id: int,
    current_user: User = Depends(require_roles("teacher", "admin")),
    db: Session = Depends(get_db),
) -> ApiResponse[ActivityRead]:
    activity = _activity_or_404(activity_id, db)
    _check_activity_access(activity, current_user, db)
    activity.status = "closed"
    db.commit()
    db.refresh(activity)
    return ApiResponse(message="课堂互动已结束", data=_activity_read(activity, current_user, db))


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

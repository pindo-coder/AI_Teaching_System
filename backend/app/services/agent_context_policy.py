"""工作台 Agent 的统一上下文授权策略。"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.chapter import Chapter
from app.models.course import Course
from app.models.teaching_class import ClassMembership, TeachingClass, TeachingClassMaterial, TeachingClassTeacher
from app.models.user import User
from app.schemas.ai import AiWorkspaceContextData


class AgentContextPolicy:
    """在进入规划器前验证课程、专题和教学班边界。"""

    def __init__(self, db: Session, user: User) -> None:
        self.db = db
        self.user = user

    def validate(self, context: AiWorkspaceContextData) -> AiWorkspaceContextData:
        if context.course_id is None and context.chapter_id is None:
            return context
        if context.course_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="选择专题时必须同时提供课程")
        course = self.db.get(Course, context.course_id)
        if course is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="课程不存在")
        if context.chapter_id is not None:
            chapter = self.db.get(Chapter, context.chapter_id)
            if chapter is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="专题不存在")
            if chapter.course_id != course.id:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="专题与课程不匹配")
        for chapter_id in context.chapter_ids:
            selected = self.db.get(Chapter, chapter_id)
            if selected is None or selected.course_id != course.id:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="所选专题必须属于同一课程")

        # 当用户已有可见教学班时，裸课程 ID 也必须属于其教学范围；没有
        # 教学班的本地课程/学习测试数据仍允许访问，兼容课程中心场景。
        if self.user.role != "admin":
            visible_class_ids = set(self.db.scalars(
                select(TeachingClass.id).where(
                    (TeachingClass.owner_id == self.user.id)
                    | TeachingClass.id.in_(select(TeachingClassTeacher.teaching_class_id).where(TeachingClassTeacher.user_id == self.user.id))
                    | TeachingClass.id.in_(select(ClassMembership.teaching_class_id).where(
                        ClassMembership.user_id == self.user.id,
                        ClassMembership.status == "active",
                    ))
                )
            ).all())
            if visible_class_ids:
                allowed_course_ids = set(self.db.scalars(select(TeachingClassMaterial.course_id).where(
                    TeachingClassMaterial.teaching_class_id.in_(visible_class_ids)
                )).all())
                if context.course_id not in allowed_course_ids:
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权使用该课程上下文")

        class_id = context.teaching_class_id
        if class_id is None or self.user.role == "admin":
            return context
        teaching_class = self.db.get(TeachingClass, class_id)
        if teaching_class is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="教学班不存在")
        if self.user.role == "teacher":
            allowed = self.db.scalar(
                select(TeachingClass.id)
                .outerjoin(TeachingClassTeacher, TeachingClassTeacher.teaching_class_id == TeachingClass.id)
                .where(
                    TeachingClass.id == class_id,
                    or_(TeachingClass.owner_id == self.user.id, TeachingClassTeacher.user_id == self.user.id),
                )
            )
        else:
            allowed = self.db.scalar(
                select(ClassMembership.id).where(
                    ClassMembership.teaching_class_id == class_id,
                    ClassMembership.user_id == self.user.id,
                    ClassMembership.status == "active",
                )
            )
        if allowed is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权使用该教学班上下文")
        return context

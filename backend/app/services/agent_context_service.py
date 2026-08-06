"""为全局教学 Agent 推断、校验并解释当前教学上下文。

优先级故意保持可解释：页面显式范围 > 用户手动选择 > 最近学习/任务 > 默认教学班。
这里不让模型自行猜测教材，避免新建课程后误落到旧教材或其他教学班。
"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.chapter import Chapter
from app.models.course import Course
from app.models.learning_progress import LearningProgress
from app.models.teacher_assignment import AssignmentRecipient, TeacherAssignment
from app.models.teaching_class import (
    ClassMembership,
    TeachingClass,
    TeachingClassMaterial,
    TeachingClassTeacher,
)
from app.models.user import User
from app.schemas.ai import AiWorkspaceContextCandidate, AiWorkspaceContextData


class AgentContextService:
    def __init__(self, db: Session, user: User) -> None:
        self.db = db
        self.user = user

    def _visible_classes(self) -> list[TeachingClass]:
        statement = select(TeachingClass).order_by(
            TeachingClass.is_default.desc(), TeachingClass.updated_time.desc(), TeachingClass.id.desc()
        )
        if self.user.role == "admin":
            return list(self.db.scalars(statement).all())
        if self.user.role == "student":
            return list(self.db.scalars(
                statement.join(ClassMembership, ClassMembership.teaching_class_id == TeachingClass.id).where(
                    ClassMembership.user_id == self.user.id,
                    ClassMembership.status == "active",
                )
            ).all())
        return list(self.db.scalars(
            statement.outerjoin(
                TeachingClassTeacher,
                TeachingClassTeacher.teaching_class_id == TeachingClass.id,
            ).where(
                or_(
                    TeachingClass.owner_id == self.user.id,
                    TeachingClassTeacher.user_id == self.user.id,
                )
            ).distinct()
        ).all())

    def _class_courses(self, teaching_class_id: int) -> list[Course]:
        rows = self.db.execute(
            select(Course)
            .join(TeachingClassMaterial, TeachingClassMaterial.course_id == Course.id)
            .where(TeachingClassMaterial.teaching_class_id == teaching_class_id)
            .order_by(
                (TeachingClassMaterial.material_role == "primary").desc(),
                TeachingClassMaterial.sort_order,
                Course.id,
            )
        ).scalars().all()
        return list(rows)

    def _recent_learning(self, course_id: int | None = None) -> LearningProgress | None:
        statement = select(LearningProgress).where(LearningProgress.user_id == self.user.id)
        if course_id is not None:
            statement = statement.where(LearningProgress.course_id == course_id)
        return self.db.scalar(statement.order_by(LearningProgress.last_study_time.desc(), LearningProgress.id.desc()))

    def _recent_assignment(self, course_id: int | None = None) -> TeacherAssignment | None:
        if self.user.role == "student":
            statement = (
                select(TeacherAssignment)
                .join(AssignmentRecipient, AssignmentRecipient.assignment_id == TeacherAssignment.id)
                .where(
                    AssignmentRecipient.user_id == self.user.id,
                    TeacherAssignment.status == "published",
                )
            )
        else:
            statement = select(TeacherAssignment).where(TeacherAssignment.created_by == self.user.id)
        if course_id is not None:
            statement = statement.where(TeacherAssignment.course_id == course_id)
        return self.db.scalar(statement.order_by(TeacherAssignment.created_time.desc(), TeacherAssignment.id.desc()))

    def _state_summary(self) -> list[str]:
        if self.user.role == "student":
            pending = self.db.scalar(
                select(AssignmentRecipient.id)
                .join(TeacherAssignment, TeacherAssignment.id == AssignmentRecipient.assignment_id)
                .where(
                    AssignmentRecipient.user_id == self.user.id,
                    AssignmentRecipient.status != "completed",
                    TeacherAssignment.status == "published",
                )
                .limit(1)
            )
            return ["存在待完成教师任务" if pending else "当前没有待完成教师任务"]
        waiting = self.db.scalar(
            select(TeacherAssignment.id)
            .where(TeacherAssignment.created_by == self.user.id, TeacherAssignment.status == "published")
            .limit(1)
        )
        return ["可结合已发布教学任务安排备课" if waiting else "可从当前教材专题开始创建教学任务"]

    def resolve(
        self,
        *,
        course_id: int | None = None,
        chapter_id: int | None = None,
        teaching_class_id: int | None = None,
        learning_stage: str = "preview",
        page_name: str | None = None,
    ) -> AiWorkspaceContextData:
        classes = self._visible_classes()
        # 教材可以在课程中心先于教学班创建。教学班只是教学组织边界，不能成为
        # Agent 发现教材的唯一入口，否则教师尚未建班时会被误提示为“没有教材”。
        all_courses = list(self.db.scalars(select(Course).order_by(Course.id)).all())
        classes_by_id = {item.id: item for item in classes}
        source = "none"
        confidence = "low"

        selected_class = classes_by_id.get(teaching_class_id) if teaching_class_id else None
        if teaching_class_id and selected_class is not None:
            source, confidence = "manual", "medium"
        elif classes:
            selected_class = classes[0]
            source, confidence = "default_class", "low"

        course = self.db.get(Course, course_id) if course_id else None
        if course is not None:
            source = "page" if page_name else "manual"
            confidence = "high" if chapter_id else "medium"
            # 课程页面优先级高于默认教学班。若默认班未绑定此教材，绝不把它
            # 误带入后续发布流程；优先切到可见且确实绑定该教材的教学班。
            if selected_class is not None and course.id not in {
                item.id for item in self._class_courses(selected_class.id)
            }:
                selected_class = next(
                    (
                        item
                        for item in classes
                        if course.id in {candidate.id for candidate in self._class_courses(item.id)}
                    ),
                    None,
                )
        elif selected_class is not None:
            class_courses = self._class_courses(selected_class.id)
            course = class_courses[0] if class_courses else None
        elif len(all_courses) == 1:
            # 只有一本教材时可以安全地自动采用；多本教材必须交由用户确认，
            # 避免把新建课程误判为当前教学范围。
            course = all_courses[0]

        recent = self._recent_learning(course.id if course else None)
        assignment = self._recent_assignment(course.id if course else None)
        chapter = self.db.get(Chapter, chapter_id) if chapter_id else None
        if chapter is not None:
            if course is None:
                course = self.db.get(Course, chapter.course_id)
            elif chapter.course_id != course.id:
                chapter = None
        if chapter is not None:
            confidence = "high"
        elif recent is not None and (course is None or recent.course_id == course.id):
            chapter = self.db.get(Chapter, recent.chapter_id)
            if chapter is not None:
                course = self.db.get(Course, chapter.course_id)
                source, confidence = "recent_learning", "medium"
        elif assignment is not None and (course is None or assignment.course_id == course.id):
            chapter = self.db.get(Chapter, assignment.chapter_id)
            course = self.db.get(Course, assignment.course_id)
            if chapter is not None:
                source, confidence = "assignment", "medium"

        # 所有可见教学班-教材组合都会返回前端，便于人工一键纠偏。
        candidates: list[AiWorkspaceContextCandidate] = []
        seen: set[tuple[int, int | None]] = set()
        for item in classes:
            for item_course in self._class_courses(item.id):
                key = (item_course.id, item.id)
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(AiWorkspaceContextCandidate(
                    course_id=item_course.id,
                    course_name=item_course.name,
                    teaching_class_id=item.id,
                    teaching_class_name=item.name,
                ))
        # 没有绑定到可见教学班的教材也应当可选。若同一教材已有班级候选项，
        # 优先展示班级候选项，避免在范围选择器内产生重复条目。
        visible_course_ids = {item.course_id for item in candidates}
        for item_course in all_courses:
            if item_course.id in visible_course_ids:
                continue
            key = (item_course.id, None)
            seen.add(key)
            candidates.append(AiWorkspaceContextCandidate(
                course_id=item_course.id,
                course_name=item_course.name,
                teaching_class_id=None,
                teaching_class_name=None,
            ))
        if course is not None and (course.id, selected_class.id if selected_class else None) not in seen:
            candidates.insert(0, AiWorkspaceContextCandidate(
                course_id=course.id,
                course_name=course.name,
                teaching_class_id=selected_class.id if selected_class else None,
                teaching_class_name=selected_class.name if selected_class else None,
            ))

        chapters = []
        if course is not None:
            chapters = [
                {"id": item.id, "title": item.title, "sort_order": item.sort_order}
                for item in self.db.scalars(
                    select(Chapter).where(Chapter.course_id == course.id).order_by(Chapter.sort_order, Chapter.id)
                ).all()
            ]
        return AiWorkspaceContextData(
            course_id=course.id if course else None,
            course_name=course.name if course else None,
            chapter_id=chapter.id if chapter else None,
            chapter_title=chapter.title if chapter else None,
            teaching_class_id=selected_class.id if selected_class else None,
            teaching_class_name=selected_class.name if selected_class else None,
            learning_stage=learning_stage,  # type: ignore[arg-type]
            source=source,  # type: ignore[arg-type]
            confidence=confidence,  # type: ignore[arg-type]
            requires_chapter_selection=course is not None and chapter is None,
            chapters=chapters,
            candidates=candidates[:24],
            state_summary=self._state_summary(),
        )

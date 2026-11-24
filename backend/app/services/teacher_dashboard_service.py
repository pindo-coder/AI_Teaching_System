from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.time import BUSINESS_TIMEZONE, to_business_time, to_utc_naive, utc_now
from app.models.course import Course
from app.models.knowledge_document import KnowledgeDocument
from app.models.learning_task import LearningEvent
from app.models.material_scope import DocumentClassScope, DocumentCourseScope
from app.models.teacher_assignment import AssignmentRecipient, TeacherAssignment
from app.models.teaching_class import (
    AcademicTerm,
    ClassJoinRequest,
    ClassMembership,
    TeachingClass,
    TeachingClassMaterial,
    TeachingClassTeacher,
)
from app.models.user import User
from app.schemas.teacher_dashboard import (
    TeacherActivityPoint,
    TeacherCourseRow,
    TeacherDashboardData,
    TeacherDashboardMetrics,
    TeacherTodo,
)


VALID_ACTIVITY_TYPES = {
    "reading_progress",
    "ai_assist_used",
    "question_submitted",
    "note_saved",
    "activity_submitted",
    "quiz_completed",
}


class TeacherDashboardService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _class_ids(self, user: User) -> set[int]:
        if user.role == "admin":
            return set(self.db.scalars(select(TeachingClass.id)).all())
        return set(self.db.scalars(select(TeachingClassTeacher.teaching_class_id).where(
            TeachingClassTeacher.user_id == user.id,
        )).all())

    @staticmethod
    def _period(month: str | None) -> tuple[date, date]:
        if month:
            try:
                year, month_number = (int(value) for value in month.split("-", 1))
                if not 1 <= month_number <= 12:
                    raise ValueError
            except (TypeError, ValueError):
                raise ValueError("月份格式应为 YYYY-MM") from None
        else:
            today = datetime.now(BUSINESS_TIMEZONE).date()
            year, month_number = today.year, today.month
        start = date(year, month_number, 1)
        end = date(year, month_number, calendar.monthrange(year, month_number)[1])
        return start, end

    def build(self, user: User, *, month: str | None = None) -> TeacherDashboardData:
        class_ids = self._class_ids(user)
        period_start, period_end = self._period(month)
        period_start_utc = to_utc_naive(datetime.combine(period_start, time.min, BUSINESS_TIMEZONE))
        period_end_utc = to_utc_naive(datetime.combine(period_end + timedelta(days=1), time.min, BUSINESS_TIMEZONE))

        if user.role == "admin":
            student_ids = set(self.db.scalars(select(User.id).where(
                User.role == "student", User.approval_status != "disabled",
            )).all())
        elif class_ids:
            student_ids = set(self.db.scalars(
                select(ClassMembership.user_id)
                .join(User, User.id == ClassMembership.user_id)
                .where(
                    ClassMembership.teaching_class_id.in_(class_ids),
                    ClassMembership.status == "active",
                    User.role == "student",
                    User.approval_status != "disabled",
                )
            ).all())
        else:
            student_ids = set()

        event_rows = self.db.execute(
            select(LearningEvent.user_id, LearningEvent.created_time).where(
                LearningEvent.user_id.in_(student_ids),
                LearningEvent.event_type.in_(VALID_ACTIVITY_TYPES),
                LearningEvent.created_time >= period_start_utc,
                LearningEvent.created_time < period_end_utc,
            )
        ).all() if student_ids else []
        active_by_day: dict[date, set[int]] = defaultdict(set)
        for event_user_id, event_created_time in event_rows:
            active_by_day[to_business_time(event_created_time).date()].add(event_user_id)
        today = datetime.now(BUSINESS_TIMEZONE).date()
        activity_series = [
            TeacherActivityPoint(
                date=period_start + timedelta(days=index),
                active_students=len(active_by_day.get(period_start + timedelta(days=index), set())),
                total_students=len(student_ids),
                active_rate=round(len(active_by_day.get(period_start + timedelta(days=index), set())) * 100 / len(student_ids), 2)
                if student_ids else 0,
            )
            for index in range((period_end - period_start).days + 1)
        ]

        assignment_query = select(TeacherAssignment).where(TeacherAssignment.status == "published")
        if user.role != "admin":
            if class_ids:
                assignment_query = assignment_query.where(
                    (TeacherAssignment.created_by == user.id) | TeacherAssignment.teaching_class_id.in_(class_ids)
                )
            else:
                assignment_query = assignment_query.where(TeacherAssignment.created_by == user.id)
        assignments = list(self.db.scalars(assignment_query).all())
        now = utc_now()
        ongoing_tasks = sum(item.due_time >= now for item in assignments)
        assignment_ids = [item.id for item in assignments]
        recipient_rows = self.db.execute(
            select(AssignmentRecipient.assignment_id, AssignmentRecipient.progress_value).where(
                AssignmentRecipient.assignment_id.in_(assignment_ids)
            )
        ).all() if assignment_ids else []
        recipients_by_assignment: dict[int, list[float]] = defaultdict(list)
        total_progress = 0.0
        for aid, progress_val in recipient_rows:
            recipients_by_assignment[aid].append(progress_val)
            total_progress += progress_val
        average_completion_rate = round(total_progress / len(recipient_rows), 2) if recipient_rows else 0

        material_course_ids = set(self.db.scalars(select(TeachingClassMaterial.course_id).where(
            TeachingClassMaterial.teaching_class_id.in_(class_ids)
        )).all()) if class_ids else set()
        class_document_ids = set(self.db.scalars(select(DocumentClassScope.document_id).where(
            DocumentClassScope.teaching_class_id.in_(class_ids)
        )).all()) if class_ids else set()
        course_document_ids = set(self.db.scalars(select(DocumentCourseScope.document_id).where(
            DocumentCourseScope.course_id.in_(material_course_ids)
        )).all()) if material_course_ids else set()
        doc_rows = self.db.execute(
            select(
                KnowledgeDocument.id,
                KnowledgeDocument.owner_user_id,
                KnowledgeDocument.course_id,
                KnowledgeDocument.review_status,
                KnowledgeDocument.calibration_status,
            ).where(KnowledgeDocument.is_active.is_(True))
        ).all()
        visible_documents = [row for row in doc_rows if (
            user.role == "admin" or row.owner_user_id == user.id or row.course_id in material_course_ids
            or row.id in class_document_ids or row.id in course_document_ids
        )]
        pending_materials = sum(row.review_status == "pending" or row.calibration_status == "pending" for row in visible_documents)
        available_evidence = sum(row.review_status == "published" for row in visible_documents)

        todos: list[TeacherTodo] = []
        due_soon = sorted((item for item in assignments if now <= item.due_time <= now + timedelta(days=3)), key=lambda item: item.due_time)
        if due_soon:
            todos.append(TeacherTodo(kind="assignment", title="即将截止的教学任务", description=due_soon[0].title, count=len(due_soon), priority="urgent", href="/assignments"))
        if pending_materials:
            todos.append(TeacherTodo(kind="material", title="待审核资料", description="请完成资料审核后再用于教学", count=pending_materials, href="/material-review"))
        pending_calibration = sum(row.calibration_status == "pending" for row in visible_documents)
        if pending_calibration:
            todos.append(TeacherTodo(kind="calibration", title="待确认教材校准", description="教材章节边界等待确认", count=pending_calibration, href="/knowledge"))
        pending_requests = int(self.db.scalar(select(func.count(ClassJoinRequest.id)).where(
            ClassJoinRequest.teaching_class_id.in_(class_ids), ClassJoinRequest.status == "pending",
        )) or 0) if class_ids else 0
        if pending_requests:
            todos.append(TeacherTodo(kind="join_request", title="待处理学生申请", description="有学生申请加入教学班", count=pending_requests, href="/classes"))

        courses: list[TeacherCourseRow] = []
        if class_ids:
            rows = self.db.execute(select(TeachingClass, AcademicTerm).join(
                AcademicTerm, AcademicTerm.id == TeachingClass.term_id,
            ).where(TeachingClass.id.in_(class_ids)).order_by(AcademicTerm.start_date.desc(), TeachingClass.name)).all()
            primary_materials = self.db.execute(
                select(TeachingClassMaterial.teaching_class_id, TeachingClassMaterial.course_id)
                .where(
                    TeachingClassMaterial.teaching_class_id.in_(class_ids),
                    TeachingClassMaterial.material_role == "primary",
                )
                .order_by(TeachingClassMaterial.teaching_class_id, TeachingClassMaterial.sort_order)
            ).all()
            primary_course_by_class: dict[int, int] = {}
            for tc_id, c_id in primary_materials:
                primary_course_by_class.setdefault(tc_id, c_id)
            primary_course_ids = set(primary_course_by_class.values())
            course_name_by_id = dict(
                self.db.execute(select(Course.id, Course.name).where(Course.id.in_(primary_course_ids))).all()
            ) if primary_course_ids else {}
            student_count_by_class = dict(
                self.db.execute(
                    select(ClassMembership.teaching_class_id, func.count(func.distinct(ClassMembership.user_id)))
                    .where(
                        ClassMembership.teaching_class_id.in_(class_ids),
                        ClassMembership.status == "active",
                    )
                    .group_by(ClassMembership.teaching_class_id)
                ).all()
            )
            assignments_by_class: dict[int, list[int]] = defaultdict(list)
            for item in assignments:
                if item.teaching_class_id is not None:
                    assignments_by_class[item.teaching_class_id].append(item.id)
            for teaching_class, term in rows:
                primary_course_id = primary_course_by_class.get(teaching_class.id)
                course_name = course_name_by_id.get(primary_course_id) if primary_course_id else None
                class_progress: list[float] = []
                for aid in assignments_by_class.get(teaching_class.id, []):
                    class_progress.extend(recipients_by_assignment.get(aid, []))
                completion = round(sum(class_progress) / len(class_progress), 2) if class_progress else 0
                courses.append(TeacherCourseRow(
                    teaching_class_id=teaching_class.id, class_name=teaching_class.name, class_code=teaching_class.code,
                    course_id=primary_course_id, course_name=course_name or "未绑定教材",
                    student_count=int(student_count_by_class.get(teaching_class.id, 0)),
                    completion_rate=completion, start_date=term.start_date, end_date=term.end_date, status=teaching_class.status,
                ))

        return TeacherDashboardData(
            period_start=period_start, period_end=period_end,
            metrics=TeacherDashboardMetrics(
                ongoing_tasks=ongoing_tasks, average_completion_rate=average_completion_rate,
                active_students_today=len(active_by_day.get(today, set())),
                active_rate_today=round(len(active_by_day.get(today, set())) * 100 / len(student_ids), 2) if student_ids else 0,
                pending_materials=pending_materials, available_evidence=available_evidence,
            ), activity_series=activity_series, todos=todos[:5], courses=courses,
        )

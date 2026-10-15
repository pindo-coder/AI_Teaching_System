from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.time import BUSINESS_TIMEZONE, to_business_time, to_utc_naive, utc_now
from app.models.chapter import Chapter
from app.models.classroom import ClassroomActivity, ClassroomResponse, DiscussionReply, DiscussionThread
from app.models.course import Course
from app.models.learning_task import LearningEvent, UserTaskProgress
from app.models.teacher_assignment import AssignmentRecipient, AssignmentRequirementProgress, TeacherAssignment
from app.models.user import User
from app.models.teaching_class import ClassGroup, ClassGroupMember, ClassMembership, TeachingClassMaterial, TeachingClassTeacher
from app.schemas.assignment import AssignmentCompletionPolicy, AssignmentCreate
from app.services.task_service import TaskService


def _assignment_time_utc(
    assignment: TeacherAssignment,
    value: datetime | None,
) -> datetime | None:
    if value is None:
        return None
    naive_timezone = UTC if assignment.due_time_is_utc else BUSINESS_TIMEZONE
    return to_utc_naive(value, naive_timezone=naive_timezone)


def _assignment_due_time_utc(assignment: TeacherAssignment) -> datetime:
    value = _assignment_time_utc(assignment, assignment.due_time)
    assert value is not None
    return value


def _assignment_now_for_storage(assignment: TeacherAssignment) -> datetime:
    """Store recipient completion in the same basis as its assignment marker."""
    now = utc_now()
    if assignment.due_time_is_utc:
        return now
    return to_business_time(now).replace(tzinfo=None)


class AssignmentService:
    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def _required_task_types(stage: str, kind: str) -> list[str]:
        if kind == "reading":
            return [f"reading_{stage}"]
        if kind == "ai_assist":
            return [f"ai_{stage}"]
        if kind == "note":
            return ["note_saved"]
        return []

    @staticmethod
    def _policy(assignment: TeacherAssignment) -> AssignmentCompletionPolicy | None:
        raw = assignment.completion_policy or {}
        if not raw:
            return None
        try:
            return AssignmentCompletionPolicy.model_validate(raw)
        except ValueError:
            # Do not break historical lists because of an old or manually edited JSON value.
            return None

    @staticmethod
    def _next_path(assignment: TeacherAssignment, event: str) -> str:
        base = f"/courses/{assignment.course_id}/chapters/{assignment.chapter_id}/{assignment.learning_stage}"
        if event in {"discussion_created", "discussion_reply_created", "activity_submitted"}:
            return "/interaction"
        if event == "note_saved":
            return f"{base}?focus=notes"
        if event == "quiz_completed":
            return f"/courses/{assignment.course_id}/chapters/{assignment.chapter_id}/exam?focus=practice"
        if event == "ai_assist_used":
            return f"{base}?focus=ai"
        return f"{base}?focus=reading"

    def list_students(self, requester: User, teaching_class_id: int | None = None) -> list[dict[str, object]]:
        statement = select(User).where(User.role == "student")
        if teaching_class_id is not None:
            from app.services.teaching_class_service import TeachingClassService
            TeachingClassService(self.db).require_teacher(teaching_class_id, requester)
            statement = statement.join(ClassMembership, ClassMembership.user_id == User.id).where(
                ClassMembership.teaching_class_id == teaching_class_id, ClassMembership.status == "active"
            )
        elif requester.role != "admin":
            class_ids = select(TeachingClassTeacher.teaching_class_id).where(
                TeachingClassTeacher.user_id == requester.id
            )
            statement = statement.join(ClassMembership, ClassMembership.user_id == User.id).where(
                ClassMembership.teaching_class_id.in_(class_ids), ClassMembership.status == "active"
            ).distinct()
        students = self.db.scalars(statement.order_by(User.username)).all()
        return [{"id": item.id, "username": item.username, "identity_no": item.identity_no} for item in students]

    def create(self, teacher_id: int, payload: AssignmentCreate, *, commit: bool = True) -> TeacherAssignment:
        chapter = self.db.get(Chapter, payload.chapter_id)
        if chapter is None or chapter.course_id != payload.course_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="专题与教材不匹配")
        due_time = to_utc_naive(payload.due_time)
        if due_time <= utc_now():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="截止时间必须晚于当前时间")
        if (
            payload.task_kind == "note"
            and payload.learning_stage != "review"
            and payload.completion_policy is None
        ):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="章节笔记任务应关联课后巩固阶段")
        if payload.teaching_class_id is not None:
            teacher = self.db.get(User, teacher_id)
            from app.services.teaching_class_service import TeachingClassService
            TeachingClassService(self.db).require_teacher(payload.teaching_class_id, teacher)
            material = self.db.scalar(select(TeachingClassMaterial.id).where(
                TeachingClassMaterial.teaching_class_id == payload.teaching_class_id,
                TeachingClassMaterial.course_id == payload.course_id,
            ))
            if material is None:
                raise HTTPException(status_code=400, detail="该教材未绑定到当前教学班")
        assignment = TeacherAssignment(
            created_by=teacher_id,
            teaching_class_id=payload.teaching_class_id,
            course_id=payload.course_id,
            chapter_id=payload.chapter_id,
            learning_stage=payload.learning_stage,
            task_kind=(
                "composite"
                if payload.completion_policy is not None and len(payload.completion_policy.items) > 1
                else payload.task_kind
            ),
            title=payload.title.strip(),
            description=payload.description.strip(),
            rubric=payload.rubric,
            due_time=due_time,
            due_time_is_utc=True,
            status="published",
            target_scope=payload.target_scope,
            target_group_ids=payload.group_ids,
            required_task_types=self._required_task_types(payload.learning_stage, payload.task_kind),
            completion_policy=(
                payload.completion_policy.model_dump(mode="json")
                if payload.completion_policy is not None
                else {}
            ),
        )
        self.db.add(assignment)
        self.db.flush()
        if payload.teaching_class_id is not None:
            class_students = select(ClassMembership.user_id).where(
                ClassMembership.teaching_class_id == payload.teaching_class_id,
                ClassMembership.status == "active",
            )
            if payload.target_scope == "all_students":
                student_ids = list(self.db.scalars(class_students).all())
            elif payload.target_scope == "selected_groups":
                student_ids = list(self.db.scalars(select(ClassGroupMember.user_id).where(
                    ClassGroupMember.teaching_class_id == payload.teaching_class_id,
                    ClassGroupMember.group_id.in_(set(payload.group_ids)),
                )).all())
            else:
                student_ids = list(self.db.scalars(select(ClassMembership.user_id).where(
                    ClassMembership.teaching_class_id == payload.teaching_class_id,
                    ClassMembership.status == "active",
                    ClassMembership.user_id.in_(set(payload.student_ids)),
                )).all())
                if len(student_ids) != len(set(payload.student_ids)):
                    raise HTTPException(status_code=400, detail="指定学生必须属于当前教学班")
        elif payload.target_scope == "all_students":
            student_ids = list(self.db.scalars(select(User.id).where(User.role == "student")).all())
        else:
            student_ids = list(self.db.scalars(select(User.id).where(
                User.role == "student", User.id.in_(set(payload.student_ids))
            )).all())
            if len(student_ids) != len(set(payload.student_ids)):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="发布对象中包含无效学生账号")
        self.db.add_all([AssignmentRecipient(assignment_id=assignment.id, user_id=user_id) for user_id in student_ids])
        if commit:
            self.db.commit()
            self.db.refresh(assignment)
        else:
            self.db.flush()
        return assignment

    def _sync_legacy_recipient(self, assignment: TeacherAssignment, recipient: AssignmentRecipient) -> None:
        tasks = TaskService(self.db).ensure_tasks(assignment.course_id, assignment.chapter_id, assignment.learning_stage)
        required = set(assignment.required_task_types or [])
        selected_tasks = [task for task in tasks if not required or task.task_type in required]
        task_ids = [task.id for task in selected_tasks]
        progresses = {item.task_point_id: item for item in self.db.scalars(select(UserTaskProgress).where(
            UserTaskProgress.user_id == recipient.user_id,
            UserTaskProgress.task_point_id.in_(task_ids),
        )).all()} if task_ids else {}
        recipient.progress_value = round(sum(progresses.get(task_id).progress_value if progresses.get(task_id) else 0 for task_id in task_ids) / max(1, len(task_ids)))
        if task_ids and all(progresses.get(task_id) and progresses[task_id].status == "completed" for task_id in task_ids):
            recipient.status = "completed"
            recipient.completed_time = recipient.completed_time or _assignment_now_for_storage(assignment)
        elif recipient.progress_value > 0:
            recipient.status = "in_progress"
        else:
            recipient.status = "not_started"

    def _source_count(self, assignment: TeacherAssignment, user_id: int, event: str) -> int | None:
        context = [
            DiscussionThread.course_id == assignment.course_id,
            DiscussionThread.chapter_id == assignment.chapter_id,
        ]
        if assignment.teaching_class_id is not None:
            context.append(DiscussionThread.teaching_class_id == assignment.teaching_class_id)
        if event == "discussion_created":
            return int(self.db.scalar(select(func.count(DiscussionThread.id)).where(
                DiscussionThread.author_id == user_id,
                DiscussionThread.status.in_(["published", "closed"]),
                *context,
            )) or 0)
        if event == "discussion_reply_created":
            return int(self.db.scalar(
                select(func.count(DiscussionReply.id))
                .join(DiscussionThread, DiscussionThread.id == DiscussionReply.thread_id)
                .where(
                    DiscussionReply.author_id == user_id,
                    DiscussionReply.status == "published",
                    *context,
                )
            ) or 0)
        if event == "activity_submitted":
            activity_context = [
                ClassroomActivity.course_id == assignment.course_id,
                ClassroomActivity.chapter_id == assignment.chapter_id,
            ]
            if assignment.teaching_class_id is not None:
                activity_context.append(ClassroomActivity.teaching_class_id == assignment.teaching_class_id)
            return int(self.db.scalar(
                select(func.count(ClassroomResponse.id))
                .join(ClassroomActivity, ClassroomActivity.id == ClassroomResponse.activity_id)
                .where(ClassroomResponse.user_id == user_id, *activity_context)
            ) or 0)
        return None

    def _requirement_value(
        self,
        assignment: TeacherAssignment,
        user_id: int,
        item,
        learning_events: list[LearningEvent],
    ) -> int:
        source_count = self._source_count(assignment, user_id, item.event)
        if source_count is not None:
            return source_count
        events = [event for event in learning_events if event.event_type == item.event]
        # The teacher-facing policy calls this generic condition “使用 AI 学习辅助”.
        # Older policies persisted the assignment stage and a generated task-type list,
        # even though neither restriction was shown to students. Keep those historical
        # tasks honest by accepting any successful AI use in the same course/chapter.
        generic_ai_assist = item.key == "ai" and item.event == "ai_assist_used"
        if not generic_ai_assist and item.stage != "any":
            stage = assignment.learning_stage if item.stage == "assignment" else item.stage
            events = [event for event in events if event.learning_stage == stage]
        if not generic_ai_assist and item.task_types:
            allowed = set(item.task_types)
            events = [event for event in events if event.event_data.get("task_type") in allowed]
        if item.metric == "percent":
            return round(max((float(event.event_data.get("percent", 0)) for event in events), default=0))
        if item.metric == "length":
            return max((
                int(event.event_data.get("content_length", len(str(event.event_data.get("content", "")))))
                for event in events
            ), default=0)
        return sum(
            int(event.event_data.get("count", 1))
            for event in events
        )

    @staticmethod
    def _evidence_summary(label: str, metric: str, current: int, target: int) -> str:
        if metric == "percent":
            return f"{label}：已达到 {current}% / {target}%"
        if metric == "length":
            return f"{label}：已记录 {current} / {target} 字"
        return f"{label}：已完成 {current} / {target} 次"

    def _sync_policy_recipient(
        self,
        assignment: TeacherAssignment,
        recipient: AssignmentRecipient,
        policy: AssignmentCompletionPolicy,
    ) -> list[dict[str, object]]:
        existing = {
            row.requirement_key: row
            for row in self.db.scalars(select(AssignmentRequirementProgress).where(
                AssignmentRequirementProgress.assignment_id == assignment.id,
                AssignmentRequirementProgress.user_id == recipient.user_id,
            )).all()
        }
        active_keys = {item.key for item in policy.items}
        for key, row in existing.items():
            if key not in active_keys:
                self.db.delete(row)
        results: list[dict[str, object]] = []
        weighted_progress = 0.0
        required_complete = True
        learning_events = list(self.db.scalars(select(LearningEvent).where(
            LearningEvent.user_id == recipient.user_id,
            LearningEvent.course_id == assignment.course_id,
            LearningEvent.chapter_id == assignment.chapter_id,
        ).order_by(LearningEvent.id)).all())
        for item in policy.items:
            current = self._requirement_value(
                assignment,
                recipient.user_id,
                item,
                learning_events,
            )
            progress = min(100, round(current / item.target * 100))
            item_status = "completed" if progress >= 100 else "in_progress" if current > 0 else "not_started"
            row = existing.get(item.key)
            if row is None:
                row = AssignmentRequirementProgress(
                    assignment_id=assignment.id,
                    user_id=recipient.user_id,
                    requirement_key=item.key,
                )
                self.db.add(row)
            row.current_value = current
            row.target_value = item.target
            row.progress_value = progress
            row.status = item_status
            row.evidence_summary = self._evidence_summary(item.label, item.metric, current, item.target)
            if item_status == "completed":
                row.completed_time = row.completed_time or _assignment_now_for_storage(assignment)
            else:
                row.completed_time = None
            weighted_progress += item.weight * progress / 100
            if item.required and item_status != "completed":
                required_complete = False
            results.append({
                "key": item.key,
                "label": item.label,
                "event": item.event,
                "current_value": current,
                "target_value": item.target,
                "progress_value": progress,
                "status": item_status,
                "evidence_summary": row.evidence_summary,
                "next_path": self._next_path(assignment, item.event),
            })
        recipient.progress_value = round(weighted_progress)
        if required_complete:
            recipient.status = "completed"
            recipient.completed_time = recipient.completed_time or _assignment_now_for_storage(assignment)
        elif recipient.progress_value > 0:
            recipient.status = "in_progress"
            recipient.completed_time = None
        else:
            recipient.status = "not_started"
            recipient.completed_time = None
        return results

    def _sync_recipient(self, assignment: TeacherAssignment, recipient: AssignmentRecipient) -> list[dict[str, object]]:
        policy = self._policy(assignment)
        if policy is None:
            self._sync_legacy_recipient(assignment, recipient)
            return []
        return self._sync_policy_recipient(assignment, recipient, policy)

    def _ensure_all_student_recipients(self, user_id: int) -> None:
        assignments = self.db.scalars(select(TeacherAssignment).where(
            TeacherAssignment.status == "published", TeacherAssignment.target_scope == "all_students"
        )).all()
        existing = set(self.db.scalars(select(AssignmentRecipient.assignment_id).where(
            AssignmentRecipient.user_id == user_id
        )).all())
        for assignment in assignments:
            if assignment.id not in existing:
                if assignment.teaching_class_id is not None:
                    active_member = self.db.scalar(select(ClassMembership.id).where(
                        ClassMembership.teaching_class_id == assignment.teaching_class_id,
                        ClassMembership.user_id == user_id, ClassMembership.status == "active",
                    ))
                    if active_member is None:
                        continue
                self.db.add(AssignmentRecipient(assignment_id=assignment.id, user_id=user_id))
        self.db.flush()

    def student_assignments(self, user_id: int, include_completed: bool = True) -> list[dict[str, object]]:
        self._ensure_all_student_recipients(user_id)
        rows = list(self.db.execute(
            select(TeacherAssignment, AssignmentRecipient, Course.name, Chapter.title, User.username)
            .join(AssignmentRecipient, AssignmentRecipient.assignment_id == TeacherAssignment.id)
            .join(Course, Course.id == TeacherAssignment.course_id)
            .join(Chapter, Chapter.id == TeacherAssignment.chapter_id)
            .join(User, User.id == TeacherAssignment.created_by)
            .where(AssignmentRecipient.user_id == user_id, TeacherAssignment.status == "published")
        ).all())
        rows.sort(key=lambda row: (_assignment_due_time_utc(row[0]), -row[0].id))
        output: list[dict[str, object]] = []
        now = utc_now()
        for assignment, recipient, course_name, chapter_title, teacher_name in rows:
            requirements = self._sync_recipient(assignment, recipient)
            due_time = _assignment_due_time_utc(assignment)
            is_overdue = recipient.status != "completed" and due_time < now
            display_status = "overdue" if is_overdue else recipient.status
            if not include_completed and display_status == "completed":
                continue
            next_requirement = next((item for item in requirements if item["status"] != "completed"), None)
            output.append({
                "id": assignment.id, "course_id": assignment.course_id, "chapter_id": assignment.chapter_id,
                "teaching_class_id": assignment.teaching_class_id,
                "course_name": course_name, "chapter_title": chapter_title,
                "learning_stage": assignment.learning_stage, "task_kind": assignment.task_kind,
                "title": assignment.title, "description": assignment.description, "rubric": assignment.rubric or {}, "due_time": due_time,
                "status": display_status, "progress_value": recipient.progress_value,
                "completed_time": _assignment_time_utc(assignment, recipient.completed_time),
                "created_time": assignment.created_time,
                "teacher_name": teacher_name,
                "completion_policy": assignment.completion_policy or None,
                "requirements": requirements,
                "next_path": (
                    str(next_requirement["next_path"])
                    if next_requirement is not None
                    else self._next_path(assignment, "reading_progress")
                ),
                "completion_status": recipient.status,
                "is_overdue": is_overdue,
            })
        self.db.commit()
        return output

    def teacher_assignments(self, teacher_id: int, is_admin: bool = False) -> list[dict[str, object]]:
        statement = (
            select(TeacherAssignment, Course.name, Chapter.title)
            .join(Course, Course.id == TeacherAssignment.course_id)
            .join(Chapter, Chapter.id == TeacherAssignment.chapter_id)
            .order_by(TeacherAssignment.created_time.desc(), TeacherAssignment.id.desc())
        )
        if not is_admin:
            class_ids = select(TeachingClassTeacher.teaching_class_id).where(
                TeachingClassTeacher.user_id == teacher_id
            )
            statement = statement.where(or_(
                TeacherAssignment.created_by == teacher_id,
                TeacherAssignment.teaching_class_id.in_(class_ids),
            ))
        output = []
        now = utc_now()
        for assignment, course_name, chapter_title in self.db.execute(statement).all():
            due_time = _assignment_due_time_utc(assignment)
            recipients = list(self.db.scalars(select(AssignmentRecipient).where(
                AssignmentRecipient.assignment_id == assignment.id
            )).all())
            for recipient in recipients:
                self._sync_recipient(assignment, recipient)
            output.append({
                "id": assignment.id, "course_id": assignment.course_id, "chapter_id": assignment.chapter_id,
                "teaching_class_id": assignment.teaching_class_id,
                "course_name": course_name, "chapter_title": chapter_title,
                "learning_stage": assignment.learning_stage, "task_kind": assignment.task_kind,
                "title": assignment.title, "description": assignment.description, "rubric": assignment.rubric or {}, "due_time": due_time,
                "status": assignment.status, "target_scope": assignment.target_scope, "created_time": assignment.created_time,
                "total_count": len(recipients),
                "completed_count": sum(item.status == "completed" for item in recipients),
                "in_progress_count": sum(item.status == "in_progress" for item in recipients),
                "overdue_count": sum(item.status != "completed" and due_time < now for item in recipients),
                "completion_policy": assignment.completion_policy or None,
            })
        self.db.commit()
        return output

    def recipient_details(self, assignment_id: int, requester: User) -> list[dict[str, object]]:
        assignment = self.db.get(TeacherAssignment, assignment_id)
        if assignment is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
        if requester.role != "admin" and assignment.created_by != requester.id:
            relation = self.db.scalar(select(TeachingClassTeacher.id).where(
                TeachingClassTeacher.teaching_class_id == assignment.teaching_class_id,
                TeachingClassTeacher.user_id == requester.id,
            )) if assignment.teaching_class_id else None
            if relation is None:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权查看该任务的学生完成详情")

        group_join = and_(
            ClassGroupMember.user_id == User.id,
            ClassGroupMember.teaching_class_id == assignment.teaching_class_id,
        )
        rows = self.db.execute(
            select(AssignmentRecipient, User, ClassGroup.name)
            .join(User, User.id == AssignmentRecipient.user_id)
            .outerjoin(ClassGroupMember, group_join)
            .outerjoin(ClassGroup, ClassGroup.id == ClassGroupMember.group_id)
            .where(AssignmentRecipient.assignment_id == assignment.id)
            .order_by(User.username, User.id)
        ).all()
        now = utc_now()
        due_time = _assignment_due_time_utc(assignment)
        output: list[dict[str, object]] = []
        status_order = {"overdue": 0, "not_started": 1, "in_progress": 2, "completed": 3}
        for recipient, student, group_name in rows:
            requirements = self._sync_recipient(assignment, recipient)
            is_overdue = recipient.status != "completed" and due_time < now
            display_status = "overdue" if is_overdue else recipient.status
            last_activity_time = self.db.scalar(
                select(func.max(LearningEvent.created_time)).where(
                    LearningEvent.user_id == recipient.user_id,
                    LearningEvent.course_id == assignment.course_id,
                    LearningEvent.chapter_id == assignment.chapter_id,
                    LearningEvent.learning_stage == assignment.learning_stage,
                )
            )
            output.append({
                "user_id": student.id,
                "username": student.username,
                "identity_no": student.identity_no,
                "group_name": group_name,
                "status": display_status,
                "progress_value": recipient.progress_value,
                "completed_time": _assignment_time_utc(assignment, recipient.completed_time),
                "last_activity_time": last_activity_time,
                "completion_status": recipient.status,
                "is_overdue": is_overdue,
                "requirements": requirements,
            })
        self.db.commit()
        return sorted(
            output,
            key=lambda item: (
                status_order.get(str(item["status"]), 9),
                str(item["identity_no"] or item["username"]),
            ),
        )

    def cancel(self, assignment_id: int, teacher_id: int, is_admin: bool = False) -> TeacherAssignment:
        assignment = self.db.get(TeacherAssignment, assignment_id)
        if assignment is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
        if not is_admin and assignment.created_by != teacher_id:
            relation = self.db.scalar(select(TeachingClassTeacher.id).where(
                TeachingClassTeacher.teaching_class_id == assignment.teaching_class_id,
                TeachingClassTeacher.user_id == teacher_id,
            )) if assignment.teaching_class_id else None
            if relation is None:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权撤回该教学班任务")
        assignment.status = "cancelled"
        self.db.commit()
        self.db.refresh(assignment)
        return assignment

    def confirm_rubric(self, assignment_id: int, requester: User, rubric: dict) -> TeacherAssignment:
        assignment = self.db.get(TeacherAssignment, assignment_id)
        if assignment is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
        if requester.role != "admin" and assignment.created_by != requester.id:
            relation = self.db.scalar(select(TeachingClassTeacher.id).where(
                TeachingClassTeacher.teaching_class_id == assignment.teaching_class_id,
                TeachingClassTeacher.user_id == requester.id,
            )) if assignment.teaching_class_id else None
            if relation is None:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权确认该任务量规")
        items = rubric.get("items") if isinstance(rubric, dict) else None
        if not isinstance(items, list) or not items:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="量规至少需要一个评分维度")
        total = sum(float(item.get("weight", 0)) for item in items if isinstance(item, dict))
        if abs(total - 100) > 0.01:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="量规权重总和必须为 100%")
        assignment.rubric = rubric
        self.db.commit()
        self.db.refresh(assignment)
        return assignment

    def update_completion_policy(
        self,
        assignment_id: int,
        requester: User,
        policy: AssignmentCompletionPolicy,
    ) -> TeacherAssignment:
        assignment = self.db.get(TeacherAssignment, assignment_id)
        if assignment is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
        if requester.role != "admin" and assignment.created_by != requester.id:
            relation = self.db.scalar(select(TeachingClassTeacher.id).where(
                TeachingClassTeacher.teaching_class_id == assignment.teaching_class_id,
                TeachingClassTeacher.user_id == requester.id,
            )) if assignment.teaching_class_id else None
            if relation is None:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权调整该任务完成条件")
        assignment.completion_policy = policy.model_dump(mode="json")
        assignment.task_kind = "composite" if len(policy.items) > 1 else {
            "reading_progress": "reading",
            "ai_assist_used": "ai_assist",
            "note_saved": "note",
        }.get(policy.items[0].event, "composite")
        assignment.required_task_types = []
        recipients = list(self.db.scalars(select(AssignmentRecipient).where(
            AssignmentRecipient.assignment_id == assignment.id
        )).all())
        for recipient in recipients:
            self._sync_policy_recipient(assignment, recipient, policy)
        self.db.commit()
        self.db.refresh(assignment)
        return assignment

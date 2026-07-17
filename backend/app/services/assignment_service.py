from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.chapter import Chapter
from app.models.course import Course
from app.models.learning_task import UserTaskProgress
from app.models.teacher_assignment import AssignmentRecipient, TeacherAssignment
from app.models.user import User
from app.models.teaching_class import ClassGroupMember, ClassMembership, TeachingClassMaterial, TeachingClassTeacher
from app.schemas.assignment import AssignmentCreate
from app.services.task_service import TaskService


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

    def create(self, teacher_id: int, payload: AssignmentCreate) -> TeacherAssignment:
        chapter = self.db.get(Chapter, payload.chapter_id)
        if chapter is None or chapter.course_id != payload.course_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="专题与教材不匹配")
        due_time = payload.due_time.replace(tzinfo=None)
        if due_time <= datetime.now():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="截止时间必须晚于当前时间")
        if payload.task_kind == "note" and payload.learning_stage != "review":
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
            task_kind=payload.task_kind,
            title=payload.title.strip(),
            description=payload.description.strip(),
            due_time=due_time,
            status="published",
            target_scope=payload.target_scope,
            target_group_ids=payload.group_ids,
            required_task_types=self._required_task_types(payload.learning_stage, payload.task_kind),
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
        self.db.commit()
        self.db.refresh(assignment)
        return assignment

    def _sync_recipient(self, assignment: TeacherAssignment, recipient: AssignmentRecipient) -> None:
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
            recipient.completed_time = recipient.completed_time or datetime.now()
        elif recipient.progress_value > 0:
            recipient.status = "in_progress"
        else:
            recipient.status = "not_started"

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
        rows = self.db.execute(
            select(TeacherAssignment, AssignmentRecipient, Course.name, Chapter.title, User.username)
            .join(AssignmentRecipient, AssignmentRecipient.assignment_id == TeacherAssignment.id)
            .join(Course, Course.id == TeacherAssignment.course_id)
            .join(Chapter, Chapter.id == TeacherAssignment.chapter_id)
            .join(User, User.id == TeacherAssignment.created_by)
            .where(AssignmentRecipient.user_id == user_id, TeacherAssignment.status == "published")
            .order_by(TeacherAssignment.due_time, TeacherAssignment.id.desc())
        ).all()
        output: list[dict[str, object]] = []
        now = datetime.now()
        for assignment, recipient, course_name, chapter_title, teacher_name in rows:
            self._sync_recipient(assignment, recipient)
            display_status = "overdue" if recipient.status != "completed" and assignment.due_time < now else recipient.status
            if not include_completed and display_status == "completed":
                continue
            output.append({
                "id": assignment.id, "course_id": assignment.course_id, "chapter_id": assignment.chapter_id,
                "teaching_class_id": assignment.teaching_class_id,
                "course_name": course_name, "chapter_title": chapter_title,
                "learning_stage": assignment.learning_stage, "task_kind": assignment.task_kind,
                "title": assignment.title, "description": assignment.description, "due_time": assignment.due_time,
                "status": display_status, "progress_value": recipient.progress_value,
                "completed_time": recipient.completed_time, "created_time": assignment.created_time,
                "teacher_name": teacher_name,
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
        now = datetime.now()
        for assignment, course_name, chapter_title in self.db.execute(statement).all():
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
                "title": assignment.title, "description": assignment.description, "due_time": assignment.due_time,
                "status": assignment.status, "target_scope": assignment.target_scope, "created_time": assignment.created_time,
                "total_count": len(recipients),
                "completed_count": sum(item.status == "completed" for item in recipients),
                "in_progress_count": sum(item.status == "in_progress" for item in recipients),
                "overdue_count": sum(item.status != "completed" and assignment.due_time < now for item in recipients),
            })
        self.db.commit()
        return output

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

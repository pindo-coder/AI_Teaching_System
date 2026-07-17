"""把升级前的全站测试数据归入默认试点班；脚本可重复执行。"""
from datetime import date

from sqlalchemy import select

import app.db.models  # noqa: F401  # 注册全部 ORM 模型，确保字符串关系可被解析
from app.db.session import SessionLocal
from app.models.classroom import ClassroomActivity
from app.models.course import Course
from app.models.teacher_assignment import TeacherAssignment
from app.models.teaching_class import (
    AcademicTerm, ClassMembership, ClassRosterEntry, CourseSubject, StudentCourseSeat, TeachingClass,
    TeachingClassMaterial, TeachingClassTeacher,
)
from app.models.user import User
from app.services.teaching_class_service import TeachingClassService


def bootstrap() -> None:
    with SessionLocal() as db:
        existing = db.scalar(select(TeachingClass).where(TeachingClass.is_default.is_(True)))
        if existing:
            print(f"默认试点班已存在：{existing.id}")
            return
        today = date.today()
        term = db.scalar(select(AcademicTerm).where(AcademicTerm.is_current.is_(True)))
        if term is None:
            term = AcademicTerm(name=f"{today.year}年度试点学期", start_date=date(today.year, 1, 1),
                                end_date=date(today.year, 12, 31), is_current=True)
            db.add(term); db.flush()
        subject = db.scalar(select(CourseSubject).order_by(CourseSubject.id))
        if subject is None:
            subject = CourseSubject(name="习近平新时代中国特色社会主义思想概论", code="XG")
            db.add(subject); db.flush()
        owner = db.scalar(select(User).where(User.role == "admin").order_by(User.id))
        if owner is None:
            raise RuntimeError("请先创建管理员账号，再执行默认试点班迁移")
        item = TeachingClass(subject_id=subject.id, term_id=term.id, name="默认试点班", code="PILOT",
                             owner_id=owner.id, status="active", join_code=TeachingClassService.new_join_code(),
                             is_default=True, description="由升级脚本迁移的既有测试数据")
        db.add(item); db.flush()
        db.add(TeachingClassTeacher(teaching_class_id=item.id, user_id=owner.id, teacher_role="primary"))
        for teacher in db.scalars(select(User).where(User.role == "teacher")).all():
            teacher.approval_status = "approved"
            db.add(TeachingClassTeacher(teaching_class_id=item.id, user_id=teacher.id, teacher_role="collaborator"))
        for index, course in enumerate(db.scalars(select(Course).order_by(Course.id)).all()):
            db.add(TeachingClassMaterial(teaching_class_id=item.id, course_id=course.id,
                                         material_role="primary" if index == 0 else "supplementary", sort_order=index))
        for student in db.scalars(select(User).where(User.role == "student")).all():
            db.add(ClassMembership(teaching_class_id=item.id, user_id=student.id, status="active", join_method="migration"))
            db.add(ClassRosterEntry(teaching_class_id=item.id, identity_no=(student.identity_no or f"LEGACY-{student.id}").upper(),
                                    student_name=student.username, bound_user_id=student.id))
            db.add(StudentCourseSeat(user_id=student.id, subject_id=subject.id, term_id=term.id,
                                     teaching_class_id=item.id))
        for assignment in db.scalars(select(TeacherAssignment).where(TeacherAssignment.teaching_class_id.is_(None))).all():
            assignment.teaching_class_id = item.id
        for activity in db.scalars(select(ClassroomActivity).where(ClassroomActivity.teaching_class_id.is_(None))).all():
            activity.teaching_class_id = item.id
        db.commit()
        print(f"默认试点班迁移完成：class_id={item.id} join_code={item.join_code}")


if __name__ == "__main__":
    bootstrap()

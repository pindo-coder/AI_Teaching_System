from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CourseSubject(Base):
    __tablename__ = "course_subjects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True, index=True, nullable=False)
    code: Mapped[str | None] = mapped_column(String(50), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    created_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class AcademicTerm(Base):
    __tablename__ = "academic_terms"
    __table_args__ = (UniqueConstraint("name", "start_date", name="uq_academic_term_name_start"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    created_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class TeachingClass(Base):
    __tablename__ = "teaching_classes"
    __table_args__ = (UniqueConstraint("term_id", "code", name="uq_teaching_class_term_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("course_subjects.id", ondelete="RESTRICT"), index=True)
    term_id: Mapped[int] = mapped_column(ForeignKey("academic_terms.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="not_started", nullable=False, index=True)
    join_code: Mapped[str] = mapped_column(String(16), unique=True, index=True, nullable=False)
    join_code_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    created_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class TeachingClassTeacher(Base):
    __tablename__ = "teaching_class_teachers"
    __table_args__ = (UniqueConstraint("teaching_class_id", "user_id", name="uq_class_teacher"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    teaching_class_id: Mapped[int] = mapped_column(ForeignKey("teaching_classes.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    teacher_role: Mapped[str] = mapped_column(String(20), default="collaborator", nullable=False)
    created_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class TeachingClassMaterial(Base):
    __tablename__ = "teaching_class_materials"
    __table_args__ = (UniqueConstraint("teaching_class_id", "course_id", name="uq_class_material"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    teaching_class_id: Mapped[int] = mapped_column(ForeignKey("teaching_classes.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    material_role: Mapped[str] = mapped_column(String(20), default="supplementary", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class ClassRosterEntry(Base):
    __tablename__ = "class_roster_entries"
    __table_args__ = (UniqueConstraint("teaching_class_id", "identity_no", name="uq_class_roster_identity"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    teaching_class_id: Mapped[int] = mapped_column(ForeignKey("teaching_classes.id", ondelete="CASCADE"), index=True)
    identity_no: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    student_name: Mapped[str] = mapped_column(String(100), nullable=False)
    group_name: Mapped[str | None] = mapped_column(String(100))
    bound_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class ClassMembership(Base):
    __tablename__ = "class_memberships"
    __table_args__ = (UniqueConstraint("teaching_class_id", "user_id", name="uq_class_membership"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    teaching_class_id: Mapped[int] = mapped_column(ForeignKey("teaching_classes.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False, index=True)
    join_method: Mapped[str] = mapped_column(String(20), default="code", nullable=False)
    joined_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    left_time: Mapped[datetime | None] = mapped_column(DateTime)


class StudentCourseSeat(Base):
    """数据库层保证学生在同一课程、同一学期只有一个当前教学班。"""

    __tablename__ = "student_course_seats"
    __table_args__ = (UniqueConstraint("user_id", "subject_id", "term_id", name="uq_student_subject_term"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("course_subjects.id", ondelete="CASCADE"), index=True)
    term_id: Mapped[int] = mapped_column(ForeignKey("academic_terms.id", ondelete="CASCADE"), index=True)
    teaching_class_id: Mapped[int] = mapped_column(ForeignKey("teaching_classes.id", ondelete="CASCADE"), index=True)
    updated_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class ClassGroup(Base):
    __tablename__ = "class_groups"
    __table_args__ = (UniqueConstraint("teaching_class_id", "name", name="uq_class_group_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    teaching_class_id: Mapped[int] = mapped_column(ForeignKey("teaching_classes.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class ClassGroupMember(Base):
    __tablename__ = "class_group_members"
    __table_args__ = (
        UniqueConstraint("teaching_class_id", "user_id", name="uq_student_single_group_per_class"),
        UniqueConstraint("group_id", "user_id", name="uq_group_member"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    teaching_class_id: Mapped[int] = mapped_column(ForeignKey("teaching_classes.id", ondelete="CASCADE"), index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("class_groups.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)


class ClassJoinRequest(Base):
    __tablename__ = "class_join_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    teaching_class_id: Mapped[int] = mapped_column(ForeignKey("teaching_classes.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    request_type: Mapped[str] = mapped_column(String(20), default="join", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(String(500))
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    reviewed_time: Mapped[datetime | None] = mapped_column(DateTime)
    created_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class ClassTransferLog(Base):
    __tablename__ = "class_transfer_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("course_subjects.id", ondelete="CASCADE"), index=True)
    term_id: Mapped[int] = mapped_column(ForeignKey("academic_terms.id", ondelete="CASCADE"), index=True)
    from_class_id: Mapped[int | None] = mapped_column(ForeignKey("teaching_classes.id", ondelete="SET NULL"), index=True)
    to_class_id: Mapped[int] = mapped_column(ForeignKey("teaching_classes.id", ondelete="CASCADE"), index=True)
    transfer_type: Mapped[str] = mapped_column(String(30), nullable=False)
    created_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

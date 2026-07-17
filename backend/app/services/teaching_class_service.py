from datetime import datetime
import secrets
import string
import random

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.course import Course
from app.models.teaching_class import (
    AcademicTerm, ClassGroup, ClassGroupMember, ClassJoinRequest, ClassMembership,
    ClassRosterEntry, ClassTransferLog, CourseSubject, StudentCourseSeat, TeachingClass,
    TeachingClassMaterial, TeachingClassTeacher,
)
from app.models.user import User
from app.schemas.teaching_class import TeachingClassCreate


class TeachingClassService:
    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def new_join_code() -> str:
        alphabet = string.ascii_uppercase + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(8))

    def require_class(self, class_id: int) -> TeachingClass:
        item = self.db.get(TeachingClass, class_id)
        if item is None:
            raise HTTPException(status_code=404, detail="教学班不存在")
        return item

    def teacher_role(self, class_id: int, user: User) -> str | None:
        if user.role == "admin":
            return "admin"
        item = self.db.scalar(select(TeachingClassTeacher).where(
            TeachingClassTeacher.teaching_class_id == class_id,
            TeachingClassTeacher.user_id == user.id,
        ))
        return item.teacher_role if item else None

    def require_teacher(self, class_id: int, user: User, *, owner_only: bool = False) -> TeachingClass:
        item = self.require_class(class_id)
        role = self.teacher_role(class_id, user)
        allowed = {"admin", "primary"} if owner_only else {"admin", "primary", "collaborator"}
        if role not in allowed:
            raise HTTPException(status_code=403, detail="无权管理该教学班")
        return item

    def create(self, user: User, payload: TeachingClassCreate) -> TeachingClass:
        if user.role == "teacher" and user.approval_status != "approved":
            raise HTTPException(status_code=403, detail="教师账号尚未通过审核")
        if self.db.get(CourseSubject, payload.subject_id) is None or self.db.get(AcademicTerm, payload.term_id) is None:
            raise HTTPException(status_code=400, detail="课程科目或学期不存在")
        course_ids = [payload.primary_course_id, *payload.supplementary_course_ids]
        courses = self.db.scalars(select(Course.id).where(Course.id.in_(set(course_ids)))).all()
        if len(set(courses)) != len(set(course_ids)):
            raise HTTPException(status_code=400, detail="包含不存在的教材")
        item = TeachingClass(
            subject_id=payload.subject_id, term_id=payload.term_id, name=payload.name.strip(),
            code=payload.code.strip().upper(), owner_id=user.id, status="not_started",
            join_code=self.new_join_code(), description=payload.description.strip() if payload.description else None,
        )
        self.db.add(item)
        try:
            self.db.flush()
            self.db.add(TeachingClassTeacher(teaching_class_id=item.id, user_id=user.id, teacher_role="primary"))
            self.db.add(TeachingClassMaterial(teaching_class_id=item.id, course_id=payload.primary_course_id,
                                              material_role="primary", sort_order=0))
            for index, course_id in enumerate(dict.fromkeys(payload.supplementary_course_ids), start=1):
                if course_id != payload.primary_course_id:
                    self.db.add(TeachingClassMaterial(teaching_class_id=item.id, course_id=course_id,
                                                      material_role="supplementary", sort_order=index))
            self.db.commit(); self.db.refresh(item)
            return item
        except IntegrityError:
            self.db.rollback()
            raise HTTPException(status_code=409, detail="同一学期内教学班编号已存在") from None

    def list_for_user(self, user: User) -> list[dict[str, object]]:
        query = select(TeachingClass, CourseSubject.name, AcademicTerm.name)
        if user.role == "student":
            query = query.join(ClassMembership, ClassMembership.teaching_class_id == TeachingClass.id).where(
                ClassMembership.user_id == user.id
            )
        elif user.role == "teacher":
            query = query.join(TeachingClassTeacher, TeachingClassTeacher.teaching_class_id == TeachingClass.id).where(
                TeachingClassTeacher.user_id == user.id
            )
        query = query.join(CourseSubject, CourseSubject.id == TeachingClass.subject_id).join(
            AcademicTerm, AcademicTerm.id == TeachingClass.term_id
        ).order_by(AcademicTerm.start_date.desc(), TeachingClass.name)
        output: list[dict[str, object]] = []
        for item, subject_name, term_name in self.db.execute(query).all():
            materials = list(self.db.scalars(select(TeachingClassMaterial).where(
                TeachingClassMaterial.teaching_class_id == item.id
            ).order_by(TeachingClassMaterial.sort_order)).all())
            membership = self.db.scalar(select(ClassMembership).where(
                ClassMembership.teaching_class_id == item.id, ClassMembership.user_id == user.id
            )) if user.role == "student" else None
            output.append({
                "id": item.id, "subject_id": item.subject_id, "subject_name": subject_name,
                "term_id": item.term_id, "term_name": term_name, "name": item.name, "code": item.code,
                "status": item.status, "join_code": item.join_code, "join_code_enabled": item.join_code_enabled,
                "description": item.description, "is_default": item.is_default,
                "teacher_role": self.teacher_role(item.id, user),
                "membership_status": membership.status if membership else None,
                "primary_course_id": next((m.course_id for m in materials if m.material_role == "primary"), None),
                "material_ids": [m.course_id for m in materials],
                "student_count": self.db.scalar(select(func.count()).select_from(ClassMembership).where(
                    ClassMembership.teaching_class_id == item.id, ClassMembership.status == "active"
                )) or 0,
            })
        return output

    def _activate_membership(self, user: User, item: TeachingClass, join_method: str,
                             previous_class_id: int | None = None) -> str:
        existing = self.db.scalar(select(ClassMembership).where(
            ClassMembership.teaching_class_id == item.id, ClassMembership.user_id == user.id
        ))
        if existing:
            existing.status = "active"; existing.left_time = None; existing.join_method = join_method
        else:
            self.db.add(ClassMembership(teaching_class_id=item.id, user_id=user.id, status="active",
                                        join_method=join_method))
        seat = self.db.scalar(select(StudentCourseSeat).where(
            StudentCourseSeat.user_id == user.id, StudentCourseSeat.subject_id == item.subject_id,
            StudentCourseSeat.term_id == item.term_id
        ))
        result = "joined"
        if seat:
            previous_class_id = previous_class_id or seat.teaching_class_id
            seat.teaching_class_id = item.id
            result = "transferred"
        else:
            self.db.add(StudentCourseSeat(user_id=user.id, subject_id=item.subject_id, term_id=item.term_id,
                                          teaching_class_id=item.id))
        if previous_class_id and previous_class_id != item.id:
            old = self.db.scalar(select(ClassMembership).where(
                ClassMembership.teaching_class_id == previous_class_id, ClassMembership.user_id == user.id
            ))
            if old:
                old.status = "transferred"; old.left_time = datetime.now()
            self.db.add(ClassTransferLog(user_id=user.id, subject_id=item.subject_id, term_id=item.term_id,
                                         from_class_id=previous_class_id, to_class_id=item.id,
                                         transfer_type="default_to_formal" if self.require_class(previous_class_id).is_default else "approved"))
        self.db.flush()
        return result

    def join(self, user: User, join_code: str) -> dict[str, object]:
        if user.role != "student":
            raise HTTPException(status_code=403, detail="只有学生可以加入教学班")
        item = self.db.scalar(select(TeachingClass).where(
            TeachingClass.join_code == join_code.strip().upper(), TeachingClass.join_code_enabled.is_(True)
        ))
        if item is None or item.status == "archived":
            raise HTTPException(status_code=404, detail="班级码无效或教学班已归档")
        membership = self.db.scalar(select(ClassMembership).where(
            ClassMembership.teaching_class_id == item.id, ClassMembership.user_id == user.id
        ))
        if membership and membership.status == "active":
            return {"status": "already_joined", "teaching_class_id": item.id, "message": "你已在该教学班中"}
        roster = self.db.scalar(select(ClassRosterEntry).where(
            ClassRosterEntry.teaching_class_id == item.id, ClassRosterEntry.identity_no == user.identity_no
        ))
        seat = self.db.scalar(select(StudentCourseSeat).where(
            StudentCourseSeat.user_id == user.id, StudentCourseSeat.subject_id == item.subject_id,
            StudentCourseSeat.term_id == item.term_id
        ))
        if seat and seat.teaching_class_id != item.id:
            old_class = self.require_class(seat.teaching_class_id)
            if old_class.is_default:
                result = self._activate_membership(user, item, "roster" if roster else "code", old_class.id)
                self.db.commit()
                return {"status": result, "teaching_class_id": item.id, "message": "已从默认试点班转入新教学班"}
        if membership and membership.status == "left" and membership.join_method in {"code", "migration"} and seat is None:
            result = self._activate_membership(user, item, membership.join_method)
            self.db.commit()
            return {"status": result, "teaching_class_id": item.id, "message": "已恢复原教学班成员身份"}
        if roster and seat is None:
            roster.bound_user_id = user.id
            result = self._activate_membership(user, item, "roster")
            self.db.commit()
            return {"status": result, "teaching_class_id": item.id, "message": "学号匹配成功，已加入教学班"}
        pending = self.db.scalar(select(ClassJoinRequest).where(
            ClassJoinRequest.teaching_class_id == item.id, ClassJoinRequest.user_id == user.id,
            ClassJoinRequest.status == "pending"
        ))
        if pending is None:
            self.db.add(ClassJoinRequest(teaching_class_id=item.id, user_id=user.id,
                                         request_type="transfer" if seat else "join", status="pending"))
        if membership is None:
            self.db.add(ClassMembership(teaching_class_id=item.id, user_id=user.id, status="pending",
                                        join_method="requested"))
        elif membership.status != "active":
            membership.status = "pending"; membership.left_time = None
        self.db.commit()
        return {"status": "pending", "teaching_class_id": item.id, "message": "申请已提交，等待主讲教师审核"}

    def leave(self, user: User, class_id: int) -> dict[str, object]:
        item = self.require_class(class_id)
        membership = self.db.scalar(select(ClassMembership).where(
            ClassMembership.teaching_class_id == class_id, ClassMembership.user_id == user.id,
            ClassMembership.status == "active"
        ))
        if membership is None:
            raise HTTPException(status_code=404, detail="你不在该教学班中")
        if membership.join_method == "roster" and not item.is_default:
            request = self.db.scalar(select(ClassJoinRequest).where(
                ClassJoinRequest.teaching_class_id == class_id, ClassJoinRequest.user_id == user.id,
                ClassJoinRequest.request_type == "leave", ClassJoinRequest.status == "pending"
            ))
            if request is None:
                self.db.add(ClassJoinRequest(teaching_class_id=class_id, user_id=user.id,
                                             request_type="leave", status="pending")); self.db.commit()
            return {"status": "pending", "message": "退出申请已提交，等待教师审核"}
        membership.status = "left"; membership.left_time = datetime.now()
        seat = self.db.scalar(select(StudentCourseSeat).where(
            StudentCourseSeat.user_id == user.id, StudentCourseSeat.teaching_class_id == class_id
        ))
        if seat: self.db.delete(seat)
        self.db.commit()
        return {"status": "left", "message": "已退出教学班，历史学习数据仍被保留"}

    def review_request(self, reviewer: User, request_id: int, approved: bool) -> ClassJoinRequest:
        request = self.db.get(ClassJoinRequest, request_id)
        if request is None or request.status != "pending":
            raise HTTPException(status_code=404, detail="待审核申请不存在")
        self.require_teacher(request.teaching_class_id, reviewer, owner_only=True)
        user = self.db.get(User, request.user_id); item = self.require_class(request.teaching_class_id)
        if approved and request.request_type in {"join", "transfer"}:
            seat = self.db.scalar(select(StudentCourseSeat).where(
                StudentCourseSeat.user_id == user.id, StudentCourseSeat.subject_id == item.subject_id,
                StudentCourseSeat.term_id == item.term_id
            ))
            self._activate_membership(user, item, "approved", seat.teaching_class_id if seat else None)
        elif approved and request.request_type == "leave":
            membership = self.db.scalar(select(ClassMembership).where(
                ClassMembership.teaching_class_id == item.id, ClassMembership.user_id == user.id
            ))
            if membership: membership.status = "left"; membership.left_time = datetime.now()
            seat = self.db.scalar(select(StudentCourseSeat).where(
                StudentCourseSeat.user_id == user.id, StudentCourseSeat.teaching_class_id == item.id
            ))
            if seat: self.db.delete(seat)
        elif not approved and request.request_type in {"join", "transfer"}:
            pending_membership = self.db.scalar(select(ClassMembership).where(
                ClassMembership.teaching_class_id == item.id, ClassMembership.user_id == user.id,
                ClassMembership.status == "pending",
            ))
            if pending_membership:
                self.db.delete(pending_membership)
        request.status = "approved" if approved else "rejected"
        request.reviewed_by = reviewer.id; request.reviewed_time = datetime.now()
        self.db.commit(); self.db.refresh(request)
        return request

    def add_roster(self, class_id: int, reviewer: User, rows: list[dict[str, str]]) -> dict[str, int]:
        item = self.require_teacher(class_id, reviewer, owner_only=True)
        created = updated = bound = conflicted = 0
        for row in rows:
            identity = row.get("identity_no", "").strip().upper()
            name = row.get("student_name", "").strip()
            if not identity or not name:
                continue
            record = self.db.scalar(select(ClassRosterEntry).where(
                ClassRosterEntry.teaching_class_id == class_id, ClassRosterEntry.identity_no == identity
            ))
            if record:
                record.student_name = name; record.group_name = row.get("group_name") or None; updated += 1
            else:
                record = ClassRosterEntry(teaching_class_id=class_id, identity_no=identity, student_name=name,
                                          group_name=row.get("group_name") or None)
                self.db.add(record); created += 1
            user = self.db.scalar(select(User).where(User.role == "student", User.identity_no == identity))
            if user:
                activated = False
                seat = self.db.scalar(select(StudentCourseSeat).where(
                    StudentCourseSeat.user_id == user.id, StudentCourseSeat.subject_id == item.subject_id,
                    StudentCourseSeat.term_id == item.term_id
                ))
                if seat and seat.teaching_class_id != class_id:
                    old_class = self.require_class(seat.teaching_class_id)
                    if old_class.is_default:
                        record.bound_user_id = user.id
                        self._activate_membership(user, item, "roster", old_class.id); bound += 1; activated = True
                    else:
                        conflicted += 1
                else:
                    record.bound_user_id = user.id
                    self._activate_membership(user, item, "roster"); bound += 1; activated = True
                if activated:
                    group_name = (row.get("group_name") or "").strip()
                    if group_name:
                        group = self.db.scalar(select(ClassGroup).where(
                            ClassGroup.teaching_class_id == class_id, ClassGroup.name == group_name
                        ))
                        if group is None:
                            group = ClassGroup(teaching_class_id=class_id, name=group_name)
                            self.db.add(group); self.db.flush()
                        self.db.execute(delete(ClassGroupMember).where(
                            ClassGroupMember.teaching_class_id == class_id, ClassGroupMember.user_id == user.id
                        ))
                        self.db.add(ClassGroupMember(teaching_class_id=class_id, group_id=group.id, user_id=user.id))
        self.db.commit()
        return {"total": len(rows), "created": created, "updated": updated,
                "bound": bound, "conflicted": conflicted}

    def create_group(self, class_id: int, user: User, name: str, user_ids: list[int]) -> ClassGroup:
        self.require_teacher(class_id, user, owner_only=True)
        group = ClassGroup(teaching_class_id=class_id, name=name.strip())
        self.db.add(group); self.db.flush()
        for user_id in set(user_ids):
            membership = self.db.scalar(select(ClassMembership.id).where(
                ClassMembership.teaching_class_id == class_id, ClassMembership.user_id == user_id,
                ClassMembership.status == "active"
            ))
            if not membership:
                raise HTTPException(status_code=400, detail="分组成员必须是当前班级学生")
            self.db.execute(delete(ClassGroupMember).where(
                ClassGroupMember.teaching_class_id == class_id, ClassGroupMember.user_id == user_id
            ))
            self.db.add(ClassGroupMember(teaching_class_id=class_id, group_id=group.id, user_id=user_id))
        self.db.commit(); self.db.refresh(group)
        return group

    def list_groups(self, class_id: int, user: User) -> list[dict[str, object]]:
        self.require_teacher(class_id, user)
        groups = self.db.scalars(select(ClassGroup).where(
            ClassGroup.teaching_class_id == class_id
        ).order_by(ClassGroup.sort_order, ClassGroup.id)).all()
        return [{"id": group.id, "name": group.name, "sort_order": group.sort_order,
                 "user_ids": list(self.db.scalars(select(ClassGroupMember.user_id).where(
                     ClassGroupMember.group_id == group.id)).all())} for group in groups]

    def random_groups(self, class_id: int, user: User, count: int, prefix: str) -> list[dict[str, object]]:
        self.require_teacher(class_id, user, owner_only=True)
        student_ids = list(self.db.scalars(select(ClassMembership.user_id).where(
            ClassMembership.teaching_class_id == class_id, ClassMembership.status == "active"
        )).all())
        if len(student_ids) < count:
            raise HTTPException(status_code=400, detail="分组数不能超过当前学生人数")
        random.SystemRandom().shuffle(student_ids)
        group_ids = list(self.db.scalars(select(ClassGroup.id).where(ClassGroup.teaching_class_id == class_id)).all())
        if group_ids:
            self.db.execute(delete(ClassGroupMember).where(ClassGroupMember.teaching_class_id == class_id))
            self.db.execute(delete(ClassGroup).where(ClassGroup.id.in_(group_ids)))
        for index in range(count):
            name = f"{prefix}{index + 1}组" if prefix == "第" else f"{prefix}{index + 1}"
            group = ClassGroup(teaching_class_id=class_id, name=name, sort_order=index)
            self.db.add(group); self.db.flush()
            for student_id in student_ids[index::count]:
                self.db.add(ClassGroupMember(teaching_class_id=class_id, group_id=group.id, user_id=student_id))
        self.db.commit()
        return self.list_groups(class_id, user)

    def members(self, class_id: int, user: User) -> list[dict[str, object]]:
        self.require_teacher(class_id, user)
        rows = self.db.execute(select(ClassMembership, User).join(User, User.id == ClassMembership.user_id).where(
            ClassMembership.teaching_class_id == class_id
        ).order_by(User.username)).all()
        group_map = {member.user_id: member.group_id for member in self.db.scalars(select(ClassGroupMember).where(
            ClassGroupMember.teaching_class_id == class_id
        )).all()}
        return [{"id": membership.id, "user_id": account.id, "username": account.username,
                 "identity_no": account.identity_no, "status": membership.status,
                 "join_method": membership.join_method, "group_id": group_map.get(account.id)}
                for membership, account in rows]

    def pending_requests(self, class_id: int, user: User) -> list[dict[str, object]]:
        self.require_teacher(class_id, user, owner_only=True)
        rows = self.db.execute(select(ClassJoinRequest, User).join(User, User.id == ClassJoinRequest.user_id).where(
            ClassJoinRequest.teaching_class_id == class_id, ClassJoinRequest.status == "pending"
        ).order_by(ClassJoinRequest.created_time)).all()
        return [{"id": request.id, "user_id": account.id, "username": account.username,
                 "identity_no": account.identity_no, "request_type": request.request_type,
                 "created_time": request.created_time} for request, account in rows]

    def update_status(self, class_id: int, user: User, value: str) -> TeachingClass:
        item = self.require_teacher(class_id, user, owner_only=True)
        item.status = value; self.db.commit(); self.db.refresh(item); return item

    def update_join_code(self, class_id: int, user: User, enabled: bool | None, regenerate: bool) -> TeachingClass:
        item = self.require_teacher(class_id, user, owner_only=True)
        if enabled is not None: item.join_code_enabled = enabled
        if regenerate: item.join_code = self.new_join_code()
        self.db.commit(); self.db.refresh(item); return item

    def add_teacher(self, class_id: int, user: User, teacher_id: int) -> TeachingClassTeacher:
        self.require_teacher(class_id, user, owner_only=True)
        teacher = self.db.get(User, teacher_id)
        if teacher is None or teacher.role != "teacher" or teacher.approval_status != "approved":
            raise HTTPException(status_code=400, detail="只能添加已审核通过的教师")
        existing = self.db.scalar(select(TeachingClassTeacher).where(
            TeachingClassTeacher.teaching_class_id == class_id, TeachingClassTeacher.user_id == teacher_id
        ))
        if existing: return existing
        relation = TeachingClassTeacher(teaching_class_id=class_id, user_id=teacher_id, teacher_role="collaborator")
        self.db.add(relation); self.db.commit(); self.db.refresh(relation); return relation

    def add_material(self, class_id: int, user: User, course_id: int, role: str) -> TeachingClassMaterial:
        self.require_teacher(class_id, user, owner_only=True)
        if self.db.get(Course, course_id) is None:
            raise HTTPException(status_code=404, detail="教材不存在")
        if role == "primary":
            for material in self.db.scalars(select(TeachingClassMaterial).where(
                TeachingClassMaterial.teaching_class_id == class_id,
                TeachingClassMaterial.material_role == "primary"
            )).all(): material.material_role = "supplementary"
        relation = self.db.scalar(select(TeachingClassMaterial).where(
            TeachingClassMaterial.teaching_class_id == class_id, TeachingClassMaterial.course_id == course_id
        ))
        if relation: relation.material_role = role
        else:
            relation = TeachingClassMaterial(teaching_class_id=class_id, course_id=course_id, material_role=role)
            self.db.add(relation)
        self.db.commit(); self.db.refresh(relation); return relation

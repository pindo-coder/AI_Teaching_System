from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.time import utc_now
from app.models.authority_discovery import AuthoritySourceRegistry, MaterialCandidate, PolicyChange
from app.models.teaching_class import TeachingClass, TeachingClassMaterial, TeachingClassTeacher
from app.models.teaching_notification import TeachingNotification
from app.models.user import User


class NotificationService:
    """创建和读取站内提醒；所有写入都保持幂等，便于重试索引任务。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def _teacher_recipients(self, course_ids: list[int]) -> list[int]:
        query = select(TeachingClassTeacher.user_id).join(
            TeachingClass, TeachingClass.id == TeachingClassTeacher.teaching_class_id
        ).join(
            TeachingClassMaterial, TeachingClassMaterial.teaching_class_id == TeachingClass.id
        ).where(
            TeachingClassMaterial.course_id.in_(course_ids),
            TeachingClassTeacher.user_id.in_(select(User.id).where(
                User.role == "teacher", User.approval_status == "approved"
            )),
        ) if course_ids else None
        ids = set(self.db.scalars(query).all()) if query is not None else set()
        # 尚未建立教学班和教材绑定时，不能让提醒静默丢失；回退到全部已审核教师。
        if not ids:
            ids = set(self.db.scalars(select(User.id).where(
                User.role == "teacher", User.approval_status == "approved"
            )).all())
        return sorted(ids)

    def create_policy_change_notifications(self, change: PolicyChange) -> list[TeachingNotification]:
        if change.review_status != "confirmed" or change.kb_sync_status != "synced":
            return []
        candidate = self.db.get(MaterialCandidate, change.candidate_id)
        if candidate is None:
            return []
        source = self.db.get(AuthoritySourceRegistry, candidate.source_registry_id)
        if source is not None and not source.allow_alert:
            return []
        course_ids = list(dict.fromkeys(change.affected_course_ids or candidate.course_ids or []))
        chapter_ids = list(dict.fromkeys(change.affected_chapter_ids or candidate.chapter_ids or []))
        level = "urgent" if change.importance == "high" and change.alert_recommended else (
            "important" if change.importance == "high" else ("normal" if change.importance == "medium" else "observe")
        )
        title = f"权威资料更新：{candidate.title[:80]}"
        content = (
            f"管理员已确认“{change.change_type}”，并完成中央材料知识库同步。\n"
            f"新表述：{change.new_excerpt[:260]}\n"
            "请结合课程专题判断是否需要调整教学安排。"
        )
        created: list[TeachingNotification] = []
        for user_id in self._teacher_recipients(course_ids):
            exists = self.db.scalar(select(TeachingNotification).where(
                TeachingNotification.recipient_user_id == user_id,
                TeachingNotification.policy_change_id == change.id,
                TeachingNotification.notification_type == "policy_update",
            ))
            if exists:
                continue
            item = TeachingNotification(
                recipient_user_id=user_id,
                policy_change_id=change.id,
                notification_type="policy_update",
                level=level,
                title=title,
                content=content,
                course_ids=course_ids,
                chapter_ids=chapter_ids,
                source_url=change.new_source_url,
                # 教师不一定拥有管理员资料动态页权限，提醒直接指向公开权威原文。
                action_url=None,
            )
            self.db.add(item)
            created.append(item)
        if created:
            self.db.commit()
            for item in created:
                self.db.refresh(item)
        return created

    def create_candidate_review_notifications(
        self, candidate: MaterialCandidate, *, evidence_count: int,
    ) -> list[TeachingNotification]:
        """通知管理员处理新候选；以候选详情地址作为幂等键。"""
        action_url = f"/material-discovery?candidate={candidate.id}"
        created: list[TeachingNotification] = []
        admin_ids = self.db.scalars(select(User.id).where(User.role == "admin")).all()
        for user_id in admin_ids:
            exists = self.db.scalar(select(TeachingNotification).where(
                TeachingNotification.recipient_user_id == user_id,
                TeachingNotification.notification_type == "material_review",
                TeachingNotification.action_url == action_url,
            ))
            if exists:
                continue
            item = TeachingNotification(
                recipient_user_id=user_id,
                notification_type="material_review",
                level="important" if candidate.source_level == "A" else "normal",
                title=f"待审核权威材料：{candidate.title[:80]}",
                content=f"系统已完成正文抓取和教材关联，并生成 {evidence_count} 条原文差异证据。发布前请核对来源、范围和新旧表述。",
                course_ids=list(candidate.suggested_course_ids or []),
                chapter_ids=list(candidate.suggested_chapter_ids or []),
                source_url=candidate.source_url,
                action_url=action_url,
            )
            self.db.add(item)
            created.append(item)
        if created:
            self.db.commit()
            for item in created:
                self.db.refresh(item)
        return created

    def resolve_candidate_review_notifications(self, candidate_id: int, *, commit: bool = True) -> int:
        items = list(self.db.scalars(select(TeachingNotification).where(
            TeachingNotification.notification_type == "material_review",
            TeachingNotification.action_url == f"/material-discovery?candidate={candidate_id}",
            TeachingNotification.is_read.is_(False),
        )).all())
        now = utc_now()
        for item in items:
            item.is_read = True
            item.read_time = now
        if items and commit:
            self.db.commit()
        return len(items)

    def _resolve_stale_candidate_review_notifications(self, user_id: int) -> int:
        items = list(self.db.scalars(select(TeachingNotification).where(
            TeachingNotification.recipient_user_id == user_id,
            TeachingNotification.notification_type == "material_review",
            TeachingNotification.is_read.is_(False),
        )).all())
        resolved = 0
        now = utc_now()
        threshold = float(settings.authority_discovery_min_association_score)
        relevance_threshold = float(settings.authority_discovery_min_relevance_score)
        for item in items:
            prefix = "/material-discovery?candidate="
            candidate_id = int(item.action_url.removeprefix(prefix)) if item.action_url and item.action_url.removeprefix(prefix).isdigit() else None
            candidate = self.db.get(MaterialCandidate, candidate_id) if candidate_id else None
            low_relevance = bool(
                candidate is not None and 0 < candidate.relevance_score < relevance_threshold
            )
            if candidate is not None and candidate.status == "pending_review" and (
                candidate.association_confidence < threshold or low_relevance
            ):
                candidate.status = "filtered"
                if low_relevance:
                    candidate.analysis_reason = (
                        f"主题相关度 {candidate.relevance_score:.0%} 低于审核阈值 {relevance_threshold:.0%}，已自动过滤。"
                    )
                else:
                    candidate.analysis_reason = (
                        f"教材关联度 {candidate.association_confidence:.0%} 低于审核阈值 {threshold:.0%}，已自动过滤。"
                    )
            if candidate is None or candidate.status != "pending_review":
                item.is_read = True
                item.read_time = now
                resolved += 1
        if resolved:
            self.db.commit()
        return resolved

    def list_for_user(self, user_id: int, *, unread_only: bool = False, limit: int = 50) -> list[TeachingNotification]:
        self._resolve_stale_candidate_review_notifications(user_id)
        query = select(TeachingNotification).where(
            TeachingNotification.recipient_user_id == user_id
        ).order_by(TeachingNotification.created_time.desc()).limit(limit)
        if unread_only:
            query = query.where(TeachingNotification.is_read.is_(False))
        return list(self.db.scalars(query).all())

    def mark_read(self, notification_id: int, user_id: int) -> TeachingNotification:
        item = self.db.scalar(select(TeachingNotification).where(
            TeachingNotification.id == notification_id,
            TeachingNotification.recipient_user_id == user_id,
        ))
        if item is None:
            raise ValueError("教学提醒不存在")
        item.is_read = True
        item.read_time = utc_now()
        self.db.commit()
        self.db.refresh(item)
        return item

    def mark_all_read(self, user_id: int) -> int:
        items = self.list_for_user(user_id, unread_only=True, limit=1000)
        now = utc_now()
        for item in items:
            item.is_read = True
            item.read_time = now
        if items:
            self.db.commit()
        return len(items)

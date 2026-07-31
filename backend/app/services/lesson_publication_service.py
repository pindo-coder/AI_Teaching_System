from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import BACKEND_DIR, settings
from app.models.agent_run import AgentRun
from app.models.chapter import Chapter
from app.models.classroom import ClassroomActivity
from app.models.course import Course
from app.models.lesson_publication import LessonPublication
from app.models.teaching_class import (
    ClassMembership,
    TeachingClass,
    TeachingClassMaterial,
    TeachingClassTeacher,
)
from app.models.user import User
from app.schemas.agent import LessonPublicationData, LessonPublishRequest
from app.services.presentation_artifact_service import PresentationArtifactService
from app.services.teaching_class_service import TeachingClassService


class LessonPublicationService:
    def __init__(self, db: Session, user: User) -> None:
        self.db = db
        self.user = user
        root = Path(settings.generated_artifact_directory)
        if not root.is_absolute():
            root = (BACKEND_DIR / root).resolve()
        self.root = root

    def _require_run(self, run_id: int) -> AgentRun:
        run = self.db.get(AgentRun, run_id)
        if run is None or (self.user.role != "admin" and run.created_by != self.user.id):
            raise HTTPException(status_code=404, detail="备课任务不存在或无权访问")
        if run.status != "completed" or run.current_step < 3:
            raise HTTPException(status_code=400, detail="请先完成教学成果生成")
        return run

    def _can_access(self, item: LessonPublication) -> bool:
        if self.user.role == "admin" or item.created_by == self.user.id:
            return True
        if self.user.role == "teacher":
            return self.db.scalar(
                select(TeachingClassTeacher.id).where(
                    TeachingClassTeacher.teaching_class_id == item.teaching_class_id,
                    TeachingClassTeacher.user_id == self.user.id,
                )
            ) is not None
        return self.db.scalar(
            select(ClassMembership.id).where(
                ClassMembership.teaching_class_id == item.teaching_class_id,
                ClassMembership.user_id == self.user.id,
                ClassMembership.status == "active",
            )
        ) is not None

    def _serialize(self, item: LessonPublication) -> LessonPublicationData:
        teaching_class = self.db.get(TeachingClass, item.teaching_class_id)
        chapter = self.db.get(Chapter, item.chapter_id)
        teacher = self.db.get(User, item.created_by)
        return LessonPublicationData(
            id=item.id,
            agent_run_id=item.agent_run_id,
            teaching_class_id=item.teaching_class_id,
            teaching_class_name=teaching_class.name if teaching_class else "已删除教学班",
            course_id=item.course_id,
            chapter_id=item.chapter_id,
            chapter_title=chapter.title if chapter else "已删除专题",
            created_by=item.created_by,
            teacher_name=teacher.username if teacher else "教师",
            title=item.title,
            description=item.description,
            ppt_available=bool(item.ppt_storage_path),
            ppt_file_name=item.ppt_file_name,
            discussion_activity_ids=list(item.discussion_activity_ids or []),
            status=item.status,
            created_time=item.created_time,
        )

    def publish(self, run_id: int, payload: LessonPublishRequest) -> LessonPublicationData:
        run = self._require_run(run_id)
        TeachingClassService(self.db).require_teacher(payload.teaching_class_id, self.user)
        if self.db.scalar(
            select(TeachingClassMaterial.id).where(
                TeachingClassMaterial.teaching_class_id == payload.teaching_class_id,
                TeachingClassMaterial.course_id == run.course_id,
            )
        ) is None:
            raise HTTPException(status_code=400, detail="该课程尚未绑定到所选教学班")
        existing = self.db.scalar(
            select(LessonPublication).where(
                LessonPublication.agent_run_id == run.id,
                LessonPublication.teaching_class_id == payload.teaching_class_id,
            )
        )
        if existing is not None:
            raise HTTPException(status_code=409, detail="该备课成果已发布到此教学班")
        output = run.output_data or {}
        bundle = output.get("artifact_bundle") or {}
        artifacts = output.get("artifacts") or {}
        ppt_artifact = artifacts.get("ppt")
        activities = bundle.get("classroom_activities") or []
        if payload.publish_ppt and not isinstance(ppt_artifact, dict):
            raise HTTPException(status_code=400, detail="当前任务没有可发布的 PPT")
        if payload.publish_discussions and not activities:
            raise HTTPException(status_code=400, detail="当前任务没有可发布的课堂讨论")

        item = LessonPublication(
            agent_run_id=run.id,
            teaching_class_id=payload.teaching_class_id,
            course_id=int(run.course_id),
            chapter_id=int(run.chapter_id),
            created_by=self.user.id,
            title=payload.title.strip(),
            description=payload.description.strip(),
            discussion_activity_ids=[],
        )
        self.db.add(item)
        self.db.flush()
        publication_dir = self.root / "publications" / str(item.id)
        copied_path: Path | None = None
        try:
            if payload.publish_ppt:
                source = PresentationArtifactService(run.id).resolve_download(ppt_artifact)
                publication_dir.mkdir(parents=True, exist_ok=True)
                copied_path = publication_dir / source.name
                shutil.copy2(source, copied_path)
                item.ppt_storage_path = str(copied_path.relative_to(self.root))
                item.ppt_file_name = source.name
            selected = payload.discussion_indices or list(range(len(activities)))
            activity_ids: list[int] = []
            if payload.publish_discussions:
                for index in selected:
                    if not 0 <= index < len(activities):
                        raise HTTPException(status_code=400, detail=f"课堂讨论序号 {index + 1} 无效")
                    data: dict[str, Any] = activities[index]
                    questions = [str(value) for value in (data.get("questions") or []) if value]
                    question = str(data.get("title") or "课堂讨论")
                    if data.get("purpose"):
                        question += f"\n\n讨论目标：{data['purpose']}"
                    if questions:
                        question += "\n\n" + "\n".join(
                            f"{question_index + 1}. {value}"
                            for question_index, value in enumerate(questions)
                        )
                    activity = ClassroomActivity(
                        teaching_class_id=payload.teaching_class_id,
                        course_id=int(run.course_id),
                        chapter_id=int(run.chapter_id),
                        created_by=self.user.id,
                        question=question[:2000],
                        minutes=max(3, min(60, int(data.get("duration_minutes") or 8))),
                        status="published",
                    )
                    self.db.add(activity)
                    self.db.flush()
                    activity_ids.append(activity.id)
            item.discussion_activity_ids = activity_ids
            self.db.commit()
            self.db.refresh(item)
            return self._serialize(item)
        except Exception:
            self.db.rollback()
            if copied_path:
                copied_path.unlink(missing_ok=True)
            raise

    def list(self, teaching_class_id: int | None = None) -> list[LessonPublicationData]:
        statement = select(LessonPublication).where(LessonPublication.status == "published")
        if teaching_class_id is not None:
            statement = statement.where(LessonPublication.teaching_class_id == teaching_class_id)
        if self.user.role == "student":
            class_ids = select(ClassMembership.teaching_class_id).where(
                ClassMembership.user_id == self.user.id,
                ClassMembership.status == "active",
            )
            statement = statement.where(LessonPublication.teaching_class_id.in_(class_ids))
        elif self.user.role == "teacher":
            class_ids = select(TeachingClassTeacher.teaching_class_id).where(
                TeachingClassTeacher.user_id == self.user.id
            )
            statement = statement.where(LessonPublication.teaching_class_id.in_(class_ids))
        rows = self.db.scalars(statement.order_by(LessonPublication.id.desc())).all()
        return [self._serialize(item) for item in rows]

    def download(self, publication_id: int) -> tuple[Path, LessonPublication]:
        item = self.db.get(LessonPublication, publication_id)
        if item is None or item.status != "published" or not self._can_access(item):
            raise HTTPException(status_code=404, detail="已发布课件不存在或无权访问")
        if not item.ppt_storage_path:
            raise HTTPException(status_code=404, detail="该发布记录不包含 PPT")
        path = (self.root / item.ppt_storage_path).resolve()
        if path != self.root.resolve() and self.root.resolve() not in path.parents:
            raise HTTPException(status_code=404, detail="课件文件路径无效")
        if not path.is_file():
            raise HTTPException(status_code=404, detail="课件文件不存在")
        return path, item

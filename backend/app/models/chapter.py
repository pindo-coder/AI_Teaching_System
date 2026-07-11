from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.course import Course
    from app.models.knowledge_document import KnowledgeDocument
    from app.models.learning_progress import LearningProgress


class Chapter(TimestampMixin, Base):
    __tablename__ = "chapters"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(default=0, nullable=False)

    course: Mapped["Course"] = relationship(back_populates="chapters")
    learning_progress: Mapped[list["LearningProgress"]] = relationship(back_populates="chapter")
    documents: Mapped[list["KnowledgeDocument"]] = relationship(back_populates="chapter")

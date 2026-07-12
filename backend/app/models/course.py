from typing import TYPE_CHECKING

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.chapter import Chapter
    from app.models.knowledge_document import KnowledgeDocument
    from app.models.learning_progress import LearningProgress


class Course(TimestampMixin, Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    chapters: Mapped[list["Chapter"]] = relationship(
        back_populates="course", cascade="all, delete-orphan", order_by="Chapter.sort_order"
    )
    learning_progress: Mapped[list["LearningProgress"]] = relationship(
        back_populates="course",
        cascade="all, delete-orphan",
    )
    documents: Mapped[list["KnowledgeDocument"]] = relationship(back_populates="course")

from sqlalchemy import BigInteger, Float, ForeignKey, String, Text
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin


class AiMediaAsset(TimestampMixin, Base):
    """A private, locally stored image or audio attachment owned by one user."""

    __tablename__ = "ai_media_assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    course_id: Mapped[int | None] = mapped_column(
        ForeignKey("courses.id", ondelete="SET NULL"), index=True
    )
    chapter_id: Mapped[int | None] = mapped_column(
        ForeignKey("chapters.id", ondelete="SET NULL"), index=True
    )
    media_kind: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(50), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # 160 characters stays below legacy MySQL utf8mb4 index length limits.
    storage_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ready")
    # Reserved for future asynchronous media processing failures. Never indexed.
    error_message: Mapped[str | None] = mapped_column(
        Text().with_variant(LONGTEXT(), "mysql")
    )

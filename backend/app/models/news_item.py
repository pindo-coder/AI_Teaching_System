from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NewsItem(Base):
    __tablename__ = "news_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    source_name: Mapped[str] = mapped_column(String(100), nullable=False)
    source_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    # MySQL 5.7 utf8mb4 唯一索引最多 3072 bytes，700 字符可安全兼容。
    article_url: Mapped[str] = mapped_column(String(700), unique=True, nullable=False)
    published_time: Mapped[datetime | None] = mapped_column(DateTime)
    fetched_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

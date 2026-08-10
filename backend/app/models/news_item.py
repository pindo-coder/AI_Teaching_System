from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, false
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utc_now
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
    # 旧版本把 RSS 的 +0800 墙上时间直接去掉 tzinfo；不能无依据回写历史值。
    # 迁移将历史行标为 False，新抓取行由 ORM 默认标为 True。
    published_time_is_utc: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default=false(),
        nullable=False,
    )
    fetched_time: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

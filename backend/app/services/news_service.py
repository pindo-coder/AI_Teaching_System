from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.request import Request, urlopen
import logging
import xml.etree.ElementTree as ET

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.news_item import NewsItem


logger = logging.getLogger(__name__)
FEEDS = (
    ("人民网时政", "https://www.people.com.cn/rss/politics.xml"),
    ("中国新闻网时政", "https://www.chinanews.com.cn/rss/china.xml"),
)


def _clean(value: str | None) -> str:
    return " ".join(unescape(value or "").replace("<![CDATA[", "").replace("]]>", "").split())


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).replace(tzinfo=None)
    except (TypeError, ValueError, OverflowError):
        return None


class NewsService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list(self, limit: int = 20) -> list[NewsItem]:
        return list(self.db.scalars(select(NewsItem).order_by(NewsItem.published_time.desc(), NewsItem.id.desc()).limit(limit)).all())

    def refresh(self) -> int:
        created = 0
        for source_name, source_url in FEEDS:
            try:
                request = Request(source_url, headers={"User-Agent": "AI-Teaching-System/0.1"})
                with urlopen(request, timeout=8) as response:
                    root = ET.fromstring(response.read())
                for item in root.findall(".//item")[:20]:
                    title = _clean(item.findtext("title"))
                    article_url = _clean(item.findtext("link"))
                    if not title or not article_url or self.db.scalar(select(NewsItem).where(NewsItem.article_url == article_url)):
                        continue
                    summary = _clean(item.findtext("description"))[:1000] or None
                    published_time = _parse_time(item.findtext("pubDate"))
                    self.db.add(NewsItem(title=title, summary=summary, source_name=source_name, source_url=source_url, article_url=article_url, published_time=published_time, fetched_time=datetime.utcnow()))
                    created += 1
            except (OSError, ET.ParseError, ValueError) as exc:
                logger.warning("news_feed_failed source=%s error=%s", source_name, exc)
        self.db.commit()
        self._trim()
        return created

    def refresh_if_stale(self) -> int:
        latest = self.db.scalar(select(NewsItem).order_by(NewsItem.fetched_time.desc()))
        if latest and latest.fetched_time > datetime.utcnow() - timedelta(minutes=30):
            return 0
        return self.refresh()

    def _trim(self) -> None:
        items = list(self.db.scalars(select(NewsItem).order_by(NewsItem.fetched_time.desc())).all())
        for item in items[60:]:
            self.db.delete(item)
        self.db.commit()

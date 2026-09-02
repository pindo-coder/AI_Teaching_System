from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from html import escape, unescape
from html.parser import HTMLParser
from urllib.request import Request, urlopen
import logging
import re
import xml.etree.ElementTree as ET

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.time import BUSINESS_TIMEZONE, to_business_time, to_utc_naive, utc_now
from app.core.config import settings
from app.models.news_item import NewsItem
from app.models.news_study_note import NewsStudyNote
from app.models.chapter import Chapter
from app.models.course import Course
from app.models.study_note import StudyNote
from app.schemas.news import NewsStudyNoteSave
from app.services.study_service import StudyService


logger = logging.getLogger(__name__)
FEEDS = (
    ("人民网时政", "https://www.people.com.cn/rss/politics.xml"),
    ("中国新闻网时政", "https://www.chinanews.com.cn/rss/china.xml"),
    # 央视新闻公开提供国内新闻 RSS；单个源失败不会影响其他来源刷新。
    ("央视新闻国内", "https://www.cctv.com/program/rss/02/01/index.xml"),
    # 同一媒体的要闻流作为补充，保留来源名称以便学生辨识资讯出处。
    ("中国新闻网要闻", "https://www.chinanews.com.cn/rss/importnews.xml"),
)


class _SummaryTextExtractor(HTMLParser):
    """RSS description 只保留可读文字，图片、表格结构与样式均不进入摘要。"""

    BLOCK_TAGS = {"p", "div", "br", "li", "tr", "td", "h1", "h2", "h3", "h4", "h5", "h6"}
    IGNORED_TAGS = {"script", "style", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self.IGNORED_TAGS:
            self.ignored_depth += 1
        elif tag in self.BLOCK_TAGS and not self.ignored_depth:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.IGNORED_TAGS and self.ignored_depth:
            self.ignored_depth -= 1
        elif tag in self.BLOCK_TAGS and not self.ignored_depth:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self.ignored_depth:
            self.parts.append(data)


def _clean(value: str | None) -> str:
    raw = unescape(value or "").replace("<![CDATA[", "").replace("]]>", "")
    parser = _SummaryTextExtractor()
    try:
        parser.feed(raw)
        parser.close()
        text = " ".join(parser.parts)
    except Exception:
        # 极少数不完整旧 HTML 仍以保守正则移除标签，不能把标签原样展示给用户。
        text = re.sub(r"<[^>]*>", " ", raw)
    text = text.replace("\ufffd", "")
    return " ".join(text.split())


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    try:
        # 中国来源常把 China Standard Time 简写为 CST，而 email.utils
        # 会将 CST 按北美中部时间解释。仅改写末尾的时区 token，避免影响
        # 已明确携带数值 offset 的合法日期。
        normalized = re.sub(r"\s+CST\s*$", " +0800", value.strip(), flags=re.IGNORECASE)
        parsed = parsedate_to_datetime(normalized)
        return to_utc_naive(parsed, naive_timezone=BUSINESS_TIMEZONE)
    except (TypeError, ValueError, OverflowError):
        pass
    # Atom and newer RSS feeds commonly use ISO-8601 instead of RFC-822.
    try:
        iso_value = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
        parsed = datetime.fromisoformat(iso_value)
        return to_utc_naive(parsed, naive_timezone=BUSINESS_TIMEZONE)
    except (TypeError, ValueError, OverflowError):
        pass
    # 部分中文站点直接返回“2026年9月2日 10:30”。
    match = re.search(
        r"(20\d{2})[年./-](\d{1,2})[月./-](\d{1,2})日?\s*"
        r"(\d{1,2})?:?(\d{2})?(?::(\d{2}))?",
        value,
    )
    if match:
        try:
            year, month, day, hour, minute, second = (int(part or 0) for part in match.groups())
            return to_utc_naive(
                datetime(year, month, day, hour, minute, second),
                naive_timezone=BUSINESS_TIMEZONE,
            )
        except (TypeError, ValueError, OverflowError):
            return None
    return None


def _published_time_utc(item: NewsItem) -> datetime | None:
    """Interpret a news timestamp without rewriting ambiguous historical rows."""
    if item.published_time is None:
        return None
    naive_timezone = UTC if item.published_time_is_utc else BUSINESS_TIMEZONE
    return to_utc_naive(item.published_time, naive_timezone=naive_timezone)


def _effective_news_time(item: NewsItem) -> datetime:
    return _published_time_utc(item) or to_utc_naive(item.fetched_time)


def _parse_feed(payload: bytes) -> ET.Element:
    """兼容部分新闻 RSS 使用 GBK/GB2312 声明的 XML。"""
    try:
        return ET.fromstring(payload)
    except ValueError:
        text = payload.decode("gb18030", errors="replace")
        text = re.sub(r"encoding=['\"][^'\"]+['\"]", 'encoding="utf-8"', text, count=1, flags=re.IGNORECASE)
        return ET.fromstring(text)


class NewsService:
    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def _feed_items(root: ET.Element) -> list[ET.Element]:
        """Return RSS items and Atom entries using one normalized iteration path."""
        items = root.findall(".//item") or root.findall(".//{*}item")
        return items or root.findall(".//{*}entry")

    @staticmethod
    def _feed_value(item: ET.Element, *names: str) -> str | None:
        for name in names:
            value = item.findtext(name) or item.findtext(f"{{*}}{name}")
            if value:
                return value
        if "link" in names:
            link = item.find("{*}link")
            if link is not None:
                return link.attrib.get("href") or link.text
        return None

    def list(self, limit: int = 20) -> list[NewsItem]:
        items = list(self.db.scalars(select(NewsItem)).all())
        items.sort(key=lambda item: (_effective_news_time(item), item.id), reverse=True)
        return items[:limit]

    def source_names(self) -> list[str]:
        configured = [name for name, _ in FEEDS]
        stored = list(self.db.scalars(select(NewsItem.source_name).distinct()).all())
        return list(dict.fromkeys([*configured, *stored]))

    def clean_existing_summaries(self) -> int:
        """幂等修复历史 RSS 摘要；正常纯文本不会发生更新。"""
        changed = 0
        for item in self.db.scalars(select(NewsItem)).all():
            cleaned = _clean(item.summary)[:1000] if item.summary else None
            if cleaned != item.summary:
                item.summary = cleaned or None
                changed += 1
        if changed:
            self.db.commit()
            logger.info("news_summaries_cleaned count=%s", changed)
        return changed

    def search(self, query: str = "", sources: list[str] | None = None, days: int | None = None,
               sort_by: str = "latest", page: int = 1, page_size: int = 10) -> dict[str, object]:
        self.clean_existing_summaries()
        statement = select(NewsItem)
        keyword = query.strip()
        if keyword:
            pattern = f"%{keyword}%"
            statement = statement.where(or_(NewsItem.title.ilike(pattern), NewsItem.summary.ilike(pattern)))
        if sources:
            statement = statement.where(NewsItem.source_name.in_(sources))
        items = list(self.db.scalars(statement).all())
        if days is not None:
            cutoff = utc_now() - timedelta(days=days)
            items = [item for item in items if _effective_news_time(item) >= cutoff]

        def relevance(item: NewsItem) -> tuple[float, datetime, int]:
            if not keyword:
                return 0.0, _effective_news_time(item), item.id
            haystack = f"{item.title} {item.summary or ''}".lower()
            lowered = keyword.lower()
            query_grams = self._grams(lowered)
            overlap = len(query_grams & self._grams(haystack)) / max(1, len(query_grams))
            score = item.title.lower().count(lowered) * 5 + haystack.count(lowered) + overlap
            return score, _effective_news_time(item), item.id

        if sort_by == "relevance" and keyword:
            items.sort(key=relevance, reverse=True)
        else:
            items.sort(key=lambda item: (_effective_news_time(item), item.id), reverse=True)
        total = len(items)
        start = (page - 1) * page_size
        return {
            "items": items[start:start + page_size],
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": max(1, (total + page_size - 1) // page_size),
            "sources": self.source_names(),
        }

    def require_news(self, news_id: int) -> NewsItem:
        item = self.db.get(NewsItem, news_id)
        if item is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="时政材料不存在")
        return item

    @staticmethod
    def _grams(value: str) -> set[str]:
        clean = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", value).lower()
        return {clean[index:index + 2] for index in range(max(0, len(clean) - 1))}

    def textbook_relations(self, news_id: int, course_id: int, limit: int = 3) -> list[dict[str, object]]:
        """跨全部章节匹配，避免把每条时政机械地交给教材第一章。"""
        item = self.require_news(news_id)
        course = self.db.get(Course, course_id)
        if course is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="教材不存在")
        query = f"{item.title} {item.summary or ''}"
        query_grams = self._grams(query)
        ranked: list[tuple[float, Chapter, str, int, list[str]]] = []
        chapters = self.db.scalars(
            select(Chapter).where(Chapter.course_id == course_id).order_by(Chapter.sort_order, Chapter.id)
        ).all()
        for chapter in chapters:
            paragraphs = [part.strip() for part in re.split(r"\n\s*\n|(?<=[。！？；])", chapter.content or "") if len(part.strip()) >= 16]
            candidates = paragraphs or ([chapter.content.strip()] if chapter.content and chapter.content.strip() else [])
            best_score, best_excerpt, best_index, best_overlap = 0.0, "", 0, []
            title_grams = self._grams(chapter.title)
            for index, paragraph in enumerate(candidates):
                paragraph_grams = self._grams(paragraph)
                overlap = query_grams & paragraph_grams
                coverage = len(overlap) / max(1, min(len(query_grams), 120))
                title_bonus = len(query_grams & title_grams) / max(1, len(title_grams)) * 0.25
                score = coverage + title_bonus
                if score > best_score:
                    best_score, best_excerpt, best_index = score, paragraph, index
                    best_overlap = sorted(overlap, key=lambda gram: query.find(gram))[:6]
            # 章节正文过短或没有直接命中时仍保留低分候选，让用户能够自主选择。
            ranked.append((best_score, chapter, best_excerpt or (chapter.content or "")[:300], best_index, best_overlap))
        ranked.sort(key=lambda row: (row[0], -row[1].sort_order), reverse=True)
        output = []
        for score, chapter, excerpt, paragraph_index, overlap in ranked[:limit]:
            keywords = "、".join(dict.fromkeys(overlap[:4]))
            reason = f"时政材料与本章共同涉及“{keywords}”等表述。" if keywords else "当前为候选章节，请结合教材内容人工确认关联。"
            output.append({
                "course_id": course_id,
                "chapter_id": chapter.id,
                "chapter_title": chapter.title,
                "score": round(min(1.0, score), 3),
                "reason": reason,
                "excerpt": excerpt[:320],
                "position": f"{chapter.title} · 正文第 {paragraph_index + 1} 段",
            })
        return output

    @staticmethod
    def _draft_html(title: str, source_name: str, source_url: str, published_time: datetime | None, content: str) -> str:
        """把模型纯文本转换为受限的笔记 HTML，避免把任意 HTML 写入笔记。"""
        blocks: list[str] = [f"<h2>时政研学：{escape(title)}</h2>"]
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            heading = re.match(r"^#{1,4}\s+(.+)$", line)
            if heading:
                blocks.append(f"<h3>{escape(heading.group(1))}</h3>")
            else:
                blocks.append(f"<p>{escape(line)}</p>")
        published = (
            to_business_time(published_time).strftime("%Y-%m-%d %H:%M")
            if published_time else "发布时间未注明"
        )
        blocks.append(f"<p><strong>资料来源：</strong>{escape(source_name)}，{published}，{escape(source_url)}</p>")
        return "".join(blocks)

    def save_study_note(self, user_id: int, news_id: int, payload: NewsStudyNoteSave) -> dict[str, object]:
        item = self.require_news(news_id)
        chapter = self.db.get(Chapter, payload.chapter_id)
        if chapter is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="专题章节不存在")
        existing = self.db.scalar(select(StudyNote).where(
            StudyNote.user_id == user_id, StudyNote.chapter_id == chapter.id
        ))
        if payload.mode == "create" and existing is not None and StudyService.plain_note_content(existing.content):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该章节已有笔记，请选择追加到现有笔记")
        published_time = _published_time_utc(item)
        section = self._draft_html(item.title, item.source_name, item.article_url, published_time, payload.content)
        combined = section if existing is None or not StudyService.plain_note_content(existing.content) else f"{existing.content}<hr>{section}"
        if len(combined) > 30000:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="现有笔记内容较多，请精简研学草稿后再添加")
        note = StudyService(self.db).save_note(user_id, chapter.id, combined)
        link = self.db.scalar(select(NewsStudyNote).where(
            NewsStudyNote.user_id == user_id,
            NewsStudyNote.news_id == item.id,
            NewsStudyNote.chapter_id == chapter.id,
        ))
        if link is None:
            link = NewsStudyNote(
                user_id=user_id, note_id=note.id, news_id=item.id, course_id=chapter.course_id,
                chapter_id=chapter.id, ai_summary=payload.content, textbook_relation=payload.textbook_relation,
                source_title=item.title, source_url=item.article_url, published_at=published_time,
            )
            self.db.add(link)
        else:
            link.note_id = note.id
            link.ai_summary = payload.content
            link.textbook_relation = payload.textbook_relation
        self.db.commit()
        return {"note_id": note.id, "course_id": chapter.course_id, "chapter_id": chapter.id,
                "created": existing is None, "appended": existing is not None}

    def refresh(self) -> int:
        created = 0
        # 同一篇稿件可能同时出现在“时政”和“要闻”流中；本轮内也必须去重。
        existing_by_url = {
            item.article_url: item for item in self.db.scalars(select(NewsItem)).all()
        }
        for source_name, source_url in FEEDS:
            try:
                # 给 RSS 地址增加时间戳，避免 CDN/反向代理重复返回历史快照。
                separator = "&" if "?" in source_url else "?"
                request = Request(
                    f"{source_url}{separator}_ts={int(utc_now().timestamp())}",
                    headers={"User-Agent": "AI-Teaching-System/0.1", "Cache-Control": "no-cache"},
                )
                with urlopen(request, timeout=settings.news_request_timeout_seconds) as response:
                    root = _parse_feed(response.read())
                for item in self._feed_items(root)[:settings.news_feed_item_limit]:
                    title = _clean(self._feed_value(item, "title"))
                    article_url = _clean(self._feed_value(item, "link"))
                    if not title or not article_url:
                        continue
                    summary = _clean(self._feed_value(item, "description", "summary", "content"))[:1000] or None
                    published_time = _parse_time(
                        self._feed_value(item, "pubDate", "published", "updated", "date")
                    )
                    existing = existing_by_url.get(article_url)
                    if existing is None:
                        existing = NewsItem(
                            article_url=article_url,
                            source_name=source_name,
                            title=title,
                        )
                        self.db.add(existing)
                        existing_by_url[article_url] = existing
                        created += 1
                    # 同一链接的稿件可能被媒体补发或修订，不能永久保留首次抓取的旧日期。
                    existing.title = title
                    existing.summary = summary
                    existing.source_name = source_name
                    existing.source_url = source_url
                    existing.published_time = published_time
                    existing.published_time_is_utc = True
                    existing.fetched_time = utc_now()
            except (OSError, ET.ParseError, ValueError) as exc:
                logger.warning("news_feed_failed source=%s error=%s", source_name, exc)
        self.db.commit()
        self._trim()
        return created

    def refresh_if_stale(self) -> int:
        latest = self.db.scalar(select(NewsItem).order_by(NewsItem.fetched_time.desc()))
        now = utc_now()
        recently_fetched = latest and latest.fetched_time > now - timedelta(
            minutes=settings.news_refresh_interval_minutes
        )
        # 不能只看 fetched_time：上游可能返回了“刚抓取但多年未更新”的缓存快照。
        newest_published = max(
            (_effective_news_time(item) for item in self.db.scalars(select(NewsItem)).all()),
            default=None,
        )
        feed_is_stale = newest_published is None or newest_published < now - timedelta(
            days=settings.news_max_stale_days
        )
        if recently_fetched and not feed_is_stale:
            return 0
        return self.refresh()

    def _trim(self) -> None:
        items = list(self.db.scalars(select(NewsItem).order_by(NewsItem.fetched_time.desc())).all())
        for item in items[60:]:
            self.db.delete(item)
        self.db.commit()

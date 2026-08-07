from __future__ import annotations

from datetime import date, datetime, timedelta
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
import hashlib
import ipaddress
import json
import math
from pathlib import Path
import re
from threading import BoundedSemaphore, Event, Lock, Thread
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
import socket
import time
import xml.etree.ElementTree as ET

import httpx
from fastapi import HTTPException
from langchain_core.prompts import ChatPromptTemplate
from sqlalchemy import Engine, and_, delete, func, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.logging import get_logger
from app.models.authority_discovery import (
    AuthoritySourceRegistry, DiscoveryJob, MaterialCandidate, MaterialSnapshot, PolicyChange,
)
from app.models.chapter import Chapter
from app.models.course import Course
from app.models.citation import DocumentPage, KnowledgeChunk
from app.models.knowledge_document import KnowledgeDocument
from app.models.material_scope import DocumentCourseScope
from app.models.user import User
from app.models.teaching_notification import TeachingNotification
from app.schemas.authority_discovery import (
    AuthoritySourceCreate, AuthoritySourceUpdate, CandidateBatchAction, CandidateReview, DiscoveryJobCreate,
)
from app.services.material_center_service import _assert_public_https
from app.services.material_center_service import MaterialCenterService
from app.services.authority_source_adapters import get_source_adapter
from app.services.knowledge_service import KnowledgeService
from app.services.notification_service import NotificationService
from app.services.llm_compat import clean_model_text
from app.services.ai_operation_service import AiProviderConfigService, build_chat_model
from app.rag.retriever import retrieve


logger = get_logger(__name__)


DEFAULT_SOURCES = (
    {
        "name": "中国政府网",
        "domain": "gov.cn",
        "source_level": "A",
        "adapter_type": "html_list",
        "entry_url": "https://www.gov.cn/zhengce/index.htm",
        "fetch_interval_minutes": 1440,
    },
    {
        "name": "教育部",
        "domain": "moe.gov.cn",
        "source_level": "A",
        "adapter_type": "html_list",
        "entry_url": "https://www.moe.gov.cn/jyb_xwfb/gzdt_gzdt/",
        "fetch_interval_minutes": 1440,
    },
    {
        "name": "求是网",
        "domain": "qstheory.cn",
        "source_level": "B",
        "adapter_type": "html_list",
        "entry_url": "https://www.qstheory.cn/",
        "fetch_interval_minutes": 1440,
    },
)


def _domain_matches(hostname: str | None, domain: str) -> bool:
    host = (hostname or "").lower().rstrip(".")
    wanted = domain.lower().removeprefix("www.").rstrip(".")
    return host == wanted or host.endswith(f".{wanted}")


def _validate_source_url(url: str, domain: str, *, allow_http: bool = False) -> None:
    parsed = urlparse(url)
    if parsed.scheme == "https":
        _assert_public_https(url)
    elif allow_http and parsed.scheme == "http" and parsed.hostname and not parsed.username and not parsed.password:
        try:
            addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or 80)}
        except OSError as exc:
            raise HTTPException(status_code=400, detail="权威来源网址无法解析") from exc
        if any(not ipaddress.ip_address(address).is_global for address in addresses):
            raise HTTPException(status_code=400, detail="权威来源网址不能指向本机或内网地址")
    else:
        raise HTTPException(status_code=400, detail="权威来源必须使用 HTTPS")
    if not _domain_matches(parsed.hostname, domain):
        raise HTTPException(status_code=400, detail="来源入口网址必须属于配置的白名单域名")


def _canonical_url(url: str) -> str:
    parsed = urlparse(url)
    ignored = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "spm"}
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key not in ignored]
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunparse((parsed.scheme.lower(), (parsed.hostname or "").lower(), path, "", urlencode(query), ""))


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    text = value.strip()
    match = re.search(r"(20\d{2})[年./\-](\d{1,2})[月./\-](\d{1,2})", text)
    if match:
        try:
            return date(*map(int, match.groups()))
        except ValueError:
            return None
    try:
        return parsedate_to_datetime(text).date()
    except (TypeError, ValueError, OverflowError):
        return None


def _topic_match(title: str, url: str, keywords: list[str]) -> bool:
    if not keywords:
        return True
    haystack = f"{title} {url}".lower()
    return any(keyword.lower() in haystack for keyword in keywords if keyword.strip())


def _estimate_content_quality(content: str) -> float:
    """估计正文质量，过滤栏目导航、推荐链接等低信息页面。"""
    compact = re.sub(r"\s+", "", content or "")
    if not compact:
        return 0.0
    paragraphs = [re.sub(r"\s+", "", part) for part in re.split(r"\n+|(?<=[。！？；])", content) if re.sub(r"\s+", "", part)]
    meaningful = [part for part in paragraphs if len(part) >= 12]
    average = sum(map(len, meaningful)) / max(1, len(meaningful))
    length_score = min(1.0, len(compact) / 1200)
    paragraph_score = min(1.0, len(meaningful) / 5)
    density_score = min(1.0, average / 90)
    short_ratio = sum(len(part) < 28 for part in paragraphs) / max(1, len(paragraphs))
    quality = 0.30 * length_score + 0.25 * paragraph_score + 0.45 * density_score
    punctuation_ratio = sum(any(mark in part for mark in "。！？；") for part in paragraphs) / max(1, len(paragraphs))
    if len(paragraphs) >= 8 and short_ratio >= 0.75 and punctuation_ratio < 0.5:
        quality *= 0.55
    if len(compact) >= 200 and punctuation_ratio >= 0.5:
        quality = max(quality, 0.65)
    return round(max(0.0, min(1.0, quality)), 4)


def _score(title: str, content: str, keywords: list[str], source_level: str) -> tuple[float, str]:
    """只计算主题相关度；来源等级不再混入，避免无主题任务恒定显示 35%。"""
    if not keywords:
        return 0.0, "本次为全量来源巡检，未设置单一主题词；相关性将依据教材关联度和教学重要度单独计算。"
    title_text = title.lower()
    content_text = content[:30000].lower()
    title_hits = [keyword.strip() for keyword in keywords if keyword.strip() and keyword.lower() in title_text]
    body_hits = [keyword.strip() for keyword in keywords if keyword.strip() and keyword.lower() in content_text]
    distinct_hits = list(dict.fromkeys([*title_hits, *body_hits]))
    title_score = min(0.65, len(set(title_hits)) * 0.65)
    body_score = min(0.35, len(set(body_hits)) * 0.12)
    relevance = min(1.0, title_score + body_score)
    reason = f"主题相关度：标题命中{len(set(title_hits))}项，正文命中{len(set(body_hits))}项（{'、'.join(distinct_hits) if distinct_hits else '无'}）。来源等级 {source_level} 单独用于权威性排序。"
    return round(relevance, 4), reason


def _importance_score(*, source_level: str, relevance: float, association: float,
                      freshness: float, title: str, content: str, novelty: float = 1.0) -> tuple[float, str, str]:
    policy_words = ("决定", "意见", "通知", "办法", "报告", "部署", "规划", "实施", "会议", "讲话", "条例")
    source_weight = {"A": 1.0, "B": 0.78, "C": 0.55, "D": 0.25}.get(source_level, 0.25)
    policy_weight = 1.0 if any(word in title for word in policy_words) else 0.45
    evidence_weight = min(1.0, len(re.sub(r"\s+", "", content or "")) / 1600)
    score = (source_weight * 0.25 + policy_weight * 0.20 + relevance * 0.20
             + association * 0.15 + novelty * 0.15 + freshness * 0.05)
    score = round(max(0.0, min(1.0, score)), 4)
    # 正文证据不足时不允许仅凭标题给出“重要”结论。
    if evidence_weight < 0.35:
        score = round(score * 0.75, 4)
    level = "high" if score >= 0.75 else "medium" if score >= 0.60 else "observe"
    reason = f"来源权威性{source_weight:.0%}；政策文件特征{policy_weight:.0%}；正文证据{evidence_weight:.0%}；教材关联{association:.0%}。"
    return score, level, reason


def _fetch_source_bytes(
    source: AuthoritySourceRegistry, url: str, *, limit: int,
) -> tuple[bytes, str, dict[str, str], str]:
    """Fetch one allowlisted URL without inheriting workstation proxy settings.

    Some official sites currently redirect their own HTTPS URL to HTTP. A
    downgrade is accepted only for the exact same public hostname after an
    HTTPS request; arbitrary HTTP source entries and cross-host downgrades stay
    forbidden.
    """
    _validate_source_url(url, source.domain)
    headers = {"User-Agent": "AI-Teaching-Authority-Discovery/1.0"}
    current_url = url
    original_host = (urlparse(url).hostname or "").lower()
    downgraded = False
    transient_errors = (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError)
    with httpx.Client(timeout=25, follow_redirects=False, headers=headers, trust_env=False) as client:
        for redirect_count in range(6):
            for attempt in range(3):
                try:
                    with client.stream("GET", current_url) as response:
                        if response.is_redirect and response.headers.get("location"):
                            target = urljoin(current_url, response.headers["location"])
                            target_parsed = urlparse(target)
                            if target_parsed.scheme == "http":
                                if (target_parsed.hostname or "").lower() != original_host:
                                    raise HTTPException(status_code=400, detail="权威来源禁止跨域降级到 HTTP")
                                downgraded = True
                            _validate_source_url(target, source.domain, allow_http=downgraded)
                            current_url = target
                            break
                        if response.status_code >= 400:
                            if response.status_code in {408, 425, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524} and attempt < 2:
                                time.sleep(0.6 * (attempt + 1))
                                continue
                            raise HTTPException(
                                status_code=400, detail=f"权威原文访问失败（HTTP {response.status_code}）",
                            )
                        chunks: list[bytes] = []
                        size = 0
                        for chunk in response.iter_bytes():
                            size += len(chunk)
                            if size > limit:
                                raise HTTPException(status_code=413, detail="权威原文超过系统允许的资料大小")
                            chunks.append(chunk)
                        return b"".join(chunks), str(response.url), dict(response.headers), response.encoding or "utf-8"
                except transient_errors:
                    if attempt == 2:
                        raise
                    time.sleep(0.4 * (attempt + 1))
            else:
                continue
            # A redirect updates current_url and exits the retry loop.
            continue
    raise HTTPException(status_code=400, detail="权威来源重定向次数过多")


def _read_listing(source: AuthoritySourceRegistry) -> list[tuple[str, str]]:
    body, final_url, response_headers, encoding = _fetch_source_bytes(
        source, source.entry_url, limit=5 * 1024 * 1024,
    )
    content_type = response_headers.get("content-type", "").lower()
    text = body.decode(encoding, errors="replace")
    if source.adapter_type in {"rss", "sitemap"} or "xml" in content_type or text.lstrip().startswith("<rss"):
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            raise RuntimeError("来源 XML 解析失败") from exc
        items: list[tuple[str, str]] = []
        for item in root.iter():
            tag = item.tag.rsplit("}", 1)[-1].lower()
            if tag not in {"item", "url"}:
                continue
            values = {child.tag.rsplit("}", 1)[-1].lower(): (child.text or "").strip() for child in item}
            link = values.get("link") or values.get("loc")
            if link:
                items.append((link, values.get("title", "")))
        return items
    return get_source_adapter(source.domain).parse_listing(text, final_url)


def _fetch_source_article(
    source: AuthoritySourceRegistry, url: str,
) -> tuple[str, str, str | None, str | None, date | None, str]:
    """Fetch and parse a detail page with its registered source adapter."""
    limit = settings.max_upload_size_mb * 1024 * 1024
    body, final_url, response_headers, encoding = _fetch_source_bytes(source, url, limit=limit)
    content_type = response_headers.get("content-type", "").lower()
    raw = body.decode(encoding, errors="replace")
    adapter = get_source_adapter(source.domain)
    if "html" in content_type or "<html" in raw[:1000].lower():
        parsed = adapter.parse_article(raw)
        content = parsed.content
        title = parsed.title
        publisher = parsed.publisher
        published_date = parsed.published_date
        parser_version = parsed.parser_version
    else:
        content = raw.strip()
        title = publisher = published_date = None
        parser_version = "authority-plain-text-v1"
    if len(re.sub(r"\s+", "", content)) < 80:
        raise HTTPException(status_code=400, detail="未能从权威网页提取有效正文")
    return content, final_url, title, publisher, published_date, parser_version


def _candidate_links(source: AuthoritySourceRegistry, keywords: list[str]) -> list[tuple[str, str]]:
    matched: list[tuple[str, str]] = []
    fallback: list[tuple[str, str]] = []
    seen: set[str] = set()
    for href, title in _read_listing(source):
        absolute = urljoin(source.entry_url, href)
        parsed = urlparse(absolute)
        if not _domain_matches(parsed.hostname, source.domain) or parsed.scheme not in {"http", "https"}:
            continue
        # Keep stored and queued URLs on HTTPS. The fetcher may follow a
        # same-host downgrade only when the official server explicitly sends it.
        if parsed.scheme == "http":
            absolute = urlunparse(("https", parsed.netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))
        canonical = _canonical_url(absolute)
        if canonical in seen:
            continue
        seen.add(canonical)
        target = matched if _topic_match(title, absolute, keywords) else fallback
        target.append((absolute, title))
    # 栏目标题常被截断或写成“全文”，不能在读取正文前直接排除；
    # 但仍让标题命中的线索优先，最终相关性由正文二次校验。
    limit = max(1, min(100, int(settings.authority_discovery_max_links_per_source)))
    return [*matched, *fallback][:limit]


def _now() -> datetime:
    return datetime.utcnow()


_job_creation_lock = Lock()


class AuthorityDiscoveryService:
    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def ensure_default_sources(db: Session) -> list[AuthoritySourceRegistry]:
        existing = {item.domain for item in db.scalars(select(AuthoritySourceRegistry)).all()}
        for payload in DEFAULT_SOURCES:
            if payload["domain"] not in existing:
                db.add(AuthoritySourceRegistry(**payload))
        db.commit()
        return list(db.scalars(select(AuthoritySourceRegistry).order_by(AuthoritySourceRegistry.source_level, AuthoritySourceRegistry.id)).all())

    def list_sources(self) -> list[AuthoritySourceRegistry]:
        return self.ensure_default_sources(self.db)

    def create_source(self, payload: AuthoritySourceCreate) -> AuthoritySourceRegistry:
        _validate_source_url(payload.entry_url, payload.domain)
        if self.db.scalar(select(AuthoritySourceRegistry).where(AuthoritySourceRegistry.domain == payload.domain)):
            raise HTTPException(status_code=409, detail="该白名单域名已经存在")
        source = AuthoritySourceRegistry(**payload.model_dump())
        self.db.add(source)
        self.db.commit()
        self.db.refresh(source)
        return source

    def update_source(self, source_id: int, payload: AuthoritySourceUpdate) -> AuthoritySourceRegistry:
        source = self.db.get(AuthoritySourceRegistry, source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="权威来源不存在")
        values = payload.model_dump(exclude_unset=True)
        if "entry_url" in values:
            _validate_source_url(values["entry_url"], source.domain)
        for key, value in values.items():
            setattr(source, key, value)
        self.db.commit()
        self.db.refresh(source)
        return source

    def create_job(self, user: User, payload: DiscoveryJobCreate, trigger_type: str = "manual") -> DiscoveryJob:
        if payload.start_date and payload.end_date and payload.start_date > payload.end_date:
            raise HTTPException(status_code=400, detail="检索开始日期不能晚于结束日期")
        sources = self.list_sources()
        selected = set(payload.source_ids)
        if selected:
            sources = [item for item in sources if item.id in selected]
            if len(sources) != len(selected):
                raise HTTPException(status_code=400, detail="包含不存在或未配置的来源")
        sources = [item for item in sources if item.is_enabled]
        if not sources:
            raise HTTPException(status_code=400, detail="没有启用的权威来源")
        keywords = list(dict.fromkeys([item.strip() for item in payload.keywords if item.strip()]))[:30]
        if payload.query_text and not keywords:
            keywords = [item for item in re.split(r"[，,、;；\s]+", payload.query_text) if item][:30]
        # 将“检查队列/冷却时间”和“创建任务”放在同一进程锁内，避免用户连续点击时
        # 两个请求同时通过检查并各自创建一条相同任务。
        with _job_creation_lock:
            pending_total = self.db.scalar(select(func.count(DiscoveryJob.id)).where(
                DiscoveryJob.status.in_(["queued", "running"]),
            )) or 0
            queue_limit = max(1, int(settings.authority_discovery_max_queued))
            running_limit = max(1, min(3, int(settings.authority_discovery_max_running)))
            if pending_total >= queue_limit + running_limit:
                raise HTTPException(status_code=429, detail=f"发现任务队列已满（最多排队 {queue_limit} 个），请稍后再试")
            if trigger_type == "manual" and settings.authority_discovery_cooldown_minutes > 0:
                cutoff = _now() - timedelta(minutes=settings.authority_discovery_cooldown_minutes)
                normalized_query = (payload.query_text or "").strip()
                normalized_sources = sorted(item.id for item in sources)
                recent_jobs = list(self.db.scalars(select(DiscoveryJob).where(
                    DiscoveryJob.created_by == user.id,
                    DiscoveryJob.trigger_type == "manual",
                    DiscoveryJob.created_time >= cutoff,
                ).order_by(DiscoveryJob.created_time.desc()).limit(50)).all())
                for recent in recent_jobs:
                    if ((recent.query_text or "").strip() == normalized_query
                            and sorted(recent.source_ids or []) == normalized_sources
                            and sorted(recent.keywords or []) == sorted(keywords)
                            and recent.start_date == payload.start_date
                            and recent.end_date == payload.end_date):
                        raise HTTPException(
                            status_code=409,
                            detail=f"相同发现任务在冷却期内已创建（任务 #{recent.id}），请查看任务进度",
                        )
            job = DiscoveryJob(
                created_by=user.id, trigger_type=trigger_type, query_text=payload.query_text,
                keywords=keywords, start_date=payload.start_date, end_date=payload.end_date,
                source_ids=[item.id for item in sources], total_sources=len(sources),
            )
            self.db.add(job)
            self.db.commit()
            self.db.refresh(job)
        return job

    def list_jobs(self, limit: int = 30) -> list[DiscoveryJob]:
        return list(self.db.scalars(select(DiscoveryJob).order_by(DiscoveryJob.created_time.desc()).limit(limit)).all())

    def require_job(self, job_id: int) -> DiscoveryJob:
        job = self.db.get(DiscoveryJob, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="发现任务不存在")
        return job

    def cancel_job(self, job_id: int) -> DiscoveryJob:
        job = self.require_job(job_id)
        if job.status not in {"queued", "running"}:
            raise HTTPException(status_code=409, detail="只有排队中或运行中的任务可以停止")
        job.status = "cancelled"
        job.progress_stage = "已由管理员停止"
        job.finished_time = _now()
        self.db.commit(); self.db.refresh(job)
        return job

    def delete_job(self, job_id: int) -> int:
        job = self.require_job(job_id)
        if job.status in {"queued", "running"}:
            raise HTTPException(status_code=409, detail="运行中或排队中的任务不能删除，请先停止任务")
        self.db.execute(update(MaterialCandidate).where(
            MaterialCandidate.discovery_job_id == job.id,
        ).values(discovery_job_id=None))
        self.db.delete(job)
        self.db.commit()
        return job_id

    def _normalize_pending_candidates(self) -> int:
        threshold = float(settings.authority_discovery_min_association_score)
        relevance_threshold = float(settings.authority_discovery_min_relevance_score)
        low_association = list(self.db.scalars(select(MaterialCandidate).where(
            MaterialCandidate.status == "pending_review",
            or_(
                MaterialCandidate.association_confidence < threshold,
                and_(
                    MaterialCandidate.relevance_score > 0,
                    MaterialCandidate.relevance_score < relevance_threshold,
                ),
            ),
        )).all())
        if low_association:
            notifications = NotificationService(self.db)
            for candidate in low_association:
                candidate.status = "filtered"
                if 0 < candidate.relevance_score < relevance_threshold:
                    candidate.analysis_reason = (
                        f"主题相关度 {candidate.relevance_score:.0%} 低于审核阈值 {relevance_threshold:.0%}，已自动过滤。"
                    )
                else:
                    candidate.analysis_reason = (
                        f"教材关联度 {candidate.association_confidence:.0%} 低于审核阈值 {threshold:.0%}，已自动过滤。"
                    )
                notifications.resolve_candidate_review_notifications(candidate.id, commit=False)
            self.db.commit()
        return len(low_association)

    def list_candidates(self, *, status: str | None = None, source_level: str | None = None, limit: int = 100) -> list[MaterialCandidate]:
        self._normalize_pending_candidates()
        query = select(MaterialCandidate).order_by(MaterialCandidate.importance_score.desc(), MaterialCandidate.created_time.desc())
        if status:
            query = query.where(MaterialCandidate.status == status)
        if source_level:
            query = query.where(MaterialCandidate.source_level == source_level)
        return list(self.db.scalars(query.limit(limit)).all())

    def candidate_decision_summary(self) -> dict[str, int]:
        self._normalize_pending_candidates()
        counts = {
            status: int(self.db.scalar(select(func.count(MaterialCandidate.id)).where(
                MaterialCandidate.status == status,
            )) or 0)
            for status in ("pending_review", "observed", "filtered")
        }
        high_priority = int(self.db.scalar(select(func.count(MaterialCandidate.id)).where(
            MaterialCandidate.status == "pending_review",
            or_(MaterialCandidate.importance_level == "high", MaterialCandidate.source_level == "A"),
        )) or 0)
        return {
            "pending_review": counts["pending_review"],
            "high_priority": high_priority,
            "observed": counts["observed"],
            "filtered": counts["filtered"],
        }

    def _same_candidate_topic(self, left: MaterialCandidate, right: MaterialCandidate) -> bool:
        left_chapters = set(left.suggested_chapter_ids or [])
        if not left_chapters.intersection(right.suggested_chapter_ids or []):
            return False
        if left.published_date and right.published_date:
            if abs((left.published_date - right.published_date).days) > 120:
                return False
        left_grams, right_grams = self._grams(left.title), self._grams(right.title)
        return len(left_grams & right_grams) / max(1, len(left_grams | right_grams)) >= 0.30

    def candidate_topic_groups(self) -> list[dict]:
        """Conservatively group pending candidates that describe the same textbook topic."""
        candidates = self.list_candidates(status="pending_review", limit=500)
        components: list[list[MaterialCandidate]] = []
        for candidate in candidates:
            # Complete-link grouping avoids transitive chains that can merge unrelated endpoints.
            matching = next((group for group in components if all(
                self._same_candidate_topic(candidate, member) for member in group
            )), None)
            if matching is None:
                components.append([candidate])
            else:
                matching.append(candidate)
        source_rank = {"A": 0, "B": 1, "C": 2, "D": 3}
        groups: list[dict] = []
        for members in components:
            if len(members) < 2:
                continue
            members.sort(key=lambda item: (
                source_rank.get(item.source_level, 9),
                -float(item.importance_score or 0),
                -float(item.association_confidence or 0),
                -(item.published_date.toordinal() if item.published_date else 0),
                item.id,
            ))
            primary = members[0]
            ids = sorted(item.id for item in members)
            digest = hashlib.sha1(",".join(map(str, ids)).encode("ascii")).hexdigest()[:12]
            groups.append({
                "group_key": f"topic-{digest}",
                "title": primary.title,
                "primary_candidate_id": primary.id,
                "candidate_ids": ids,
                "member_count": len(members),
                "suggested_course_ids": sorted({course_id for item in members for course_id in (item.suggested_course_ids or [])}),
                "suggested_chapter_ids": sorted({chapter_id for item in members for chapter_id in (item.suggested_chapter_ids or [])}),
                "reason": "共享教材专题且标题表述高度相近；已按来源等级、重要度和关联置信度推荐主材料。",
                "members": [{
                    "id": item.id,
                    "title": item.title,
                    "publisher": item.publisher,
                    "source_level": item.source_level,
                    "published_date": item.published_date,
                    "importance_score": item.importance_score,
                    "association_confidence": item.association_confidence,
                } for item in members],
            })
        groups.sort(key=lambda item: (-item["member_count"], item["primary_candidate_id"]))
        return groups

    def batch_candidates(self, user: User, payload: CandidateBatchAction) -> int:
        candidate_ids = list(dict.fromkeys(payload.candidate_ids))
        candidates = list(self.db.scalars(select(MaterialCandidate).where(
            MaterialCandidate.id.in_(candidate_ids),
        )).all())
        if len(candidates) != len(candidate_ids):
            raise HTTPException(status_code=400, detail="批量操作包含不存在的候选材料")
        if payload.action in {"reject", "observe", "duplicate"}:
            invalid = [item for item in candidates if item.status not in {"pending_review", "fetched", "analyzed"}]
            if invalid:
                raise HTTPException(status_code=409, detail="批量审核只适用于尚未处理的候选材料")
            now = _now()
            for candidate in candidates:
                candidate.status = {
                    "reject": "rejected", "observe": "observed", "duplicate": "duplicate",
                }[payload.action]
                candidate.reviewed_by = user.id
                candidate.reviewed_time = now
                candidate.review_notes = payload.note
                NotificationService(self.db).resolve_candidate_review_notifications(candidate.id, commit=False)
            self.db.commit()
            return len(candidates)
        if any(item.status == "published" or item.document_id is not None for item in candidates):
            raise HTTPException(status_code=409, detail="批量删除中包含已发布材料，请改为前往资料中心归档")
        for candidate in candidates:
            self._delete_candidate_records(candidate)
        self.db.commit()
        return len(candidates)

    def require_candidate(self, candidate_id: int) -> MaterialCandidate:
        candidate = self.db.get(MaterialCandidate, candidate_id)
        if candidate is None:
            raise HTTPException(status_code=404, detail="候选材料不存在")
        return candidate

    def delete_candidate(self, candidate_id: int) -> int:
        candidate = self.require_candidate(candidate_id)
        if candidate.status == "published" or candidate.document_id is not None:
            raise HTTPException(status_code=409, detail="已发布材料不能从候选池删除，请前往资料中心归档")
        self._delete_candidate_records(candidate)
        self.db.commit()
        return candidate_id

    def _delete_candidate_records(self, candidate: MaterialCandidate) -> None:
        NotificationService(self.db).resolve_candidate_review_notifications(candidate.id, commit=False)
        change_ids = list(self.db.scalars(select(PolicyChange.id).where(
            PolicyChange.candidate_id == candidate.id,
        )).all())
        if change_ids:
            self.db.execute(update(TeachingNotification).where(
                TeachingNotification.policy_change_id.in_(change_ids),
            ).values(policy_change_id=None))
        self.db.execute(delete(PolicyChange).where(PolicyChange.candidate_id == candidate.id))
        self.db.execute(delete(MaterialSnapshot).where(MaterialSnapshot.candidate_id == candidate.id))
        self.db.delete(candidate)

    def snapshots(self, candidate_id: int) -> list[MaterialSnapshot]:
        return list(self.db.scalars(select(MaterialSnapshot).where(
            MaterialSnapshot.candidate_id == candidate_id
        ).order_by(MaterialSnapshot.fetched_time.desc())).all())

    def review_candidate(self, candidate_id: int, user: User, payload: CandidateReview) -> MaterialCandidate:
        candidate = self.require_candidate(candidate_id)
        if candidate.status not in {"pending_review", "fetched", "analyzed"}:
            raise HTTPException(status_code=409, detail="当前候选材料状态不允许审核")
        candidate.reviewed_by = user.id
        candidate.reviewed_time = _now()
        candidate.review_notes = payload.review_notes
        if payload.action == "reject":
            candidate.status = "rejected"
            NotificationService(self.db).resolve_candidate_review_notifications(candidate.id, commit=False)
            self.db.commit()
            return candidate
        if payload.action == "duplicate":
            candidate.status = "duplicate"
            NotificationService(self.db).resolve_candidate_review_notifications(candidate.id, commit=False)
            self.db.commit()
            return candidate
        if not payload.course_ids and not payload.chapter_ids:
            raise HTTPException(status_code=400, detail="发布中央材料前至少选择一本教材或一个专题")
        snapshot = self.db.scalar(select(MaterialSnapshot).where(
            MaterialSnapshot.candidate_id == candidate.id
        ).order_by(MaterialSnapshot.fetched_time.desc()))
        if snapshot is None:
            raise HTTPException(status_code=409, detail="候选材料没有可发布的正文快照")
        title = (payload.source_title or candidate.title).strip()
        publisher = (payload.publisher or candidate.publisher or "").strip()
        published_date = payload.published_date or candidate.published_date
        if not publisher or not published_date:
            raise HTTPException(status_code=400, detail="发布前请补全发布机构和发布日期")
        document = MaterialCenterService(self.db).ingest_file(
            user, material_type="central", filename=f"authority-{candidate.id}.md",
            content=snapshot.content.encode("utf-8"), source_title=title, publisher=publisher,
            published_date=published_date, applicable_scope=payload.applicable_scope,
            version_label=None, supersedes_document_id=None, access_policy="full_preview",
            course_ids=payload.course_ids, chapter_ids=payload.chapter_ids, class_ids=[],
            knowledge_tags=payload.knowledge_tags, source_url=candidate.source_url,
            snapshot_time=snapshot.fetched_time,
        )
        MaterialCenterService(self.db).replace_scopes(
            document, user, course_ids=payload.course_ids, chapter_ids=payload.chapter_ids,
            class_ids=[], knowledge_tags=payload.knowledge_tags, confirmed=True,
        )
        MaterialCenterService(self.db).publish(document.id, user)
        candidate.status = "published"
        candidate.document_id = document.id
        candidate.course_ids = list(dict.fromkeys(payload.course_ids))
        candidate.chapter_ids = list(dict.fromkeys(payload.chapter_ids))
        candidate.knowledge_tags = list(dict.fromkeys(payload.knowledge_tags))
        NotificationService(self.db).resolve_candidate_review_notifications(candidate.id, commit=False)
        self.db.commit()
        self.db.refresh(candidate)
        # 候选材料发布后，继续处理此前已确认但等待发布的政策变化。
        self._sync_candidate_changes(candidate.id)
        return candidate

    # ---- 第二阶段：教材关联与原文差异证据 ----
    @staticmethod
    def _compact(value: str) -> str:
        return re.sub(r"\s+", "", value or "").strip()

    @classmethod
    def _grams(cls, value: str) -> set[str]:
        compact = cls._compact(value)
        return {compact[index:index + 2] for index in range(max(0, len(compact) - 1))}

    @classmethod
    def _search_tokens(cls, value: str) -> list[str]:
        """面向中文教材的轻量检索分词；不依赖额外分词服务。"""
        tokens: list[str] = []
        for part in re.findall(r"[\u4e00-\u9fff]+|[A-Za-z0-9_-]+", (value or "").lower()):
            if re.fullmatch(r"[\u4e00-\u9fff]+", part):
                tokens.extend(part[index:index + 2] for index in range(max(1, len(part) - 1)))
                if 2 <= len(part) <= 12:
                    tokens.append(part)
            elif len(part) > 1:
                tokens.append(part)
        return tokens

    @classmethod
    def _bm25(cls, query: str, documents: list[str]) -> list[float]:
        if not documents:
            return []
        query_terms = cls._search_tokens(query)
        tokenized = [cls._search_tokens(document) for document in documents]
        if not query_terms or not any(tokenized):
            return [0.0] * len(documents)
        document_frequency: Counter[str] = Counter()
        for tokens in tokenized:
            document_frequency.update(set(tokens))
        average_length = sum(len(tokens) for tokens in tokenized) / max(1, len(tokenized))
        scores: list[float] = []
        for tokens in tokenized:
            frequencies = Counter(tokens)
            score = 0.0
            for term in query_terms:
                frequency = frequencies.get(term, 0)
                if not frequency:
                    continue
                inverse = math.log(1 + (len(tokenized) - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5))
                denominator = frequency + 1.5 * (1 - 0.75 + 0.75 * len(tokens) / max(1, average_length))
                score += inverse * frequency * 2.5 / denominator
            scores.append(score)
        maximum = max(scores, default=0)
        return [score / maximum if maximum else 0.0 for score in scores]

    @classmethod
    def _paragraphs(cls, value: str) -> list[str]:
        chunks = re.split(r"\n+|(?<=[。！？；])\s*", value or "")
        return [" ".join(chunk.split()).strip()[:1200] for chunk in chunks if len(cls._compact(chunk)) >= 12]

    def _candidate_text(self, candidate: MaterialCandidate) -> str:
        snapshot = self.db.scalar(select(MaterialSnapshot).where(
            MaterialSnapshot.candidate_id == candidate.id,
        ).order_by(MaterialSnapshot.fetched_time.desc()))
        return snapshot.content if snapshot else (candidate.content_preview or "")

    def _document_text(self, document: KnowledgeDocument) -> str:
        path = Path(document.stored_path)
        if path.exists() and document.source_type in {"txt", "md", "markdown"}:
            try:
                return path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass
        chunks = list(self.db.scalars(select(KnowledgeChunk.content).where(
            KnowledgeChunk.document_id == document.id,
        ).order_by(KnowledgeChunk.chunk_index).limit(80)).all())
        if chunks:
            return "\n".join(chunks)
        return "\n".join(self.db.scalars(select(DocumentPage.text).where(
            DocumentPage.document_id == document.id,
        ).order_by(DocumentPage.pdf_page).limit(120)).all())

    def _semantic_association_review(
        self,
        source: str,
        candidates: list[tuple[float, Course, Chapter]],
    ) -> tuple[list[int], float, str] | None:
        """只对召回集合做受约束复核；失败时由确定性混合检索兜底。"""
        runtime = AiProviderConfigService.resolve(self.db)
        if settings.ai_mock_mode or not runtime.api_key or not candidates:
            return None
        options = [
            {
                "chapter_id": chapter.id,
                "course": course.name,
                "chapter": chapter.title,
                "retrieval_score": round(score, 4),
                "excerpt": (chapter.content or "")[:900],
            }
            for score, course, chapter in candidates[:8]
        ]
        prompt = ChatPromptTemplate.from_messages([
            ("system", "你负责核验权威资料与高校思政教材专题的真实关联。只能从候选 chapter_id 中选择，不得创造编号；证据不足可返回空数组。只输出 JSON。"),
            ("human", "权威资料：\n{source}\n\n候选专题：\n{options}\n\n输出格式：{{\"chapter_ids\":[1],\"confidence\":0.8,\"reason\":\"简短说明实际关联点\"}}"),
        ])
        try:
            model, _ = build_chat_model(
                feature="material_association",
                db=self.db,
                temperature=0,
                timeout=runtime.timeout_seconds,
            )
            raw = clean_model_text((prompt | model).invoke({
                "source": source[:7000], "options": json.dumps(options, ensure_ascii=False),
            }).content)
            payload = json.loads(re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.I).strip())
            allowed = {chapter.id for _, _, chapter in candidates[:8]}
            chapter_ids = [int(item) for item in payload.get("chapter_ids", []) if int(item) in allowed]
            confidence = max(0.0, min(1.0, float(payload.get("confidence", 0))))
            reason = str(payload.get("reason", "")).strip()[:1000]
            return list(dict.fromkeys(chapter_ids)), confidence, reason
        except Exception:
            return None

    def associate_candidate(self, candidate_id: int) -> MaterialCandidate:
        candidate = self.require_candidate(candidate_id)
        source = f"{candidate.title}\n{self._candidate_text(candidate)}"
        source_compact, source_grams = self._compact(source), self._grams(source)
        rows = list(self.db.execute(select(Chapter, Course).join(Course, Course.id == Chapter.course_id)).all())
        chunk_texts: dict[int, list[str]] = defaultdict(list)
        for chapter_id, content in self.db.execute(
            select(KnowledgeChunk.chapter_id, KnowledgeChunk.content)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .where(
                KnowledgeDocument.material_type == "textbook",
                KnowledgeDocument.is_active.is_(True),
                KnowledgeChunk.chapter_id.is_not(None),
            )
        ).all():
            if chapter_id and content and len(chunk_texts[chapter_id]) < 24:
                chunk_texts[chapter_id].append(content)
        targets = [
            f"{course.name}\n{chapter.title}\n{chapter.content or ''}\n{' '.join(chunk_texts.get(chapter.id, []))}"
            for chapter, course in rows
        ]
        bm25_scores = self._bm25(source[:24000], targets)
        vector_boosts: dict[int, float] = defaultdict(float)
        # 向量服务不可用时自动退回 BM25/原文规则，不让后台发现任务整体失败。
        for course_id in dict.fromkeys(course.id for _, course in rows):
            try:
                for result in retrieve(source[:3000], course_id=course_id, chapter_id=None, top_k=10):
                    chapter_id = result.metadata.get("chapter_id")
                    if isinstance(chapter_id, int):
                        vector_boosts[chapter_id] = max(vector_boosts[chapter_id], float(result.score))
            except Exception:
                continue
        scored: list[tuple[float, Course, Chapter]] = []
        for index, (chapter, course) in enumerate(rows):
            target = targets[index]
            target_grams = self._grams(target[:18000])
            overlap = len(source_grams & target_grams) / max(1, min(len(source_grams), len(target_grams)))
            title_hit = 0.22 if self._compact(chapter.title) in source_compact else 0
            course_hit = 0.08 if self._compact(course.name) in source_compact else 0
            score = bm25_scores[index] * 0.44 + overlap * 0.22 + vector_boosts[chapter.id] * 0.24 + title_hit + course_hit
            scored.append((min(1.0, score), course, chapter))
        scored.sort(key=lambda item: item[0], reverse=True)
        selected = [item for item in scored if item[0] >= 0.12][:8] or scored[:3]
        semantic = self._semantic_association_review(source, selected)
        semantic_reason = ""
        if semantic is not None:
            semantic_ids, semantic_confidence, semantic_reason = semantic
            if semantic_ids:
                by_id = {item[2].id: item for item in selected}
                selected = [by_id[item] for item in semantic_ids if item in by_id]
                candidate.association_confidence = round(semantic_confidence, 4)
        candidate.suggested_course_ids = list(dict.fromkeys(item[1].id for item in selected))
        candidate.suggested_chapter_ids = list(dict.fromkeys(item[2].id for item in selected))
        candidate.suggested_knowledge_tags = re.findall(r"[\u4e00-\u9fff]{2,12}", candidate.title)[:8]
        if semantic is None or not semantic[0]:
            candidate.association_confidence = round(min(1.0, (selected[0][0] if selected else 0) * 1.25), 4)
        importance, importance_level, importance_reason = _importance_score(
            source_level=candidate.source_level,
            relevance=candidate.relevance_score,
            association=candidate.association_confidence,
            freshness=candidate.freshness_score,
            title=candidate.title,
            content=source,
            novelty=candidate.novelty_score,
        )
        candidate.importance_score = importance
        candidate.importance_level = importance_level
        candidate.importance_reason = importance_reason
        labels = [f"{course.name}·{chapter.title}（{score:.0%}）" for score, course, chapter in selected[:5]]
        method = "混合召回并经大模型受约束复核" if semantic is not None and semantic[0] else "教材全文 BM25、向量召回、标题命中与正文重叠的混合评分"
        candidate.association_reason = f"基于{method}，建议范围（仅供管理员确认）：" + ("；".join(labels) if labels else "暂无可匹配专题") + (f"。语义复核说明：{semantic_reason}" if semantic_reason else "")
        self.db.commit(); self.db.refresh(candidate)
        return candidate

    def _reference_sources(self, candidate: MaterialCandidate) -> list[tuple[int | None, int | None, str, str | None, str]]:
        course_ids, chapter_ids = list(candidate.suggested_course_ids or []), list(candidate.suggested_chapter_ids or [])
        output: list[tuple[int | None, int | None, str, str | None, str]] = []
        for chapter in self.db.scalars(select(Chapter).where(Chapter.id.in_(chapter_ids))).all() if chapter_ids else []:
            if chapter.content:
                course = self.db.get(Course, chapter.course_id)
                output.append((None, chapter.id, f"{course.name if course else '教材'}·{chapter.title}", None, chapter.content))
        if course_ids:
            docs = self.db.scalars(select(KnowledgeDocument).outerjoin(
                DocumentCourseScope, DocumentCourseScope.document_id == KnowledgeDocument.id,
            ).where(
                KnowledgeDocument.material_type == "central", KnowledgeDocument.review_status == "published",
                KnowledgeDocument.is_active.is_(True),
                or_(
                    KnowledgeDocument.course_id.in_(course_ids),
                    (DocumentCourseScope.course_id.in_(course_ids) & DocumentCourseScope.confirmed.is_(True)),
                ),
            ).distinct().order_by(KnowledgeDocument.published_date.desc().nullslast()).limit(20)).all()
            for document in docs:
                text = self._document_text(document)
                if text:
                    output.append((document.id, document.chapter_id, document.source_title, document.source_url, text))
        return output

    def detect_policy_changes(self, candidate_id: int) -> list[PolicyChange]:
        candidate = self.require_candidate(candidate_id)
        new_parts = self._paragraphs(self._candidate_text(candidate))
        self.db.execute(delete(PolicyChange).where(PolicyChange.candidate_id == candidate.id, PolicyChange.review_status == "pending"))
        ranked: list[tuple[float, tuple, str, str, float]] = []
        for reference in self._reference_sources(candidate):
            old_parts = self._paragraphs(reference[4])
            for new_part in new_parts:
                if not old_parts:
                    continue
                best = max(old_parts, key=lambda old: SequenceMatcher(None, self._compact(new_part), self._compact(old)).ratio())
                ratio = SequenceMatcher(None, self._compact(new_part), self._compact(best)).ratio()
                if ratio < 0.92:
                    ranked.append((len(self._compact(new_part)) * (1 - ratio), reference, best, new_part, ratio))
        ranked.sort(key=lambda item: item[0], reverse=True)
        changes: list[PolicyChange] = []
        seen: set[tuple[int | None, int | None, str]] = set()
        for _, reference, old_excerpt, new_excerpt, ratio in ranked:
            old_document_id, old_chapter_id, old_title, old_url, _ = reference
            key = (old_document_id, old_chapter_id, self._compact(new_excerpt)[:160])
            if key in seen:
                continue
            seen.add(key)
            policy_words = ("决定", "意见", "通知", "报告", "部署", "规划", "实施", "会议", "讲话")
            high = candidate.source_level == "A" and (any(word in candidate.title for word in policy_words) or candidate.relevance_score >= 0.55)
            change_type = "权威解释更新" if "解读" in candidate.title else ("重要会议精神" if any(word in candidate.title for word in ("会议", "讲话", "精神", "部署")) else ("新增重要表述" if ratio < 0.35 else "原有要求进一步强化"))
            change = PolicyChange(
                candidate_id=candidate.id, old_document_id=old_document_id, old_chapter_id=old_chapter_id,
                change_type=change_type, old_source_title=old_title, old_source_url=old_url,
                new_source_title=candidate.title, new_source_url=candidate.source_url,
                old_excerpt=old_excerpt[:4000], new_excerpt=new_excerpt[:4000], similarity_score=round(ratio, 4),
                importance="high" if high or len(new_excerpt) > 180 else ("medium" if ratio < 0.5 else "low"),
                alert_recommended=high or len(new_excerpt) > 180, review_status="pending",
                affected_course_ids=list(candidate.suggested_course_ids or []), affected_chapter_ids=list(candidate.suggested_chapter_ids or []),
                ai_explanation=f"已将新材料与“{old_title}”的原文句段进行确定性比对；请以左右两侧原文为准，系统没有依据之外的推断。",
            )
            self.db.add(change); changes.append(change)
            if len(changes) >= 3:
                break
        self.db.commit()
        return changes

    def analyze_candidate(self, candidate_id: int) -> MaterialCandidate:
        candidate = self.associate_candidate(candidate_id)
        changes = self.detect_policy_changes(candidate.id)
        candidate.status = "pending_review"
        candidate.analysis_reason = f"{candidate.association_reason or ''} 已生成 {len(changes)} 条新旧原文差异证据，等待管理员确认。"[:4000]
        self.db.commit(); self.db.refresh(candidate)
        NotificationService(self.db).create_candidate_review_notifications(candidate, evidence_count=len(changes))
        return candidate

    def list_changes(self, *, status: str | None = None, importance: str | None = None, candidate_id: int | None = None, limit: int = 100) -> list[PolicyChange]:
        query = select(PolicyChange).order_by(PolicyChange.created_time.desc())
        if status: query = query.where(PolicyChange.review_status == status)
        if importance: query = query.where(PolicyChange.importance == importance)
        if candidate_id: query = query.where(PolicyChange.candidate_id == candidate_id)
        return list(self.db.scalars(query.limit(limit)).all())

    def require_change(self, change_id: int) -> PolicyChange:
        change = self.db.get(PolicyChange, change_id)
        if change is None: raise HTTPException(status_code=404, detail="政策变化证据不存在")
        return change

    def review_change(self, change_id: int, user: User, action: str, note: str | None = None) -> PolicyChange:
        change = self.require_change(change_id)
        change.review_status = {"confirm": "confirmed", "dismiss": "dismissed", "observe": "observed"}[action]
        change.reviewed_by, change.reviewed_time = user.id, _now()
        if note: change.ai_explanation = f"{change.ai_explanation or ''}\n管理员备注：{note}"[:8000]
        self.db.commit(); self.db.refresh(change)
        if action != "confirm":
            change.kb_sync_status = "not_required"
            self.db.commit(); self.db.refresh(change)
        else:
            change = self._sync_confirmed_change(change.id)
        return change

    def _sync_candidate_changes(self, candidate_id: int) -> list[PolicyChange]:
        changes = list(self.db.scalars(select(PolicyChange).where(
            PolicyChange.candidate_id == candidate_id,
            PolicyChange.review_status == "confirmed",
        )).all())
        output: list[PolicyChange] = []
        for change in changes:
            output.append(self._sync_confirmed_change(change.id))
        return output

    def _sync_confirmed_change(self, change_id: int) -> PolicyChange:
        """将管理员确认的变化同步到当前向量配置，并在成功后通知教师。"""
        change = self.require_change(change_id)
        if change.review_status != "confirmed":
            return change
        candidate = self.db.get(MaterialCandidate, change.candidate_id)
        if candidate is None:
            change.kb_sync_status = "failed"
            change.kb_error = "候选材料不存在"
            self.db.commit(); self.db.refresh(change)
            return change
        document = self.db.get(KnowledgeDocument, candidate.document_id) if candidate.document_id else None
        if candidate.status != "published" or document is None:
            change.kb_sync_status = "waiting_publish"
            change.kb_error = None
            self.db.commit(); self.db.refresh(change)
            return change
        try:
            # 统一通过 KnowledgeService 使用当前 Embedding profile，避免旧向量维度混入活动集合。
            KnowledgeService(self.db).reindex(document.id)
        except Exception as exc:
            self.db.rollback()
            change = self.require_change(change_id)
            change.kb_sync_status = "failed"
            change.kb_error = str(exc)[:2000]
            self.db.commit(); self.db.refresh(change)
            return change
        change = self.require_change(change_id)
        change.kb_sync_status = "synced"
        change.kb_synced_time = _now()
        change.kb_error = None
        self.db.commit(); self.db.refresh(change)
        NotificationService(self.db).create_policy_change_notifications(change)
        self.db.refresh(change)
        return change


_worker_slots = BoundedSemaphore(max(1, min(3, settings.material_batch_worker_concurrency)))
_active_job_ids: set[int] = set()
_active_lock = Lock()
_dispatcher_started = False
_dispatcher_lock = Lock()
_dispatcher_event = Event()
_dispatcher_bind: Engine | None = None
_dispatcher_stop = Event()


def schedule_discovery_job(job_id: int, bind: Engine) -> None:
    """唤醒进程内受控调度器，不为每个请求创建一个等待线程。"""
    _ensure_dispatcher(bind)
    with _active_lock:
        if job_id in _active_job_ids:
            return
    _dispatcher_event.set()


def _ensure_dispatcher(bind: Engine) -> None:
    global _dispatcher_started, _dispatcher_bind
    with _dispatcher_lock:
        _dispatcher_bind = bind
        if not _dispatcher_started:
            _dispatcher_started = True
            Thread(target=_discovery_dispatch_loop, daemon=True, name="authority-discovery-dispatcher").start()
    _dispatcher_event.set()


def _dispatch_available_jobs() -> None:
    with _dispatcher_lock:
        bind = _dispatcher_bind
    if bind is None:
        return
    max_running = max(1, min(3, int(settings.authority_discovery_max_running)))
    with _active_lock:
        capacity = max_running - len(_active_job_ids)
    if capacity <= 0:
        return
    factory = sessionmaker(bind=bind, autoflush=False, expire_on_commit=False)
    with factory() as db:
        queued_ids = list(db.scalars(select(DiscoveryJob.id).where(
            DiscoveryJob.status == "queued",
        ).order_by(DiscoveryJob.created_time.asc()).limit(capacity * 2)).all())
    for job_id in queued_ids:
        with _active_lock:
            if len(_active_job_ids) >= max_running or job_id in _active_job_ids:
                continue
            _active_job_ids.add(job_id)
        if not _claim_queued_job(job_id, bind):
            with _active_lock:
                _active_job_ids.discard(job_id)
            continue
        try:
            Thread(target=_run_discovery_job, args=(job_id, bind), daemon=True, name=f"authority-discovery-{job_id}").start()
        except Exception as exc:
            with _active_lock:
                _active_job_ids.discard(job_id)
            _mark_discovery_job_failed(job_id, bind, f"后台执行线程启动失败：{exc}")


def _claim_queued_job(job_id: int, bind: Engine) -> bool:
    """通过数据库条件更新原子认领任务，避免多个 Web 进程重复执行同一任务。"""
    factory = sessionmaker(bind=bind, autoflush=False, expire_on_commit=False)
    with factory() as db:
        result = db.execute(update(DiscoveryJob).where(
            DiscoveryJob.id == job_id,
            DiscoveryJob.status == "queued",
        ).values(
            status="running",
            progress_stage="等待后台执行",
            started_time=_now(),
            finished_time=None,
        ))
        db.commit()
        return result.rowcount == 1


def _mark_discovery_job_failed(job_id: int, bind: Engine, message: str) -> None:
    factory = sessionmaker(bind=bind, autoflush=False, expire_on_commit=False)
    with factory() as db:
        job = db.get(DiscoveryJob, job_id)
        if job and job.status in {"queued", "running"}:
            job.status = "failed"
            job.progress_stage = "执行失败，可重试"
            job.error_message = message[:2000]
            job.finished_time = _now()
            db.commit()


def _discovery_dispatch_loop() -> None:
    while not _dispatcher_stop.is_set():
        try:
            _dispatch_available_jobs()
        except Exception:
            # 调度器异常不能影响 FastAPI 主服务；任务仍会保留在 queued 状态等待下一轮。
            pass
        # 有新任务时 schedule_discovery_job 会立即唤醒；空闲时降低轮询频率，避免无意义的数据库查询。
        _dispatcher_event.wait(5.0)
        _dispatcher_event.clear()


def _run_discovery_job(job_id: int, bind: Engine) -> None:
    try:
        with _worker_slots:
            _process_discovery_job(job_id, bind)
    except Exception as exc:
        # 防止未预期异常让任务永久停在 running；保留失败原因，管理员可从页面重试。
        try:
            _mark_discovery_job_failed(job_id, bind, str(exc))
        except Exception:
            # 记录失败本身不能再次阻塞调度器，下一次重试会重新读取任务状态。
            pass
    finally:
        with _active_lock:
            _active_job_ids.discard(job_id)
        # 立即尝试下一条排队任务，不必等待空闲轮询周期。
        _dispatcher_event.set()


def _process_discovery_job(job_id: int, bind: Engine) -> None:
    factory = sessionmaker(bind=bind, autoflush=False, expire_on_commit=False)
    with factory() as db:
        job = db.get(DiscoveryJob, job_id)
        if job is None:
            return
        if job.status not in {"queued", "running"}:
            return
        job.status = "running"
        job.progress_stage = "读取来源栏目"
        job.started_time = job.started_time or _now()
        db.commit()
        sources = list(db.scalars(select(AuthoritySourceRegistry).where(
            AuthoritySourceRegistry.id.in_(job.source_ids), AuthoritySourceRegistry.is_enabled.is_(True)
        )).all())
        daily_limit = max(1, int(settings.authority_discovery_daily_fetch_limit))
        day_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        daily_fetch_count = db.scalar(select(func.count(MaterialCandidate.id)).where(
            MaterialCandidate.created_time >= day_start,
        )) or 0
        daily_limit_reached = daily_fetch_count >= daily_limit

        for source in sources:
            db.refresh(job)
            if job.status == "cancelled":
                return
            if daily_limit_reached:
                job.progress_stage = "已达到今日抓取上限"
                break
            try:
                if not source.allow_full_text:
                    raise RuntimeError("该来源未授权抓取全文，请在来源管理中确认后启用")
                links = _candidate_links(source, job.keywords)
                job.discovered_count += len(links)
                job.progress_stage = f"抓取 {source.name}"
                db.commit()
            except Exception as exc:
                source.consecutive_failures += 1
                source.last_error = str(exc)[:1000]
                job.failed_count += 1
                summary = f"{source.name}：{str(exc)[:300]}"
                job.error_message = "；".join(filter(None, [job.error_message, summary]))[-1000:]
                job.processed_sources += 1
                db.commit()
                continue
            last_request_time = 0.0
            for source_url, anchor_title in links:
                db.refresh(job)
                if job.status == "cancelled":
                    return
                if daily_fetch_count >= daily_limit:
                    daily_limit_reached = True
                    job.progress_stage = "已达到今日抓取上限"
                    break
                try:
                    wait_interval = max(
                        int(source.request_interval_seconds or 0),
                        int(settings.authority_discovery_request_interval_seconds),
                    )
                    wait_seconds = wait_interval - (time.monotonic() - last_request_time)
                    if last_request_time and wait_seconds > 0:
                        time.sleep(wait_seconds)
                    last_request_time = time.monotonic()
                    content, final_url, title, publisher, published_date, parser_version = _fetch_source_article(
                        source, source_url,
                    )
                    job.fetched_count += 1
                    canonical = _canonical_url(final_url)
                    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
                    existing = db.scalar(select(MaterialCandidate).where(
                        MaterialCandidate.canonical_url == canonical,
                        MaterialCandidate.content_hash == content_hash,
                    ))
                    if existing:
                        job.deduped_count += 1
                        continue
                    title = (title or anchor_title or canonical).strip()[:500]
                    publisher = (publisher or source.name).strip()[:255]
                    extraction_quality = _estimate_content_quality(content)
                    if extraction_quality < float(settings.authority_discovery_min_extraction_quality):
                        job.filtered_count += 1
                        job.extraction_failed_count += 1
                        continue
                    if job.keywords and not _topic_match(title, content[:20000], job.keywords):
                        # 标题未命中时仍会抓取正文复核；正文也不相关才真正排除。
                        job.filtered_count += 1
                        continue
                    if job.start_date and published_date and published_date < job.start_date:
                        job.filtered_count += 1
                        continue
                    if job.end_date and published_date and published_date > job.end_date:
                        job.filtered_count += 1
                        continue
                    relevance, reason = _score(title, content, job.keywords, source.source_level)
                    if job.keywords and relevance < float(settings.authority_discovery_min_relevance_score):
                        job.filtered_count += 1
                        continue
                    freshness = 1.0 if published_date and published_date >= date.today() - timedelta(days=30) else 0.4
                    candidate = MaterialCandidate(
                        discovery_job_id=job.id, source_registry_id=source.id, title=title,
                        source_url=final_url, canonical_url=canonical, publisher=publisher,
                        published_date=published_date, source_level=source.source_level,
                        recommended_material_type="central" if source.source_level in {"A", "B"} else "local",
                        status="pending_review", content_hash=content_hash,
                        content_preview=content[:5000], extraction_quality_score=extraction_quality,
                        relevance_score=relevance, freshness_score=freshness,
                        novelty_score=1.0, analysis_reason=reason,
                    )
                    db.add(candidate)
                    db.flush()
                    db.add(MaterialSnapshot(
                        candidate_id=candidate.id, fetched_url=final_url, content=content,
                        content_hash=content_hash, parser_version=parser_version, fetched_time=_now(),
                    ))
                    db.commit()
                    candidate = db.get(MaterialCandidate, candidate.id)
                    try:
                        job.progress_stage = f"关联教材并对比原文：{title[:18]}"
                        db.commit()
                        discovery_service = AuthorityDiscoveryService(db)
                        discovery_service.associate_candidate(candidate.id)
                        candidate = db.get(MaterialCandidate, candidate.id)
                        if candidate.association_confidence < float(settings.authority_discovery_min_association_score):
                            candidate.status = "filtered"
                            candidate.analysis_reason = f"教材关联度 {candidate.association_confidence:.0%} 低于审核阈值 {settings.authority_discovery_min_association_score:.0%}，已自动过滤。"
                            job.filtered_count += 1
                            db.commit()
                            continue
                        discovery_service.detect_policy_changes(candidate.id)
                        candidate.status = "pending_review"
                        candidate.analysis_reason = f"{candidate.association_reason or reason} 已生成原文差异证据，等待管理员确认。"[:4000]
                        db.commit()
                        NotificationService(db).create_candidate_review_notifications(candidate, evidence_count=len(discovery_service.list_changes(candidate_id=candidate.id)))
                    except Exception as analysis_exc:
                        db.rollback()
                        candidate = db.get(MaterialCandidate, candidate.id)
                        candidate.analysis_reason = f"正文已抓取，自动关联/差异分析失败：{str(analysis_exc)[:800]}"
                        candidate.status = "pending_review"
                    if candidate.status == "pending_review":
                        job.pending_review_count += 1
                    daily_fetch_count += 1
                except Exception as exc:
                    job.failed_count += 1
                    summary = f"{source.name} {source_url}：{str(exc)[:240]}"
                    job.error_message = "；".join(filter(None, [job.error_message, summary]))[-1000:]
                db.commit()
            source.last_success_time = _now()
            source.consecutive_failures = 0
            source.last_error = None
            job.processed_sources += 1
            db.commit()
        handled_count = job.fetched_count + job.filtered_count + job.deduped_count
        job.status = "failed" if job.failed_count and not handled_count else "completed"
        if job.status == "failed":
            job.progress_stage = "执行失败"
        elif job.failed_count:
            job.progress_stage = "部分成功，等待人工审核"
        elif not daily_limit_reached:
            job.progress_stage = "等待人工审核"
        if daily_limit_reached:
            job.error_message = f"已达到每日抓取上限 {daily_limit}，剩余来源将在下一次任务处理"
        job.finished_time = _now()
        db.commit()

def schedule_due_discovery_jobs(bind: Engine) -> int:
    """按来源自己的周期创建后台任务；只读白名单来源，失败不会影响现有任务。"""
    if not settings.authority_discovery_scheduler_enabled:
        return 0
    factory = sessionmaker(bind=bind, autoflush=False, expire_on_commit=False)
    created = 0
    # 与手动任务共享创建锁，避免同一进程中定时器和管理员请求同时突破队列上限。
    with _job_creation_lock:
        with factory() as db:
            admin = db.scalar(select(User).where(User.role == "admin").order_by(User.id))
            if admin is None:
                return 0
            now = _now()
            sources = list(db.scalars(select(AuthoritySourceRegistry).where(
                AuthoritySourceRegistry.is_enabled.is_(True)
            )).all())
            active_jobs = list(db.scalars(select(DiscoveryJob).where(
                DiscoveryJob.status.in_(["queued", "running"]),
                DiscoveryJob.trigger_type == "scheduled",
            )).all())
            active_source_ids = {
                source_id for active_job in active_jobs for source_id in (active_job.source_ids or [])
            }
            pending_total = db.scalar(select(func.count(DiscoveryJob.id)).where(
                DiscoveryJob.status.in_(["queued", "running"]),
            )) or 0
            queue_capacity = max(
                0,
                int(settings.authority_discovery_max_queued)
                + max(1, min(3, int(settings.authority_discovery_max_running)))
                - pending_total,
            )
            job_ids: list[int] = []
            for source in sources:
                if queue_capacity <= 0:
                    break
                if source.id in active_source_ids:
                    continue
                due_at = source.last_success_time
                if due_at and now < due_at + timedelta(minutes=source.fetch_interval_minutes):
                    continue
                job = DiscoveryJob(
                    created_by=admin.id, trigger_type="scheduled", keywords=[],
                    source_ids=[source.id], total_sources=1,
                )
                db.add(job)
                db.flush()
                job_ids.append(job.id)
                created += 1
                queue_capacity -= 1
            db.commit()
    for job_id in job_ids:
        schedule_discovery_job(job_id, bind)
    return created


_scheduler_started = False
_scheduler_lock = Lock()
_scheduler_stop = Event()


def start_discovery_scheduler(bind: Engine) -> None:
    global _scheduler_started
    # 即使关闭定时发现，也恢复服务重启前遗留的 queued/running 任务。
    # 这样页面已提交的后台任务不会因进程重启永久停在 running。
    factory = sessionmaker(bind=bind, autoflush=False, expire_on_commit=False)
    queued_count = 0
    try:
        with factory() as db:
            interrupted = list(db.scalars(select(DiscoveryJob).where(DiscoveryJob.status == "running")).all())
            for job in interrupted:
                job.status = "queued"
                job.progress_stage = "服务重启后重新排队"
                job.started_time = None
                job.error_message = "服务重启前任务未完成，已自动重新排队"
            queued_count = db.scalar(select(func.count(DiscoveryJob.id)).where(DiscoveryJob.status == "queued")) or 0
            if interrupted:
                db.commit()
    except SQLAlchemyError:
        # 数据库迁移落后时，资料发现模块应降级停用，而不是阻断登录、
        # 课程和 AI 等全部后端接口。日志保留明确的迁移提示。
        logger.exception(
            "authority discovery scheduler disabled because database schema is outdated; "
            "run `alembic upgrade head` before enabling discovery"
        )
        return
    if settings.authority_discovery_scheduler_enabled or queued_count:
        _ensure_dispatcher(bind)
        _dispatcher_event.set()
    if not settings.authority_discovery_scheduler_enabled:
        return
    with _scheduler_lock:
        if _scheduler_started:
            return
        _scheduler_started = True

    def loop() -> None:
        while not _scheduler_stop.is_set():
            try:
                schedule_due_discovery_jobs(bind)
            except Exception:
                # 调度器异常不能影响 FastAPI 主服务；具体来源错误会留在任务记录中。
                pass
            _scheduler_stop.wait(max(30, settings.authority_discovery_scheduler_poll_seconds))

    Thread(target=loop, daemon=True, name="authority-discovery-scheduler").start()

"""向独立 SQLite 测试库导入教材匹配演示数据。

仅允许写入 app_matching_test.db；可重复执行。
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import delete, select

import app.main  # noqa: F401  # 注册所有 API 依赖的 ORM 模型。
from app.core.config import settings
from app.core.time import utc_now
from app.db.session import SessionLocal
from app.models.authority_discovery import (
    AuthoritySourceRegistry,
    MaterialCandidate,
    MaterialSnapshot,
    PolicyChange,
)
from app.models.chapter import Chapter
from app.models.course import Course
from app.services import authority_discovery_service as discovery_module
from app.services.authority_discovery_service import AuthorityDiscoveryService


COURSE_NAME = "【匹配测试】习近平新时代中国特色社会主义思想概论"
CHAPTERS = [
    (
        "第九章 全面依法治国",
        "全面依法治国是国家治理的一场深刻革命。坚持以习近平法治思想为指导，"
        "坚持依法治国、依法执政、依法行政共同推进，建设中国特色社会主义法治体系。"
        "深入开展法治宣传教育，繁荣发展社会主义法治文化，推动尊法学法守法用法在全社会蔚然成风。",
    ),
    (
        "第十一章 建设巩固国防和强大人民军队",
        "强国必须强军，军强才能国安。坚持党对人民军队的绝对领导，贯彻习近平强军思想，"
        "全面推进国防和军队现代化。加强军事人才队伍建设，提高捕捉战争形态和作战方式变化的能力，建设世界一流军队。",
    ),
    (
        "第十章 建设社会主义文化强国",
        "文化兴国运兴，文化强民族强。坚定文化自信，坚持马克思主义在意识形态领域的指导地位，"
        "培育和践行社会主义核心价值观，提升国家文化软实力和中华文化影响力。",
    ),
]
CANDIDATES = [
    (
        "law",
        "法治宣传教育第九个五年规划",
        "坚持以习近平法治思想为指导，全面贯彻党的二十大和二十届历次全会精神。"
        "深入开展法治宣传教育，健全法治宣传教育工作体系，繁荣发展社会主义法治文化，"
        "推动习近平法治思想深入人心，以贯彻实施法治宣传教育法为抓手，服务全面依法治国。",
    ),
    (
        "military",
        "高质量推进国防和军队现代化新部署",
        "坚持党对人民军队的绝对领导，深入贯彻习近平强军思想，聚焦实现建军一百年奋斗目标。"
        "加强军事人才队伍建设，加快武器装备现代化，提高捍卫国家主权、安全、发展利益的战略能力。",
    ),
    (
        "unrelated",
        "城市古典音乐会节目单",
        "本场音乐会将演奏小提琴协奏曲和交响曲。请观众按票面座位编号有序入场，演出期间请将手机调至静音模式。",
    ),
]


def _assert_test_database() -> None:
    normalized = settings.database_url.replace("\\", "/")
    if not normalized.startswith("sqlite") or not normalized.endswith("/data/app_matching_test.db"):
        raise RuntimeError("拒绝执行：本脚本只允许写入 backend/data/app_matching_test.db")


def _upsert_course_and_chapters(db) -> tuple[Course, dict[str, Chapter]]:
    course = db.scalar(select(Course).where(Course.name == COURSE_NAME))
    if course is None:
        course = Course(name=COURSE_NAME, description="教材关联算法本地演示数据")
        db.add(course)
        db.flush()
    chapters: dict[str, Chapter] = {}
    for sort_order, (title, content) in enumerate(CHAPTERS, start=1):
        chapter = db.scalar(select(Chapter).where(
            Chapter.course_id == course.id,
            Chapter.title == title,
        ))
        if chapter is None:
            chapter = Chapter(course_id=course.id, title=title)
            db.add(chapter)
        chapter.content = content
        chapter.sort_order = sort_order
        db.flush()
        chapters[title] = chapter
    db.commit()
    return course, chapters


def _replace_candidate(db, source: AuthoritySourceRegistry, key: str, title: str, content: str) -> MaterialCandidate:
    url = f"https://example.invalid/matching-demo/{key}"
    candidate = db.scalar(select(MaterialCandidate).where(MaterialCandidate.canonical_url == url))
    if candidate is not None:
        db.execute(delete(PolicyChange).where(PolicyChange.candidate_id == candidate.id))
        db.execute(delete(MaterialSnapshot).where(MaterialSnapshot.candidate_id == candidate.id))
    else:
        candidate = MaterialCandidate(
            source_registry_id=source.id,
            title=title,
            source_url=url,
            canonical_url=url,
            source_level="A",
        )
        db.add(candidate)
    digest = sha256(content.encode("utf-8")).hexdigest()
    candidate.title = title
    candidate.publisher = "本地匹配测试数据"
    candidate.source_level = "A"
    candidate.recommended_material_type = "central"
    candidate.status = "discovered"
    candidate.content_hash = digest
    candidate.canonical_url_hash = sha256(url.encode("utf-8")).hexdigest()
    candidate.content_preview = content
    candidate.extraction_quality_score = 1.0
    candidate.relevance_score = 0.90 if key != "unrelated" else 0.0
    candidate.freshness_score = 1.0
    candidate.novelty_score = 1.0
    candidate.suggested_course_ids = None
    candidate.suggested_chapter_ids = None
    candidate.association_confidence = 0.0
    db.flush()
    db.add(MaterialSnapshot(
        candidate_id=candidate.id,
        fetched_url=url,
        content=content,
        content_hash=digest,
        parser_version="matching-demo-v1",
        fetched_time=utc_now(),
    ))
    db.commit()
    return candidate


def main() -> None:
    _assert_test_database()
    # 演示种子不调用外部服务，确保首次本地验证可复现且不产生 API 费用。
    discovery_module.retrieve = lambda *_args, **_kwargs: []
    discovery_module.open_source_matcher.rerank = lambda _pairs: None
    discovery_module.open_source_matcher.nli = lambda _pairs: None

    with SessionLocal() as db:
        course, chapters = _upsert_course_and_chapters(db)
        source = db.scalar(select(AuthoritySourceRegistry).order_by(AuthoritySourceRegistry.id))
        if source is None:
            raise RuntimeError("权威来源尚未初始化，请先启动一次后端")
        service = AuthorityDiscoveryService(db)
        results = []
        for key, title, content in CANDIDATES:
            candidate = _replace_candidate(db, source, key, title, content)
            service.associate_candidate(candidate.id)
            changes = service.detect_policy_changes(candidate.id)
            candidate = db.get(MaterialCandidate, candidate.id)
            if candidate.suggested_chapter_ids and candidate.association_confidence >= float(
                settings.authority_discovery_min_association_score
            ):
                candidate.status = "pending_review"
            elif candidate.suggested_chapter_ids:
                candidate.status = "observed"
            else:
                candidate.status = "filtered"
            candidate.analysis_reason = (
                f"本地演示分析完成：匹配 {len(candidate.suggested_chapter_ids or [])} 个章节，"
                f"生成 {len(changes)} 条差异证据。"
            )
            db.commit()
            matched_titles = list(db.scalars(select(Chapter.title).where(
                Chapter.id.in_(candidate.suggested_chapter_ids or [])
            )).all()) if candidate.suggested_chapter_ids else []
            results.append((key, candidate.id, candidate.status, candidate.association_confidence, matched_titles, len(changes)))

    print(f"课程 #{course.id}：{course.name}")
    print("章节：" + "；".join(f"#{chapter.id} {chapter.title}" for chapter in chapters.values()))
    for key, candidate_id, status, confidence, titles, change_count in results:
        print(
            f"{key}: candidate=#{candidate_id}, status={status}, confidence={confidence:.1%}, "
            f"chapters={titles or []}, changes={change_count}"
        )


if __name__ == "__main__":
    main()

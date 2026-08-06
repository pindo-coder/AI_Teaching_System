from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text

from app.models.authority_discovery import MaterialCandidate, MaterialSnapshot, PolicyChange
from app.models.chapter import Chapter
from app.models.course import Course
from app.models.citation import KnowledgeChunk
from app.models.knowledge_document import KnowledgeDocument
from app.models.material_scope import DocumentCourseScope
from app.models.user import User
from app.models.teaching_notification import TeachingNotification
from app.schemas.authority_discovery import DiscoveryJobCreate
from app.services import authority_discovery_service as discovery
from app.services.authority_discovery_service import AuthorityDiscoveryService, _process_discovery_job
from app.services.authority_discovery_service import _estimate_content_quality, _score
from app.services.notification_service import NotificationService
from app.services.material_center_service import _ArticleTextParser


def test_discovery_job_creates_pending_candidate_and_snapshot(db, monkeypatch) -> None:
    admin = User(username="discovery-admin", password_hash="hash", role="admin")
    db.add(admin)
    db.commit()
    service = AuthorityDiscoveryService(db)
    source = service.list_sources()[0]
    job = service.create_job(admin, DiscoveryJobCreate(
        keywords=["全过程人民民主"], source_ids=[source.id],
        start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
    ))
    monkeypatch.setattr(discovery, "_candidate_links", lambda *_: [
        ("https://www.gov.cn/zhengce/2026-01/01/content_1.htm", "全过程人民民主新部署"),
    ])
    monkeypatch.setattr(discovery, "_default_fetch", lambda *_: (
        "这是用于测试的权威材料正文。" * 20,
        "https://www.gov.cn/zhengce/2026-01/01/content_1.htm",
        "全过程人民民主新部署", "中国政府网", date(2026, 1, 2),
    ))

    _process_discovery_job(job.id, db.get_bind())

    candidate = db.query(MaterialCandidate).one()
    snapshot = db.query(MaterialSnapshot).one()
    assert candidate.status == "pending_review"
    assert candidate.recommended_material_type == "central"
    assert candidate.content_hash == snapshot.content_hash
    assert snapshot.candidate_id == candidate.id
    db.expire_all()
    refreshed = db.get(type(job), job.id)
    assert refreshed.status == "completed"
    assert refreshed.pending_review_count == 1


def test_candidate_analysis_associates_textbook_and_creates_evidence(db) -> None:
    course = Course(name="习近平新时代中国特色社会主义思想概论", description="")
    db.add(course)
    db.flush()
    chapter = Chapter(course_id=course.id, title="全过程人民民主", content=(
        "全过程人民民主是社会主义民主政治的本质属性。坚持党的领导、人民当家作主、依法治国有机统一。"
    ))
    db.add(chapter)
    admin = User(username="analysis-admin", password_hash="hash", role="admin")
    db.add(admin)
    db.flush()
    source = AuthorityDiscoveryService(db).list_sources()[0]
    candidate = MaterialCandidate(
        source_registry_id=source.id, title="全过程人民民主新部署意见", source_url="https://www.gov.cn/new",
        canonical_url="https://www.gov.cn/new", publisher="中国政府网", source_level="A",
        recommended_material_type="central", status="pending_review", content_hash="a" * 64,
        content_preview="全过程人民民主是社会主义民主政治的本质属性。完善全过程人民民主制度。",
        relevance_score=0.8, freshness_score=1, novelty_score=1,
    )
    db.add(candidate)
    db.flush()
    db.add(MaterialSnapshot(
        candidate_id=candidate.id, fetched_url=candidate.source_url,
        content="全过程人民民主是社会主义民主政治的本质属性。完善全过程人民民主制度。",
        content_hash="a" * 64, fetched_time=discovery._now(),
    ))
    db.commit()

    analyzed = AuthorityDiscoveryService(db).analyze_candidate(candidate.id)
    assert chapter.id in analyzed.suggested_chapter_ids
    assert analyzed.association_confidence > 0
    changes = db.query(PolicyChange).filter_by(candidate_id=candidate.id).all()
    assert changes
    assert changes[0].old_excerpt
    assert changes[0].new_excerpt
    assert changes[0].review_status == "pending"


def test_confirmed_change_notification_is_idempotent(db) -> None:
    teacher = User(username="notify-teacher", password_hash="hash", role="teacher", approval_status="approved")
    admin = User(username="notify-admin", password_hash="hash", role="admin")
    db.add_all([teacher, admin])
    db.flush()
    source = AuthorityDiscoveryService(db).list_sources()[0]
    candidate = MaterialCandidate(
        source_registry_id=source.id, title="重要会议精神更新", source_url="https://www.gov.cn/update",
        canonical_url="https://www.gov.cn/update", publisher="中国政府网", source_level="A",
        recommended_material_type="central", status="published", content_hash="b" * 64,
        content_preview="新的权威表述", course_ids=[42], chapter_ids=[7],
    )
    db.add(candidate)
    db.flush()
    change = PolicyChange(
        candidate_id=candidate.id, change_type="重要会议精神", old_excerpt="旧表述",
        new_excerpt="新表述", importance="high", alert_recommended=True,
        review_status="confirmed", kb_sync_status="synced", affected_course_ids=[42],
    )
    db.add(change)
    db.commit()

    first = NotificationService(db).create_policy_change_notifications(change)
    second = NotificationService(db).create_policy_change_notifications(change)
    assert len(first) == 1  # 未绑定教学班时没有课程对应教师，系统按已审核教师回退
    assert second == []
    # 当前 teacher 回退收件人应收到一条，并且重复执行不会增加数量。
    assert db.query(TeachingNotification).count() == 1


def test_discovery_rejects_irrelevant_full_text_even_for_a_level_source(db, monkeypatch) -> None:
    admin = User(username="filter-admin", password_hash="hash", role="admin")
    db.add(admin); db.commit()
    service = AuthorityDiscoveryService(db)
    source = service.list_sources()[0]
    job = service.create_job(admin, DiscoveryJobCreate(keywords=["思政课建设"], source_ids=[source.id]))
    monkeypatch.setattr(discovery, "_candidate_links", lambda *_: [("https://www.gov.cn/unrelated", "最新发布")])
    monkeypatch.setattr(discovery, "_default_fetch", lambda *_: (
        "这是一篇与检索主题无关的公共信息。", "https://www.gov.cn/unrelated",
        "公共服务通知", "中国政府网", date(2026, 8, 1),
    ))

    _process_discovery_job(job.id, db.get_bind())

    assert db.query(MaterialCandidate).count() == 0
    db.expire_all()
    assert db.get(type(job), job.id).fetched_count == 0


def test_discovery_manual_job_is_cooled_down_and_queue_is_bounded(db, monkeypatch) -> None:
    admin = User(username="cooldown-admin", password_hash="hash", role="admin")
    db.add(admin); db.commit()
    service = AuthorityDiscoveryService(db)
    source = service.list_sources()[0]
    monkeypatch.setattr(discovery.settings, "authority_discovery_cooldown_minutes", 30)
    monkeypatch.setattr(discovery.settings, "authority_discovery_max_queued", 1)
    monkeypatch.setattr(discovery.settings, "authority_discovery_max_running", 1)
    payload = DiscoveryJobCreate(keywords=["中国式现代化"], source_ids=[source.id])
    service.create_job(admin, payload)
    with pytest.raises(HTTPException) as duplicate:
        service.create_job(admin, payload)
    assert duplicate.value.status_code == 409

    other_admin = User(username="queue-admin", password_hash="hash", role="admin")
    db.add(other_admin); db.commit()
    service.create_job(other_admin, DiscoveryJobCreate(keywords=["全过程人民民主"], source_ids=[source.id]))
    with pytest.raises(HTTPException) as full:
        service.create_job(other_admin, DiscoveryJobCreate(keywords=["共同富裕"], source_ids=[source.id]))
    assert full.value.status_code == 429


def test_discovery_job_can_only_be_claimed_once(db) -> None:
    admin = User(username="claim-admin", password_hash="hash", role="admin")
    db.add(admin); db.commit()
    service = AuthorityDiscoveryService(db)
    source = service.list_sources()[0]
    job = service.create_job(admin, DiscoveryJobCreate(keywords=["思政课"], source_ids=[source.id]))

    assert discovery._claim_queued_job(job.id, db.get_bind()) is True
    assert discovery._claim_queued_job(job.id, db.get_bind()) is False
    db.expire_all()
    assert service.require_job(job.id).status == "running"


def test_relevance_score_is_not_derived_from_source_level() -> None:
    title, content, keywords = "全过程人民民主新部署", "", ["全过程人民民主"]
    level_a = _score(title, content, keywords, "A")[0]
    level_b = _score(title, content, keywords, "B")[0]
    assert level_a == level_b == 0.65
    assert _score(title, "", [], "B")[0] == 0


def test_directory_like_content_gets_low_quality_score() -> None:
    listing = "\n".join(f"最新发布标题 {index} 来源栏目" for index in range(20))
    article = "。".join("这是具有完整语义的政策正文段落，包含具体工作部署和实施要求" for _ in range(8))
    assert _estimate_content_quality(listing) < 0.60
    assert _estimate_content_quality(article) >= 0.60


def test_html_parser_prefers_article_container_over_navigation() -> None:
    parser = _ArticleTextParser()
    parser.feed("""
        <html><head><title>栏目首页</title></head><body>
        <nav>栏目一 栏目二 推荐阅读</nav>
        <main class='article-content'><h1>权威文件标题</h1>
        <p>这是正式文章正文，说明政策背景、主要目标和具体实施安排。</p>
        <p>正文第二段继续说明适用范围、工作要求以及后续保障机制。</p></main>
        <footer>版权信息 友情链接</footer>
        </body></html>
    """)
    text = parser.text()
    assert "政策背景" in text
    assert "友情链接" not in text


def test_outdated_discovery_schema_does_not_block_application_startup() -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE discovery_jobs (id INTEGER PRIMARY KEY, status VARCHAR(24) NOT NULL)"
        ))

    # A pending Alembic migration disables only the discovery scheduler; the
    # rest of FastAPI must still be able to start and expose an actionable log.
    discovery.start_discovery_scheduler(engine)


def test_scoped_central_material_participates_in_policy_comparison(db) -> None:
    course = Course(name="思想理论教材", description="")
    db.add(course); db.flush()
    chapter = Chapter(course_id=course.id, title="中国式现代化", content="中国式现代化坚持以人民为中心。")
    db.add(chapter); db.flush()
    document = KnowledgeDocument(
        source_title="既有中央文件", source_type="md", original_filename="central.md",
        stored_path="/not/existing/central.md", course_id=None, chapter_id=None,
        vector_collection="test", material_type="central", publisher="中央机关",
        review_status="published", is_active=True, status="ready", chunk_count=1,
    )
    db.add(document); db.flush()
    db.add(DocumentCourseScope(document_id=document.id, course_id=course.id, confirmed=True))
    db.add(KnowledgeChunk(
        document_id=document.id, chapter_id=None, chunk_index=0,
        content="中国式现代化坚持以人民为中心，坚持共同富裕。",
        vector_id="central-scope-test", pdf_page_start=1, pdf_page_end=1,
        index_version="test-v1",
    ))
    source = AuthorityDiscoveryService(db).list_sources()[0]
    candidate = MaterialCandidate(
        source_registry_id=source.id, title="中国式现代化新部署", source_url="https://www.gov.cn/modernization",
        canonical_url="https://www.gov.cn/modernization", publisher="中国政府网", source_level="A",
        recommended_material_type="central", status="pending_review", content_hash="c" * 64,
        content_preview="中国式现代化坚持以人民为中心，并进一步促进共同富裕。",
        suggested_course_ids=[course.id], suggested_chapter_ids=[chapter.id],
    )
    db.add(candidate); db.flush()
    db.add(MaterialSnapshot(
        candidate_id=candidate.id, fetched_url=candidate.source_url,
        content=candidate.content_preview, content_hash="c" * 64, fetched_time=discovery._now(),
    ))
    db.commit()

    references = AuthorityDiscoveryService(db)._reference_sources(candidate)
    assert any(item[0] == document.id for item in references)


def test_source_can_disable_teacher_alerts(db) -> None:
    teacher = User(username="silent-teacher", password_hash="hash", role="teacher", approval_status="approved")
    db.add(teacher); db.flush()
    source = AuthorityDiscoveryService(db).list_sources()[0]
    source.allow_alert = False
    candidate = MaterialCandidate(
        source_registry_id=source.id, title="仅入库不提醒", source_url="https://www.gov.cn/silent",
        canonical_url="https://www.gov.cn/silent", publisher="中国政府网", source_level="A",
        recommended_material_type="central", status="published", content_hash="d" * 64,
    )
    db.add(candidate); db.flush()
    change = PolicyChange(
        candidate_id=candidate.id, change_type="新增重要表述", old_excerpt="旧", new_excerpt="新",
        importance="high", alert_recommended=True, review_status="confirmed", kb_sync_status="synced",
    )
    db.add(change); db.commit()

    assert NotificationService(db).create_policy_change_notifications(change) == []
    assert db.query(TeachingNotification).count() == 0

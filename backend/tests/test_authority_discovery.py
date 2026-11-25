from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select, text
from sqlalchemy.dialects import mysql

from app.models.authority_discovery import AuthoritySourceRegistry, MaterialCandidate, MaterialSnapshot, PolicyChange
from app.models.chapter import Chapter
from app.models.course import Course
from app.models.citation import KnowledgeChunk
from app.models.knowledge_document import KnowledgeDocument
from app.models.material_scope import DocumentChapterScope, DocumentCourseScope
from app.models.user import User
from app.models.teaching_notification import TeachingNotification
from app.core.security import create_access_token
from app.schemas.authority_discovery import CandidateBatchAction, DiscoveryJobCreate
from app.services import authority_discovery_service as discovery
from app.services.authority_discovery_service import AuthorityDiscoveryService, _process_discovery_job
from app.services.authority_discovery_service import _estimate_content_quality, _score, _topic_match
from app.services.notification_service import NotificationService
from app.services.material_center_service import _ArticleTextParser


def test_discovery_job_creates_pending_candidate_and_snapshot(db, monkeypatch) -> None:
    course = Course(name="思想政治理论课", description="")
    db.add(course); db.flush()
    db.add(Chapter(
        course_id=course.id, title="全过程人民民主",
        content="全过程人民民主是社会主义民主政治的重要内容。这是用于测试的权威材料正文。",
    ))
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
    monkeypatch.setattr(discovery, "_fetch_source_article", lambda *_: (
        ("全过程人民民主是社会主义民主政治的重要内容。"
         "要健全全过程人民民主制度体系，扩大人民有序政治参与。") * 12,
        "https://www.gov.cn/zhengce/2026-01/01/content_1.htm",
        "全过程人民民主新部署", "中国政府网", date(2026, 1, 2),
        "authority-gov-cn-v1",
    ))

    _process_discovery_job(job.id, db.get_bind())

    candidate = db.query(MaterialCandidate).one()
    snapshot = db.query(MaterialSnapshot).one()
    assert candidate.status == "pending_review"
    assert candidate.recommended_material_type == "central"
    assert candidate.content_hash == snapshot.content_hash
    assert snapshot.candidate_id == candidate.id
    assert candidate.suggested_course_ids == [course.id]
    assert candidate.suggested_chapter_ids
    assert candidate.association_confidence > 0
    assert "差异证据" in candidate.analysis_reason
    assert db.query(PolicyChange).filter_by(candidate_id=candidate.id).count() > 0
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
    monkeypatch.setattr(discovery, "_fetch_source_article", lambda *_: (
        "这是一篇与检索主题无关的公共信息。", "https://www.gov.cn/unrelated",
        "公共服务通知", "中国政府网", date(2026, 8, 1),
        "authority-gov-cn-v1",
    ))

    _process_discovery_job(job.id, db.get_bind())

    assert db.query(MaterialCandidate).count() == 0
    db.expire_all()
    assert db.get(type(job), job.id).fetched_count == 1


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


def test_topic_matching_retains_body_hits_and_close_chinese_variants() -> None:
    keyword = "法治宣传教育规划"
    assert _topic_match("最新发布", "全面推进法治宣传教育五年规划实施", [keyword]) is True
    body_score = _score("最新发布", "全面贯彻法治宣传教育规划，健全工作体系。", [keyword], "A")[0]
    assert body_score >= 0.55


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


def test_chapter_scoped_central_material_participates_in_policy_comparison(db) -> None:
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
    db.add(DocumentChapterScope(document_id=document.id, chapter_id=chapter.id, confirmed=True))
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
    assert next(item for item in references if item[0] == document.id).scope_level == "chapter"


def test_reference_document_ordering_is_mysql_compatible() -> None:
    statement = select(KnowledgeDocument).order_by(
        *discovery._published_date_desc_nulls_last(),
    )

    sql = str(statement.compile(dialect=mysql.dialect()))

    assert "NULLS LAST" not in sql.upper()
    assert "IS NULL" in sql.upper()


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


def test_source_failure_is_visible_on_job(db, monkeypatch) -> None:
    admin = User(username="failure-admin", password_hash="hash", role="admin")
    db.add(admin); db.commit()
    service = AuthorityDiscoveryService(db)
    source = service.list_sources()[0]
    job = service.create_job(admin, DiscoveryJobCreate(keywords=["思政课"], source_ids=[source.id]))
    monkeypatch.setattr(discovery, "_candidate_links", lambda *_: (_ for _ in ()).throw(RuntimeError("TLS 连接失败")))

    _process_discovery_job(job.id, db.get_bind())

    db.expire_all()
    failed = service.require_job(job.id)
    assert failed.status == "failed"
    assert failed.progress_stage == "执行失败"
    assert "中国政府网" in failed.error_message
    assert "TLS 连接失败" in failed.error_message


def test_single_article_source_skips_listing_fetch(db, monkeypatch) -> None:
    source = AuthoritySourceRegistry(
        name="单篇权威原文",
        domain="example.gov.cn",
        source_level="C",
        adapter_type="single_article",
        entry_url="https://example.gov.cn/policy/one.html",
    )
    monkeypatch.setattr(
        discovery,
        "_fetch_source_bytes",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("不应读取列表页")),
    )

    assert discovery._read_listing(source) == [
        ("https://example.gov.cn/policy/one.html", "单篇权威原文"),
    ]


def test_delete_finished_job_keeps_candidate(db) -> None:
    admin = User(username="delete-job-admin", password_hash="hash", role="admin")
    db.add(admin); db.commit()
    service = AuthorityDiscoveryService(db)
    source = service.list_sources()[0]
    job = service.create_job(admin, DiscoveryJobCreate(keywords=["思政课"], source_ids=[source.id]))
    job.status = "completed"
    candidate = MaterialCandidate(
        discovery_job_id=job.id, source_registry_id=source.id, title="待保留候选",
        source_url="https://www.gov.cn/keep", canonical_url="https://www.gov.cn/keep",
        source_level="A", status="pending_review", recommended_material_type="central",
    )
    db.add(candidate); db.commit(); candidate_id = candidate.id

    assert service.delete_job(job.id) == job.id
    db.expire_all()
    assert db.get(MaterialCandidate, candidate_id) is not None
    assert db.get(MaterialCandidate, candidate_id).discovery_job_id is None


def test_delete_unpublished_candidate_removes_evidence_but_published_is_protected(db) -> None:
    admin = User(username="delete-candidate-admin", password_hash="hash", role="admin")
    db.add(admin); db.flush()
    source = AuthorityDiscoveryService(db).list_sources()[0]
    candidate = MaterialCandidate(
        source_registry_id=source.id, title="低关联候选", source_url="https://www.gov.cn/low",
        canonical_url="https://www.gov.cn/low", source_level="A", status="filtered",
        recommended_material_type="central", content_hash="e" * 64,
    )
    db.add(candidate); db.flush()
    db.add(MaterialSnapshot(
        candidate_id=candidate.id, fetched_url=candidate.source_url, content="低关联正文",
        content_hash="e" * 64, fetched_time=discovery._now(),
    ))
    db.add(PolicyChange(
        candidate_id=candidate.id, change_type="新增重要表述", old_excerpt="旧", new_excerpt="新",
        importance="low", review_status="pending",
    ))
    db.commit(); candidate_id = candidate.id

    assert AuthorityDiscoveryService(db).delete_candidate(candidate_id) == candidate_id
    assert db.get(MaterialCandidate, candidate_id) is None
    assert db.query(MaterialSnapshot).filter_by(candidate_id=candidate_id).count() == 0
    assert db.query(PolicyChange).filter_by(candidate_id=candidate_id).count() == 0

    published = MaterialCandidate(
        source_registry_id=source.id, title="已发布候选", source_url="https://www.gov.cn/published",
        canonical_url="https://www.gov.cn/published", source_level="A", status="published",
        recommended_material_type="central",
    )
    db.add(published); db.commit()
    with pytest.raises(HTTPException) as protected:
        AuthorityDiscoveryService(db).delete_candidate(published.id)
    assert protected.value.status_code == 409


def test_below_retention_topic_candidate_is_filtered_and_review_notification_is_resolved(db) -> None:
    admin = User(username="filter-notification-admin", password_hash="hash", role="admin")
    db.add(admin); db.flush()
    source = AuthorityDiscoveryService(db).list_sources()[0]
    candidate = MaterialCandidate(
        source_registry_id=source.id, title="历史低关联材料", source_url="https://www.gov.cn/legacy-low",
        canonical_url="https://www.gov.cn/legacy-low", source_level="A", status="pending_review",
        recommended_material_type="central", association_confidence=0.6, relevance_score=0.20,
    )
    db.add(candidate); db.flush()
    notification = TeachingNotification(
        recipient_user_id=admin.id, notification_type="material_review", level="important",
        title="待审核权威材料", content="请审核", action_url=f"/material-discovery?candidate={candidate.id}",
    )
    db.add(notification); db.commit()

    pending = AuthorityDiscoveryService(db).list_candidates(status="pending_review")

    assert candidate not in pending
    db.refresh(candidate); db.refresh(notification)
    assert candidate.status == "filtered"
    assert "主题相关度" in candidate.analysis_reason
    assert notification.is_read is True


def test_weak_chapter_match_is_retained_for_observation_without_important_alert(db) -> None:
    admin = User(username="weak-match-admin", password_hash="hash", role="admin")
    db.add(admin); db.flush()
    source = AuthorityDiscoveryService(db).list_sources()[0]
    candidate = MaterialCandidate(
        source_registry_id=source.id, title="网页弱关联候选", source_url="https://www.gov.cn/weak-match",
        canonical_url="https://www.gov.cn/weak-match", source_level="A", status="pending_review",
        recommended_material_type="central", association_confidence=0.30, relevance_score=0.80,
        suggested_course_ids=[1], suggested_chapter_ids=[9],
    )
    db.add(candidate); db.commit()
    created = NotificationService(db).create_candidate_review_notifications(candidate, evidence_count=1)

    assert created and created[0].level == "normal"
    assert candidate not in AuthorityDiscoveryService(db).list_candidates(status="pending_review")
    db.refresh(candidate); db.refresh(created[0])
    assert candidate.status == "observed"
    assert "观察区" in candidate.analysis_reason
    assert created[0].is_read is True


def test_weak_topic_match_with_strong_chapter_evidence_is_retained_for_observation(db) -> None:
    source = AuthorityDiscoveryService(db).list_sources()[0]
    candidate = MaterialCandidate(
        source_registry_id=source.id, title="网页近义主题候选", source_url="https://www.gov.cn/weak-topic",
        canonical_url="https://www.gov.cn/weak-topic", source_level="A", status="pending_review",
        recommended_material_type="central", association_confidence=0.80, relevance_score=0.40,
        suggested_course_ids=[1], suggested_chapter_ids=[9],
    )
    db.add(candidate); db.commit()

    assert candidate not in AuthorityDiscoveryService(db).list_candidates(status="pending_review")
    db.refresh(candidate)
    assert candidate.status == "observed"
    assert "观察区" in candidate.analysis_reason


def test_batch_candidate_actions_reduce_manual_decision_count(db) -> None:
    admin = User(username="batch-candidate-admin", password_hash="hash", role="admin")
    db.add(admin); db.flush()
    service = AuthorityDiscoveryService(db)
    source = service.list_sources()[0]
    candidates = [MaterialCandidate(
        source_registry_id=source.id, title=f"批量候选 {index}",
        source_url=f"https://www.gov.cn/batch-{index}", canonical_url=f"https://www.gov.cn/batch-{index}",
        source_level="A", status="pending_review", recommended_material_type="central",
        association_confidence=0.8, relevance_score=0.8,
    ) for index in range(3)]
    db.add_all(candidates); db.commit()

    initial_summary = service.candidate_decision_summary()
    assert initial_summary["pending_review"] == 3
    assert initial_summary["high_priority"] == 0
    updated = service.batch_candidates(admin, CandidateBatchAction(
        candidate_ids=[candidates[0].id, candidates[1].id], action="observe",
    ))
    assert updated == 2
    assert service.candidate_decision_summary()["pending_review"] == 1
    assert service.candidate_decision_summary()["observed"] == 2

    deleted_id = candidates[2].id
    assert service.batch_candidates(admin, CandidateBatchAction(
        candidate_ids=[deleted_id], action="delete",
    )) == 1
    assert db.get(MaterialCandidate, deleted_id) is None
    assert service.candidate_decision_summary()["pending_review"] == 0


def test_candidate_topic_groups_choose_authoritative_primary_and_keep_unrelated_separate(db) -> None:
    service = AuthorityDiscoveryService(db)
    sources = service.list_sources()
    government = next(item for item in sources if item.source_level == "A")
    media = next(item for item in sources if item.source_level == "B")
    related = [
        MaterialCandidate(
            source_registry_id=media.id, title="全过程人民民主制度建设最新部署",
            source_url="https://www.qstheory.cn/topic-1", canonical_url="https://www.qstheory.cn/topic-1",
            publisher="求是网", source_level="B", status="pending_review",
            recommended_material_type="central", suggested_course_ids=[1], suggested_chapter_ids=[11],
            association_confidence=0.86, relevance_score=0.82, importance_score=0.91,
        ),
        MaterialCandidate(
            source_registry_id=government.id, title="关于加强全过程人民民主制度建设的意见",
            source_url="https://www.gov.cn/topic-2", canonical_url="https://www.gov.cn/topic-2",
            publisher="中国政府网", source_level="A", status="pending_review",
            recommended_material_type="central", suggested_course_ids=[1], suggested_chapter_ids=[11],
            association_confidence=0.78, relevance_score=0.84, importance_score=0.80,
        ),
    ]
    unrelated = MaterialCandidate(
        source_registry_id=government.id, title="高校毕业生就业服务专项行动通知",
        source_url="https://www.gov.cn/unrelated-topic", canonical_url="https://www.gov.cn/unrelated-topic",
        publisher="中国政府网", source_level="A", status="pending_review",
        recommended_material_type="central", suggested_course_ids=[1], suggested_chapter_ids=[11],
        association_confidence=0.75, relevance_score=0.8, importance_score=0.8,
    )
    db.add_all([*related, unrelated]); db.commit()

    groups = service.candidate_topic_groups()

    assert len(groups) == 1
    assert groups[0]["candidate_ids"] == sorted(item.id for item in related)
    assert groups[0]["primary_candidate_id"] == related[1].id
    assert unrelated.id not in groups[0]["candidate_ids"]


def test_batch_duplicate_resolves_topic_group_secondaries(db) -> None:
    admin = User(username="topic-group-admin", password_hash="hash", role="admin")
    db.add(admin); db.flush()
    service = AuthorityDiscoveryService(db)
    source = service.list_sources()[0]
    secondary = MaterialCandidate(
        source_registry_id=source.id, title="同议题旁证材料",
        source_url="https://www.gov.cn/topic-secondary", canonical_url="https://www.gov.cn/topic-secondary",
        source_level="A", status="pending_review", recommended_material_type="central",
        association_confidence=0.8, relevance_score=0.8,
    )
    db.add(secondary); db.commit()

    assert service.batch_candidates(admin, CandidateBatchAction(
        candidate_ids=[secondary.id], action="duplicate", note="同议题旁证已归并到主材料",
    )) == 1
    db.refresh(secondary)
    assert secondary.status == "duplicate"
    assert secondary.review_notes == "同议题旁证已归并到主材料"


def test_candidate_summary_and_batch_api_use_static_routes(client, db) -> None:
    admin = User(username="batch-candidate-api-admin", password_hash="hash", role="admin")
    db.add(admin); db.flush()
    service = AuthorityDiscoveryService(db)
    source = service.list_sources()[0]
    candidates = [MaterialCandidate(
        source_registry_id=source.id, title=f"接口批量候选 {index}",
        source_url=f"https://www.gov.cn/api-batch-{index}",
        canonical_url=f"https://www.gov.cn/api-batch-{index}",
        source_level="A", status="pending_review", recommended_material_type="central",
        association_confidence=0.8, relevance_score=0.8, importance_level="high",
    ) for index in range(2)]
    db.add_all(candidates); db.commit()
    headers = {"Authorization": f"Bearer {create_access_token(str(admin.id))}"}

    summary = client.get("/api/v1/knowledge/discovery/candidates/summary", headers=headers)
    assert summary.status_code == 200
    assert summary.json()["data"]["pending_review"] == 2
    groups = client.get("/api/v1/knowledge/discovery/candidates/groups", headers=headers)
    assert groups.status_code == 200
    assert groups.json()["data"] == []

    observed = client.post(
        "/api/v1/knowledge/discovery/candidates/batch", headers=headers,
        json={"candidate_ids": [candidates[0].id], "action": "observe"},
    )
    assert observed.status_code == 200
    assert observed.json()["data"]["updated"] == 1

    summary = client.get("/api/v1/knowledge/discovery/candidates/summary", headers=headers)
    assert summary.json()["data"] == {
        "pending_review": 1, "high_priority": 1, "observed": 1, "filtered": 0,
    }


def test_batch_delete_rejects_published_candidate(db) -> None:
    admin = User(username="protected-batch-admin", password_hash="hash", role="admin")
    db.add(admin); db.flush()
    service = AuthorityDiscoveryService(db)
    source = service.list_sources()[0]
    published = MaterialCandidate(
        source_registry_id=source.id, title="批量删除保护材料",
        source_url="https://www.gov.cn/protected-batch",
        canonical_url="https://www.gov.cn/protected-batch",
        source_level="A", status="published", recommended_material_type="central",
    )
    db.add(published); db.commit()

    with pytest.raises(HTTPException) as protected:
        service.batch_candidates(admin, CandidateBatchAction(
            candidate_ids=[published.id], action="delete",
        ))

    assert protected.value.status_code == 409
    assert db.get(MaterialCandidate, published.id) is not None


def test_same_domain_allows_multiple_columns_and_delete_protection(client, db, monkeypatch) -> None:
    from app.core.security import create_access_token, hash_password

    monkeypatch.setattr(discovery, "_validate_source_url", lambda url, domain, allow_http=False: None)
    admin = User(username="multi-col-admin", password_hash=hash_password("secure-pass-123"), role="admin")
    db.add(admin); db.commit()
    headers = {"Authorization": f"Bearer {create_access_token(str(admin.id))}"}

    # 触发默认来源初始化（已包含 gov.cn 政策库）
    initial = client.get("/api/v1/knowledge/discovery/sources", headers=headers)
    assert initial.status_code == 200

    # 同域名 gov.cn 允许新增第二个栏目（要闻）
    second = client.post(
        "/api/v1/knowledge/discovery/sources",
        headers=headers,
        json={
            "name": "中国政府网·要闻",
            "domain": "gov.cn",
            "source_level": "A",
            "adapter_type": "html_list",
            "entry_url": "https://www.gov.cn/yaowen/liebiao/index.htm",
        },
    )
    assert second.status_code == 201
    second_id = second.json()["data"]["id"]

    # 完全相同的入口网址仍然返回 409
    dup = client.post(
        "/api/v1/knowledge/discovery/sources",
        headers=headers,
        json={
            "name": "重复要闻入口",
            "domain": "gov.cn",
            "source_level": "A",
            "adapter_type": "html_list",
            "entry_url": "https://www.gov.cn/yaowen/liebiao/index.htm",
        },
    )
    assert dup.status_code == 409

    # 没有候选材料引用的来源可直接删除
    deleted = client.delete(f"/api/v1/knowledge/discovery/sources/{second_id}", headers=headers)
    assert deleted.status_code == 200

    # 有候选材料引用的来源禁止删除
    first_id = initial.json()["data"][0]["id"]
    db.add(MaterialCandidate(
        source_registry_id=first_id, title="关联候选", source_url="https://www.gov.cn/used",
        canonical_url="https://www.gov.cn/used", source_level="A", status="observed",
    ))
    db.commit()
    blocked = client.delete(f"/api/v1/knowledge/discovery/sources/{first_id}", headers=headers)
    assert blocked.status_code == 409


def test_source_preview_and_runtime_status_api(client, db, monkeypatch) -> None:
    from app.core.security import create_access_token, hash_password

    monkeypatch.setattr(discovery, "_validate_source_url", lambda url, domain, allow_http=False: None)
    listing_html = (
        '<html><body>'
        '<a href="/yaowen/liebiao/202611/content_12345.htm">中共中央印发思政课建设新部署</a>'
        '</body></html>'
    ).encode("utf-8")
    article_html = (
        '<html><head><meta name="publishdate" content="2026-11-20"></head><body>'
        '<div class="pages_content"><h1>中共中央印发思政课建设新部署</h1>'
        '<p>要坚持思政课建设与党的创新理论武装同步推进，不断增强高校思政课针对性和吸引力。</p>'
        '<p>各地各高校要结合实际落实立德树人根本任务，完善实践教学与权威资料动态更新机制。</p>'
        '</div></body></html>'
    ).encode("utf-8")

    def fake_fetch(_source, url, *, limit):
        if "content_12345" in url:
            return article_html, url, {"content-type": "text/html; charset=utf-8"}, "utf-8"
        return listing_html, url, {"content-type": "text/html; charset=utf-8"}, "utf-8"

    monkeypatch.setattr(discovery, "_fetch_source_bytes", fake_fetch)
    admin = User(username="preview-admin", password_hash=hash_password("secure-pass-123"), role="admin")
    db.add(admin); db.commit()
    headers = {"Authorization": f"Bearer {create_access_token(str(admin.id))}"}

    preview = client.post(
        "/api/v1/knowledge/discovery/sources/preview",
        headers=headers,
        json={
            "domain": "gov.cn",
            "adapter_type": "html_list",
            "entry_url": "https://www.gov.cn/yaowen/liebiao/index.htm",
        },
    )
    assert preview.status_code == 200
    data = preview.json()["data"]
    assert data["ok"] is True
    assert data["adapter"] == "gov-cn"
    assert data["discovered_count"] == 1
    assert data["sample_article"]["published_date"] == "2026-11-20"
    assert data["sample_article"]["content_length"] >= 50
    # 试抓只读，不向数据库写入候选材料
    assert db.query(MaterialCandidate).count() == 0

    runtime = client.get("/api/v1/knowledge/discovery/runtime-status", headers=headers)
    assert runtime.status_code == 200
    assert "scheduler_enabled" in runtime.json()["data"]


def test_restore_and_publish_observed_candidate_with_chapter_scope(client, db) -> None:
    from app.core.security import create_access_token, hash_password

    admin = User(username="restore-publish-admin", password_hash=hash_password("secure-pass-123"), role="admin")
    course = Course(name="思政核心课", description="测试教材")
    db.add_all([admin, course]); db.flush()
    chapter = Chapter(course_id=course.id, title="第一章 理论创新", sort_order=1, content="理论创新内容")
    db.add(chapter); db.flush()
    source = AuthorityDiscoveryService(db).list_sources()[0]
    candidate = MaterialCandidate(
        source_registry_id=source.id, title="观察区重要材料",
        source_url="https://www.gov.cn/obs-1", canonical_url="https://www.gov.cn/obs-1",
        source_level="A", status="observed", recommended_material_type="central",
        association_confidence=0.25, relevance_score=0.40,
        content_preview="观察区摘要",
    )
    db.add(candidate); db.flush()
    full_text = "这是完整正文快照，包含足够详细的政策说明与理论阐述，用于验证观察区材料可恢复并直接发布到具体章节。" * 4
    db.add(MaterialSnapshot(
        candidate_id=candidate.id, fetched_url=candidate.source_url,
        content=full_text, content_hash="b" * 64, fetched_time=discovery._now(),
    ))
    db.commit()
    headers = {"Authorization": f"Bearer {create_access_token(str(admin.id))}"}

    # 1. 快照接口返回完整正文
    snaps = client.get(f"/api/v1/knowledge/discovery/candidates/{candidate.id}/snapshots", headers=headers)
    assert snaps.status_code == 200
    assert snaps.json()["data"][0]["content"] == full_text

    # 2. 从观察中移回待审核后，GET /candidates 不会再次将其踢回观察中
    restored = client.post(
        f"/api/v1/knowledge/discovery/candidates/{candidate.id}/review",
        headers=headers,
        json={"action": "restore"},
    )
    assert restored.status_code == 200
    assert restored.json()["data"]["status"] == "pending_review"

    listed = client.get(
        "/api/v1/knowledge/discovery/candidates",
        headers=headers,
        params={"status": "pending_review", "q": "观察区重要"},
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["data"]] == [candidate.id]

    # 3. 补全发布机构和发布日期，仅传 chapter_ids 发布，自动补齐 course_ids 并成功发布
    published = client.post(
        f"/api/v1/knowledge/discovery/candidates/{candidate.id}/review",
        headers=headers,
        json={
            "action": "publish",
            "source_title": "观察区重要材料（修订标题）",
            "publisher": "国务院",
            "published_date": "2026-11-24",
            "chapter_ids": [chapter.id],
            "knowledge_tags": ["理论创新"],
        },
    )
    assert published.status_code == 200
    pub_data = published.json()["data"]
    assert pub_data["status"] == "published"
    assert pub_data["course_ids"] == [course.id]
    assert pub_data["chapter_ids"] == [chapter.id]
    assert pub_data["document_id"] is not None

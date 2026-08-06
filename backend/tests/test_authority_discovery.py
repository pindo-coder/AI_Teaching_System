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
from app.core.security import create_access_token
from app.schemas.authority_discovery import CandidateBatchAction, DiscoveryJobCreate
from app.services import authority_discovery_service as discovery
from app.services.authority_discovery_service import AuthorityDiscoveryService, _process_discovery_job
from app.services.authority_discovery_service import _estimate_content_quality, _score
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


def test_low_association_candidate_is_filtered_and_review_notification_is_resolved(db) -> None:
    admin = User(username="filter-notification-admin", password_hash="hash", role="admin")
    db.add(admin); db.flush()
    source = AuthorityDiscoveryService(db).list_sources()[0]
    candidate = MaterialCandidate(
        source_registry_id=source.id, title="历史低关联材料", source_url="https://www.gov.cn/legacy-low",
        canonical_url="https://www.gov.cn/legacy-low", source_level="A", status="pending_review",
        recommended_material_type="central", association_confidence=0.6, relevance_score=0.35,
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

    assert service.candidate_decision_summary()["pending_review"] == 3
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
        association_confidence=0.8, relevance_score=0.8,
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

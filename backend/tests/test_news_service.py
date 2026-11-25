from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.core.config import settings
from app.core.time import utc_now
from app.models.news_item import NewsItem
from app.models.user import User
from app.services.news_service import NewsService, _clean, _parse_feed, _parse_time


def test_parse_feed_supports_gb_encoded_rss() -> None:
    xml = '<?xml version="1.0" encoding="gb2312"?><rss><channel><item><title>测试时政</title></item></channel></rss>'
    root = _parse_feed(xml.encode("gb18030"))
    assert root.findtext(".//item/title") == "测试时政"


def test_parse_rss_published_time() -> None:
    for source in (
        "Wed, 15 Jul 2026 08:30:00 +0800",
        "Wed, 15 Jul 2026 08:30:00 CST",
        "Wed, 15 Jul 2026 08:30:00",
    ):
        parsed = _parse_time(source)
        assert parsed == datetime(2026, 7, 15, 0, 30)
        assert parsed.tzinfo is None


def test_parse_iso_and_chinese_published_time() -> None:
    assert _parse_time("2026-07-15T08:30:00+08:00") == datetime(2026, 7, 15, 0, 30)
    assert _parse_time("2026年7月15日 08:30") == datetime(2026, 7, 15, 0, 30)


def test_news_note_source_time_uses_business_timezone() -> None:
    html = NewsService._draft_html(
        "测试时政",
        "权威来源",
        "https://example.com/news",
        datetime(2026, 7, 15, 0, 30),
        "正文",
    )

    assert "2026-07-15 08:30" in html


def test_clean_rss_summary_removes_images_and_html_but_keeps_text() -> None:
    source = '<P align="center"><TABLE><TR><TD><IMG src="x.jpg"></TD></TR></TABLE></P><P>生态文明建设&nbsp;持续推进。</P><style>.x{color:red}</style>'
    assert _clean(source) == "生态文明建设 持续推进。"
    assert "IMG" not in _clean(source)


def test_search_news_by_keyword_time_source_and_page(client: TestClient, db: Session) -> None:
    user = User(username="news_search_student", password_hash=hash_password("secure-pass-123"), role="student")
    now = utc_now()
    db.add(user); db.flush()
    db.add_all([
        NewsItem(title="推进生态文明建设", summary="推动绿色发展", source_name="中国新闻网时政", source_url="https://a.example/rss",
                 article_url="https://a.example/1", published_time=now - timedelta(days=1), fetched_time=now),
        NewsItem(title="绿色低碳发展取得新进展", summary="生态文明建设持续推进", source_name="中国新闻网国际", source_url="https://b.example/rss",
                 article_url="https://b.example/2", published_time=now - timedelta(days=2), fetched_time=now),
        NewsItem(title="历史资料", summary="生态文明专题旧稿", source_name="中国新闻网时政", source_url="https://a.example/rss",
                 article_url="https://a.example/3", published_time=now - timedelta(days=120), fetched_time=now - timedelta(days=120)),
    ])
    db.commit()
    headers = {"Authorization": f"Bearer {create_access_token(str(user.id))}"}

    response = client.get("/api/v1/current-affairs/search", headers=headers, params=[
        ("q", "生态文明"), ("source", "中国新闻网时政"), ("days", "30"),
        ("sort", "relevance"), ("page", "1"), ("page_size", "5"),
    ])
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["title"] == "推进生态文明建设"
    assert data["items"][0]["published_time"].endswith("Z")
    assert data["items"][0]["fetched_time"].endswith("Z")
    assert data["sources"] == ["中国新闻网时政", "中国新闻网国际"]


def test_news_api_preserves_legacy_business_wall_time_without_rewriting(
    client: TestClient,
    db: Session,
    monkeypatch,
) -> None:
    # This test validates timezone serialization, not the rolling news window.
    # Freeze the service clock so these serialization fixtures never become a
    # stale feed, trigger real RSS refresh, and get trimmed as dates advance.
    fixed_now = datetime(2026, 7, 16, 8, 30)
    monkeypatch.setattr("app.services.news_service.utc_now", lambda: fixed_now)
    user = User(username="legacy_news_student", password_hash=hash_password("secure-pass-123"), role="student")
    fetched_time = fixed_now
    db.add_all([
        user,
        NewsItem(
            title="历史时政时间",
            source_name="中国新闻网时政",
            source_url="https://legacy.example/rss",
            article_url="https://legacy.example/1",
            published_time=datetime(2026, 7, 15, 8, 30),
            published_time_is_utc=False,
            fetched_time=fetched_time,
        ),
        NewsItem(
            title="新时政时间",
            source_name="中国新闻网国际",
            source_url="https://new.example/rss",
            article_url="https://new.example/1",
            published_time=datetime(2026, 7, 15, 0, 30),
            published_time_is_utc=True,
            fetched_time=fetched_time,
        ),
    ])
    db.commit()
    headers = {"Authorization": f"Bearer {create_access_token(str(user.id))}"}

    response = client.get("/api/v1/current-affairs", headers=headers)
    assert response.status_code == 200
    items = {item["title"]: item for item in response.json()["data"]}
    assert items["历史时政时间"]["published_time"] == "2026-07-15T00:30:00Z"
    assert items["新时政时间"]["published_time"] == "2026-07-15T00:30:00Z"
    assert "published_time_is_utc" not in items["历史时政时间"]


def test_news_ai_summary_stream_does_not_require_course_or_chapter(
    client: TestClient,
    db: Session,
    monkeypatch,
) -> None:
    user = User(username="news_summary_student", password_hash=hash_password("secure-pass-123"), role="student")
    news = NewsItem(
        title="推进高质量发展",
        summary="权威媒体发布相关时政信息。",
        source_name="测试媒体",
        source_url="https://example.com/rss",
        article_url="https://example.com/news/quality",
        fetched_time=utc_now(),
    )
    db.add_all([user, news])
    db.commit()
    headers = {"Authorization": f"Bearer {create_access_token(str(user.id))}"}
    called: dict[str, int] = {}

    def fake_stream(service: NewsService, user_id: int, news_id: int):
        called.update(user_id=user_id, news_id=news_id)
        return iter(("仅依据时政材料生成的总结。",)), "test-model"

    monkeypatch.setattr(NewsService, "stream_ai_summary", fake_stream)
    response = client.post(f"/api/v1/current-affairs/{news.id}/ai-summary/stream", headers=headers)

    assert response.status_code == 200
    assert called == {"user_id": user.id, "news_id": news.id}
    assert '"scope": "news"' in response.text
    assert "仅依据时政材料生成的总结" in response.text
    assert "event: sources\ndata: []" in response.text


def test_news_ai_summary_mock_uses_news_material_only(db: Session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "ai_mock_mode", True)
    news = NewsItem(
        title="时政标题",
        summary="这是用于总结的新闻摘要。",
        source_name="测试媒体",
        source_url="https://example.com/rss",
        article_url="https://example.com/news/summary",
        fetched_time=utc_now(),
    )
    db.add(news)
    db.commit()

    chunks, model = NewsService(db).stream_ai_summary(user_id=1, news_id=news.id)
    answer = "".join(chunks)

    assert model == "mock"
    assert "这是用于总结的新闻摘要" in answer
    assert "本总结仅依据当前新闻标题与摘要" in answer
    assert "教材" not in answer


def test_trim_keeps_news_sources_balanced(db: Session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "news_max_items", 6)
    now = utc_now()
    for source_index, source_name in enumerate(("中国新闻网时政", "中国新闻网国际", "中国新闻网要闻")):
        for item_index in range(8):
            db.add(NewsItem(
                title=f"{source_name}-{item_index}",
                summary="时政摘要",
                source_name=source_name,
                source_url=f"https://{source_index}.example/rss",
                article_url=f"https://{source_index}.example/news/{item_index}",
                published_time=now - timedelta(minutes=item_index),
                fetched_time=now - timedelta(minutes=item_index),
            ))
    db.commit()

    NewsService(db)._trim()

    counts = dict(db.execute(select(NewsItem.source_name, func.count(NewsItem.id)).group_by(NewsItem.source_name)).all())
    assert sum(counts.values()) == 6
    assert counts == {"中国新闻网时政": 2, "中国新闻网国际": 2, "中国新闻网要闻": 2}


def test_source_names_only_include_recent_configured_news(db: Session) -> None:
    now = utc_now()
    db.add_all([
        NewsItem(
            title="有效来源稿件", summary="摘要", source_name="中国新闻网时政",
            source_url="https://a.example/rss", article_url="https://a.example/active",
            published_time=now - timedelta(days=1), fetched_time=now,
        ),
        NewsItem(
            title="过期来源稿件", summary="摘要", source_name="中国新闻网国际",
            source_url="https://b.example/rss", article_url="https://b.example/expired",
            published_time=now - timedelta(days=120), fetched_time=now - timedelta(days=120),
        ),
        NewsItem(
            title="旧配置来源稿件", summary="摘要", source_name="人民网时政",
            source_url="https://people.example/rss", article_url="https://people.example/legacy",
            published_time=now - timedelta(days=1), fetched_time=now,
        ),
    ])
    db.commit()

    assert NewsService(db).source_names(days=30) == ["中国新闻网时政"]


def test_teacher_classroom_debate_draft_and_role_guard(client: TestClient, db: Session) -> None:
    from app.models.chapter import Chapter
    from app.models.course import Course

    student = User(username="debate_student", password_hash=hash_password("secure-pass-123"), role="student")
    teacher = User(
        username="debate_teacher",
        password_hash=hash_password("secure-pass-123"),
        role="teacher",
        approval_status="approved",
    )
    course = Course(name="思政测试课程", description="测试教材")
    db.add_all([student, teacher, course])
    db.flush()
    chapter = Chapter(
        course_id=course.id,
        title="生态文明建设专题",
        sort_order=1,
        content="绿水青山就是金山银山，必须坚持统筹高质量发展和高水平保护，推进生态文明建设。",
    )
    now = utc_now()
    news = NewsItem(
        title="全国多地推进绿色低碳转型与生态补偿机制建设",
        summary="各地结合实际深化生态文明制度改革，推动绿色产业发展与生态环境保护协同共进。",
        source_name="中国新闻网时政",
        source_url="https://a.example/rss",
        article_url="https://a.example/eco-2026",
        published_time=now - timedelta(hours=3),
        fetched_time=now,
    )
    db.add_all([chapter, news])
    db.commit()

    student_headers = {"Authorization": f"Bearer {create_access_token(str(student.id))}"}
    teacher_headers = {"Authorization": f"Bearer {create_access_token(str(teacher.id))}"}

    # 详情接口可用
    detail = client.get(f"/api/v1/current-affairs/{news.id}", headers=teacher_headers)
    assert detail.status_code == 200
    assert detail.json()["data"]["title"] == news.title

    # 学生无权调用教师课堂辨析草稿接口
    forbidden = client.post(
        f"/api/v1/current-affairs/{news.id}/classroom-debate-draft",
        headers=student_headers,
        json={"course_id": course.id, "chapter_id": chapter.id, "activity_type": "judgment"},
    )
    assert forbidden.status_code == 403

    # 教师生成观点辨析草稿
    resp = client.post(
        f"/api/v1/current-affairs/{news.id}/classroom-debate-draft",
        headers=teacher_headers,
        json={"course_id": course.id, "chapter_id": chapter.id, "activity_type": "judgment"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["activity_type"] == "judgment"
    assert len(data["question"]) >= 15
    assert len(data["options"]) >= 2
    assert len(data["teaching_guide"]) >= 2
    assert data["source_citation"]["news_id"] == news.id
    assert data["source_citation"]["article_url"] == "https://a.example/eco-2026"
    assert "生态文明建设专题" in data["textbook_position"]

    # 随堂问答模式不返回判断选项
    qa_resp = client.post(
        f"/api/v1/current-affairs/{news.id}/classroom-debate-draft",
        headers=teacher_headers,
        json={"course_id": course.id, "chapter_id": chapter.id, "activity_type": "qa"},
    )
    assert qa_resp.status_code == 200
    assert qa_resp.json()["data"]["options"] == []


def test_lesson_prep_agent_injects_current_affairs_evidence(client: TestClient, db: Session) -> None:
    from app.models.agent_run import AgentRun
    from app.models.chapter import Chapter
    from app.models.course import Course

    teacher = User(
        username="prep_news_teacher",
        password_hash=hash_password("secure-pass-123"),
        role="teacher",
        approval_status="approved",
    )
    course = Course(name="中国式现代化专题课", description="测试教材")
    db.add_all([teacher, course])
    db.flush()
    chapter = Chapter(
        course_id=course.id,
        title="高质量发展与新质生产力",
        sort_order=1,
        content="高质量发展是全面建设社会主义现代化国家的首要任务，要加快发展新质生产力。",
    )
    now = utc_now()
    news = NewsItem(
        title="人工智能赋能制造业高质量发展新案例发布",
        summary="相关部门发布制造业智能化转型典型案例，强调科技创新引领现代化产业体系建设。",
        source_name="中国新闻网要闻",
        source_url="https://b.example/rss",
        article_url="https://b.example/ai-mfg",
        published_time=now - timedelta(hours=5),
        fetched_time=now,
    )
    db.add_all([chapter, news])
    db.commit()

    headers = {"Authorization": f"Bearer {create_access_token(str(teacher.id))}"}
    resp = client.post(
        "/api/v1/agent/runs",
        headers=headers,
        json={
            "agent_type": "teacher_lesson_prep",
            "course_id": course.id,
            "chapter_id": chapter.id,
            "input": {
                "lesson_hours": 2,
                "learning_stage": "preview",
                "student_level": "本科生",
                "teaching_goal": "结合制造业智能化案例讲透新质生产力",
                "news_item_ids": [news.id, news.id],
            },
        },
    )
    assert resp.status_code == 200
    run_data = resp.json()["data"]
    assert run_data["status"] == "waiting_confirmation"
    assert run_data["input_data"]["news_item_ids"] == [news.id]
    news_evidence = [item for item in run_data["evidence_snapshot"] if item["material_type"] == "current_affairs"]
    assert len(news_evidence) == 1
    assert news_evidence[0]["source_title"] == news.title
    assert news_evidence[0]["publisher"] == "中国新闻网要闻"
    assert news_evidence[0]["source_url"] == "https://b.example/ai-mfg"

    run_row = db.get(AgentRun, run_data["id"])
    assert run_row is not None
    assert news.title in (run_row.context_snapshot or "")

    # 不存在的时政 ID 返回 404
    missing = client.post(
        "/api/v1/agent/runs",
        headers=headers,
        json={
            "agent_type": "teacher_lesson_prep",
            "course_id": course.id,
            "chapter_id": chapter.id,
            "input": {"news_item_ids": [999999]},
        },
    )
    assert missing.status_code == 404


def test_lesson_prep_degrades_gracefully_when_vector_retrieval_fails(
    client: TestClient,
    db: Session,
    monkeypatch,
) -> None:
    from app.models.chapter import Chapter
    from app.models.course import Course
    from app.models.knowledge_document import KnowledgeDocument

    teacher = User(
        username="degrade_teacher",
        password_hash=hash_password("secure-pass-123"),
        role="teacher",
        approval_status="approved",
    )
    course = Course(name="降级容错课程", description="测试教材")
    db.add_all([teacher, course])
    db.flush()
    chapter = Chapter(
        course_id=course.id,
        title="第一章 教材直连降级",
        sort_order=1,
        content="本章节包含完整的教材正文依据，用于在外部 Embedding 网络波动时保底构建备课证据包。",
    )
    now = utc_now()
    news = NewsItem(
        title="降级测试时政案例",
        summary="确保向量检索失败时仍保留时政证据卡与教材正文依据。",
        source_name="中国新闻网时政",
        source_url="https://c.example/rss",
        article_url="https://c.example/degrade",
        published_time=now - timedelta(hours=1),
        fetched_time=now,
    )
    db.add_all([chapter, news])
    db.flush()
    doc = KnowledgeDocument(
        course_id=course.id,
        chapter_id=chapter.id,
        source_type="pdf",
        original_filename="textbook.pdf",
        stored_path="/tmp/textbook.pdf",
        vector_collection="ideology_course_kb",
        source_title="测试教材原文",
        material_type="textbook",
        status="ready",
        review_status="published",
    )
    db.add(doc)
    db.commit()

    def broken_retrieve(*_args, **_kwargs):
        raise ConnectionError("Connection error.")

    monkeypatch.setattr("app.services.ai_service.retrieve_layered", broken_retrieve)
    headers = {"Authorization": f"Bearer {create_access_token(str(teacher.id))}"}
    resp = client.post(
        "/api/v1/agent/runs",
        headers=headers,
        json={
            "agent_type": "teacher_lesson_prep",
            "course_id": course.id,
            "chapter_id": chapter.id,
            "input": {"news_item_ids": [news.id]},
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "waiting_confirmation"
    types = {item["material_type"] for item in data["evidence_snapshot"]}
    assert "current_affairs" in types
    assert "textbook" in types

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


def test_news_api_preserves_legacy_business_wall_time_without_rewriting(client: TestClient, db: Session) -> None:
    user = User(username="legacy_news_student", password_hash=hash_password("secure-pass-123"), role="student")
    fetched_time = utc_now()
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

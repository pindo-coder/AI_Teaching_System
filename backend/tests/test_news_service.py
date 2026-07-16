from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.models.news_item import NewsItem
from app.models.user import User
from app.services.news_service import _clean, _parse_feed, _parse_time


def test_parse_feed_supports_gb_encoded_rss() -> None:
    xml = '<?xml version="1.0" encoding="gb2312"?><rss><channel><item><title>测试时政</title></item></channel></rss>'
    root = _parse_feed(xml.encode("gb18030"))
    assert root.findtext(".//item/title") == "测试时政"


def test_parse_rss_published_time() -> None:
    parsed = _parse_time("Wed, 15 Jul 2026 08:30:00 +0800")
    assert parsed is not None
    assert parsed.year == 2026
    assert parsed.month == 7


def test_clean_rss_summary_removes_images_and_html_but_keeps_text() -> None:
    source = '<P align="center"><TABLE><TR><TD><IMG src="x.jpg"></TD></TR></TABLE></P><P>生态文明建设&nbsp;持续推进。</P><style>.x{color:red}</style>'
    assert _clean(source) == "生态文明建设 持续推进。"
    assert "IMG" not in _clean(source)


def test_search_news_by_keyword_time_source_and_page(client: TestClient, db: Session) -> None:
    user = User(username="news_search_student", password_hash=hash_password("secure-pass-123"), role="student")
    now = datetime.utcnow()
    db.add(user); db.flush()
    db.add_all([
        NewsItem(title="推进生态文明建设", summary="推动绿色发展", source_name="人民网时政", source_url="https://a.example/rss",
                 article_url="https://a.example/1", published_time=now - timedelta(days=1), fetched_time=now),
        NewsItem(title="绿色低碳发展取得新进展", summary="生态文明建设持续推进", source_name="央视新闻国内", source_url="https://b.example/rss",
                 article_url="https://b.example/2", published_time=now - timedelta(days=2), fetched_time=now),
        NewsItem(title="历史资料", summary="生态文明专题旧稿", source_name="人民网时政", source_url="https://a.example/rss",
                 article_url="https://a.example/3", published_time=now - timedelta(days=120), fetched_time=now - timedelta(days=120)),
    ])
    db.commit()
    headers = {"Authorization": f"Bearer {create_access_token(str(user.id))}"}

    response = client.get("/api/v1/current-affairs/search", headers=headers, params=[
        ("q", "生态文明"), ("source", "人民网时政"), ("days", "30"),
        ("sort", "relevance"), ("page", "1"), ("page_size", "5"),
    ])
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["title"] == "推进生态文明建设"
    assert "央视新闻国内" in data["sources"]

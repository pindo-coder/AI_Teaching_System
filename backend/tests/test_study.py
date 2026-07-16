from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.models.chapter import Chapter
from app.models.course import Course
from app.models.user import User
from app.models.news_item import NewsItem


def test_note_and_review_plan(client: TestClient, db: Session) -> None:
    user = User(username="note_student", password_hash=hash_password("secure-pass-123"), role="student")
    course = Course(name="习概", description="测试")
    db.add_all([user, course]); db.flush()
    chapter = Chapter(course_id=course.id, title="第一章", content="本专题教材正文用于说明核心概念、主要观点和专题笔记整理方法。", sort_order=1)
    db.add(chapter); db.commit()
    headers = {"Authorization": f"Bearer {create_access_token(str(user.id))}"}

    saved = client.put(f"/api/v1/study/notes/{chapter.id}", headers=headers, json={"content": "我的专题笔记"})
    assert saved.status_code == 200
    assert saved.json()["data"]["content"] == "我的专题笔记"

    listed = client.get("/api/v1/study/notes", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["data"][0]["chapter_title"] == "第一章"

    semantic = client.get("/api/v1/study/notes/semantic-search", headers=headers, params={"q": "专题笔记"})
    assert semantic.status_code == 200
    assert semantic.json()["data"][0]["id"] == saved.json()["data"]["id"]

    related = client.get(f"/api/v1/study/notes/{chapter.id}/related", headers=headers)
    assert related.status_code == 200
    assert related.json()["data"]["status"] in {"vector", "chapter_fallback"}
    assert related.json()["data"]["textbook_chunks"]

    activated = client.post(f"/api/v1/study/reviews/{chapter.id}/activate", headers=headers)
    assert activated.status_code == 200
    assert activated.json()["data"]["interval_days"] == 1

    completed = client.post(f"/api/v1/study/reviews/{chapter.id}/complete", headers=headers)
    assert completed.status_code == 200
    assert completed.json()["data"]["interval_days"] == 2

    deleted = client.delete(f"/api/v1/study/notes/{saved.json()['data']['id']}", headers=headers)
    assert deleted.status_code == 200
    assert client.get("/api/v1/study/notes", headers=headers).json()["data"] == []


def test_review_question_loop(client: TestClient, db: Session) -> None:
    user = User(username="review_student", password_hash=hash_password("secure-pass-123"), role="student")
    course = Course(name="习概", description="测试")
    db.add_all([user, course]); db.flush()
    chapter = Chapter(course_id=course.id, title="第一章", content="核心概念、主要观点与现实意义。", sort_order=1)
    db.add(chapter); db.commit()
    headers = {"Authorization": f"Bearer {create_access_token(str(user.id))}"}

    client.put(f"/api/v1/study/notes/{chapter.id}", headers=headers, json={"content": "我理解本章的核心概念与现实意义。"})
    created = client.post(f"/api/v1/study/reviews/{chapter.id}/questions", headers=headers)
    assert created.status_code == 200
    questions = created.json()["data"]
    assert len(questions) == 3
    for item in questions:
        answer = client.post(f"/api/v1/study/reviews/questions/{item['id']}/answer", headers=headers,
                             json={"answer": "本题围绕核心概念、主要观点和现实意义进行分析，并说明它们之间的逻辑关系。"})
        assert answer.status_code == 200
    assert answer.json()["data"]["completed"] is True


def test_note_ai_chat_history_is_private(client: TestClient, db: Session) -> None:
    user = User(username="chat_student", password_hash=hash_password("secure-pass-123"), role="student")
    course = Course(name="习概", description="测试")
    db.add_all([user, course]); db.flush()
    chapter = Chapter(course_id=course.id, title="第一章", content="教材正文", sort_order=1)
    db.add(chapter); db.commit()
    headers = {"Authorization": f"Bearer {create_access_token(str(user.id))}"}

    saved = client.post("/api/v1/study/chat-history", headers=headers, json={
        "course_id": course.id, "chapter_id": chapter.id, "question": "本章主旨是什么？",
        "answer": "本章围绕教材主题展开。", "model": "test-model", "sources": [],
    })
    assert saved.status_code == 200
    assert [item["role"] for item in saved.json()["data"]] == ["user", "assistant"]
    history = client.get(f"/api/v1/study/chat-history/{chapter.id}", headers=headers)
    assert history.status_code == 200
    assert len(history.json()["data"]) == 2


def test_news_can_recommend_chapter_and_append_study_note(client: TestClient, db: Session) -> None:
    user = User(username="news_note_student", password_hash=hash_password("secure-pass-123"), role="student")
    course = Course(name="习概", description="测试")
    db.add_all([user, course]); db.flush()
    chapter_one = Chapter(course_id=course.id, title="第一章", content="新时代坚持和发展中国特色社会主义。", sort_order=1)
    chapter_two = Chapter(course_id=course.id, title="生态文明建设", content="绿水青山就是金山银山，推动绿色发展和美丽中国建设。", sort_order=2)
    news = NewsItem(title="推进绿色低碳发展", summary="多地推进生态文明建设和绿色转型。", source_name="测试媒体",
                    source_url="https://example.com/rss", article_url="https://example.com/news/green")
    db.add_all([chapter_one, chapter_two, news]); db.commit()
    headers = {"Authorization": f"Bearer {create_access_token(str(user.id))}"}

    related = client.get(f"/api/v1/current-affairs/{news.id}/textbook-relations", headers=headers,
                         params={"course_id": course.id})
    assert related.status_code == 200
    assert related.json()["data"][0]["chapter_id"] == chapter_two.id

    saved = client.post(f"/api/v1/current-affairs/{news.id}/study-note", headers=headers, json={
        "chapter_id": chapter_two.id,
        "content": "# 事件概览\n推进绿色低碳发展。\n# 教材关联\n联系生态文明建设。",
        "textbook_relation": "生态文明建设 · 正文第 1 段",
        "mode": "create",
    })
    assert saved.status_code == 200
    note = client.get(f"/api/v1/study/notes/{chapter_two.id}", headers=headers).json()["data"]
    assert "时政研学：推进绿色低碳发展" in note["content"]
    assert "https://example.com/news/green" in note["content"]

    appended = client.post(f"/api/v1/current-affairs/{news.id}/study-note", headers=headers, json={
        "chapter_id": chapter_two.id,
        "content": "补充后的个人研学内容。",
        "textbook_relation": "生态文明建设",
        "mode": "append",
    })
    assert appended.status_code == 200
    assert appended.json()["data"]["appended"] is True

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.models.chapter import Chapter
from app.models.course import Course
from app.models.user import User


def test_note_and_review_plan(client: TestClient, db: Session) -> None:
    user = User(username="note_student", password_hash=hash_password("secure-pass-123"), role="student")
    course = Course(name="习概", description="测试")
    db.add_all([user, course]); db.flush()
    chapter = Chapter(course_id=course.id, title="第一章", content="教材正文", sort_order=1)
    db.add(chapter); db.commit()
    headers = {"Authorization": f"Bearer {create_access_token(str(user.id))}"}

    saved = client.put(f"/api/v1/study/notes/{chapter.id}", headers=headers, json={"content": "我的专题笔记"})
    assert saved.status_code == 200
    assert saved.json()["data"]["content"] == "我的专题笔记"

    listed = client.get("/api/v1/study/notes", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["data"][0]["chapter_title"] == "第一章"

    activated = client.post(f"/api/v1/study/reviews/{chapter.id}/activate", headers=headers)
    assert activated.status_code == 200
    assert activated.json()["data"]["interval_days"] == 1

    completed = client.post(f"/api/v1/study/reviews/{chapter.id}/complete", headers=headers)
    assert completed.status_code == 200
    assert completed.json()["data"]["interval_days"] == 2

    deleted = client.delete(f"/api/v1/study/notes/{saved.json()['data']['id']}", headers=headers)
    assert deleted.status_code == 200
    assert client.get("/api/v1/study/notes", headers=headers).json()["data"] == []


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

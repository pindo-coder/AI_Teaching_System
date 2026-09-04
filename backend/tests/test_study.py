from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.models.chapter import Chapter
from app.models.course import Course
from app.models.user import User
from app.models.news_item import NewsItem
from app.models.learning_task import LearningEvent


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


def test_long_note_save_is_not_blocked_by_learning_event_payload(client: TestClient, db: Session) -> None:
    user = User(username="long_note_student", password_hash=hash_password("secure-pass-123"), role="student")
    course = Course(name="习概", description="测试")
    db.add_all([user, course]); db.flush()
    chapter = Chapter(course_id=course.id, title="第一章", content="教材正文", sort_order=1)
    db.add(chapter); db.commit()
    headers = {"Authorization": f"Bearer {create_access_token(str(user.id))}"}
    content = "核心观点" * 2_000

    saved = client.put(f"/api/v1/study/notes/{chapter.id}", headers=headers, json={"content": content})

    assert saved.status_code == 200
    assert saved.json()["data"]["content"] == content
    event = db.query(LearningEvent).filter_by(user_id=user.id, chapter_id=chapter.id, event_type="note_saved").one()
    assert event.event_data == {"content_length": len(content)}


def test_textbook_annotations_are_private_and_support_crud(client: TestClient, db: Session) -> None:
    first_user = User(username="annotation_student", password_hash=hash_password("secure-pass-123"), role="student")
    second_user = User(username="annotation_outsider", password_hash=hash_password("secure-pass-123"), role="student")
    course = Course(name="习概", description="测试")
    db.add_all([first_user, second_user, course]); db.flush()
    chapter = Chapter(
        course_id=course.id,
        title="第一章",
        content="本专题教材正文用于说明核心概念、主要观点和实践要求。",
        sort_order=1,
    )
    db.add(chapter); db.commit()
    first_headers = {"Authorization": f"Bearer {create_access_token(str(first_user.id))}"}
    second_headers = {"Authorization": f"Bearer {create_access_token(str(second_user.id))}"}

    created = client.post(
        f"/api/v1/study/textbook-annotations/chapters/{chapter.id}",
        headers=first_headers,
        json={
            "block_index": 0,
            "start_offset": 10,
            "end_offset": 14,
            "selected_text": "核心概念",
            "prefix_text": "教材正文用于说明",
            "suffix_text": "、主要观点和实践要求。",
            "annotation_type": "concept",
            "comment": "注意概念之间的关系",
        },
    )
    assert created.status_code == 201
    annotation = created.json()["data"]
    assert annotation["course_id"] == course.id
    assert annotation["annotation_type"] == "concept"
    assert len(annotation["chapter_content_hash"]) == 64

    listed = client.get(
        f"/api/v1/study/textbook-annotations/chapters/{chapter.id}",
        headers=first_headers,
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["data"]] == [annotation["id"]]
    assert client.get(
        f"/api/v1/study/textbook-annotations/chapters/{chapter.id}",
        headers=second_headers,
    ).json()["data"] == []

    overlapping = client.post(
        f"/api/v1/study/textbook-annotations/chapters/{chapter.id}",
        headers=first_headers,
        json={
            "block_index": 0,
            "start_offset": 11,
            "end_offset": 15,
            "selected_text": "核心概念",
            "annotation_type": "key_point",
        },
    )
    assert overlapping.status_code == 409

    updated = client.patch(
        f"/api/v1/study/textbook-annotations/{annotation['id']}",
        headers=first_headers,
        json={"annotation_type": "question", "comment": "为什么这是核心概念？"},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["annotation_type"] == "question"
    assert updated.json()["data"]["comment"] == "为什么这是核心概念？"
    assert client.patch(
        f"/api/v1/study/textbook-annotations/{annotation['id']}",
        headers=second_headers,
        json={"comment": "越权修改"},
    ).status_code == 404

    assert client.delete(
        f"/api/v1/study/textbook-annotations/{annotation['id']}",
        headers=second_headers,
    ).status_code == 404
    assert client.delete(
        f"/api/v1/study/textbook-annotations/{annotation['id']}",
        headers=first_headers,
    ).status_code == 200


def test_textbook_annotation_rejects_text_outside_chapter(client: TestClient, db: Session) -> None:
    user = User(username="invalid_annotation", password_hash=hash_password("secure-pass-123"), role="student")
    course = Course(name="习概", description="测试")
    db.add_all([user, course]); db.flush()
    chapter = Chapter(course_id=course.id, title="第一章", content="真实教材正文。", sort_order=1)
    db.add(chapter); db.commit()
    headers = {"Authorization": f"Bearer {create_access_token(str(user.id))}"}

    response = client.post(
        f"/api/v1/study/textbook-annotations/chapters/{chapter.id}",
        headers=headers,
        json={
            "block_index": 0,
            "start_offset": 0,
            "end_offset": 4,
            "selected_text": "伪造的文字",
            "annotation_type": "key_point",
        },
    )
    assert response.status_code == 400


def test_review_question_loop(client: TestClient, db: Session, monkeypatch) -> None:
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
        answer_data = answer.json()["data"]
        assert answer_data["ai_reference_answer"]
        assert answer_data["reference_knowledge_points"]
        duplicate = client.post(f"/api/v1/study/reviews/questions/{item['id']}/answer", headers=headers,
                                json={"answer": "重复提交用于恢复前端切题状态。"})
        assert duplicate.status_code == 200
        assert "恢复本次练习进度" in duplicate.json()["data"]["feedback"]
    assert answer.json()["data"]["completed"] is True
    references = client.post(
        f"/api/v1/study/reviews/{chapter.id}/references",
        headers=headers,
        json={"practice_ids": [item["id"] for item in questions]},
    )
    assert references.status_code == 200
    reference_data = references.json()["data"]
    assert {item["practice_id"] for item in reference_data} == {item["id"] for item in questions}
    assert all(item["ai_reference_answer"] for item in reference_data)
    assert all(item["reference_knowledge_points"] for item in reference_data)
    assert len({item["ai_reference_answer"] for item in reference_data}) == len(questions)
    from app.services.ai_service import AiService
    monkeypatch.setattr(AiService, "assist", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("cached references must not call AI")))
    cached_references = client.post(
        f"/api/v1/study/reviews/{chapter.id}/references",
        headers=headers,
        json={"practice_ids": [item["id"] for item in questions]},
    )
    assert cached_references.status_code == 200
    assert cached_references.json()["data"] == reference_data
    latest_result = client.get(f"/api/v1/study/reviews/{chapter.id}/latest-result", headers=headers)
    assert latest_result.status_code == 200
    latest_data = latest_result.json()["data"]
    assert [item["practice_id"] for item in latest_data] == [item["id"] for item in questions]
    assert all(item["student_answer"] for item in latest_data)
    assert all(item["reference_generated"] for item in latest_data)
    assert all(item["ai_reference_answer"] for item in latest_data)
    saved_to_notes = client.post(
        f"/api/v1/study/reviews/{chapter.id}/save-to-notes",
        headers=headers,
        json={"practice_ids": [item["id"] for item in questions]},
    )
    assert saved_to_notes.status_code == 200
    note_content = saved_to_notes.json()["data"]["content"]
    assert "本章练习记录" in note_content
    assert "我的作答" in note_content
    assert "AI 参考答案" in note_content
    assert "参考知识点" in note_content
    duplicate_save = client.post(
        f"/api/v1/study/reviews/{chapter.id}/save-to-notes",
        headers=headers,
        json={"practice_ids": [item["id"] for item in questions]},
    )
    assert duplicate_save.status_code == 200
    assert duplicate_save.json()["data"]["content"] == note_content
    task_summary = client.get(
        "/api/v1/learning/task-points",
        headers=headers,
        params={
            "course_id": course.id,
            "chapter_id": chapter.id,
            "learning_stage": "exam",
        },
    )
    quiz_task = next(
        item for item in task_summary.json()["data"]["tasks"]
        if item["task_type"] == "exam_question"
    )
    assert quiz_task["status"] == "completed"


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

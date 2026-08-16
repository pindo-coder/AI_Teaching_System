from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.models.user import User


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


def test_global_discussion_basic_lifecycle_and_permissions(client: TestClient, db: Session) -> None:
    student = User(username="discussion_student", identity_no="D-S1", password_hash=hash_password("secure-pass-123"), role="student", approval_status="approved")
    teacher = User(username="discussion_teacher", identity_no="D-T1", password_hash=hash_password("secure-pass-123"), role="teacher", approval_status="approved")
    admin = User(username="discussion_admin", identity_no="D-A1", password_hash=hash_password("secure-pass-123"), role="admin", approval_status="approved")
    db.add_all([student, teacher, admin])
    db.commit()

    created = client.post("/api/v1/classroom/discussions", headers=_headers(student), json={
        "title": "1", "content": "全体讨论内容",
    })
    assert created.status_code == 201, created.text
    thread = created.json()["data"]
    assert thread["teaching_class_id"] is None
    assert thread["course_id"] is None
    assert thread["chapter_id"] is None
    assert thread["created_time"].endswith("Z")
    assert thread["updated_time"].endswith("Z")

    first_reply = client.post(
        f"/api/v1/classroom/discussions/{thread['id']}/replies",
        headers=_headers(teacher), json={"content": "教师回复"},
    )
    assert first_reply.status_code == 201
    assert first_reply.json()["data"]["created_time"].endswith("Z")
    assert first_reply.json()["data"]["updated_time"].endswith("Z")
    first_reply_id = first_reply.json()["data"]["id"]
    child_reply = client.post(
        f"/api/v1/classroom/discussions/{thread['id']}/replies",
        headers=_headers(student),
        json={"content": "回复教师", "parent_reply_id": first_reply_id},
    )
    assert child_reply.status_code == 201
    assert child_reply.json()["data"]["parent_reply_id"] == first_reply_id

    updated = client.patch(
        f"/api/v1/classroom/discussions/{thread['id']}", headers=_headers(student),
        json={"title": "更新后的标题", "content": "更新后的内容"},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["title"] == "更新后的标题"

    # 普通教师不能管理面向全体的讨论；管理员可以。
    assert client.post(
        f"/api/v1/classroom/discussions/{thread['id']}/pin", headers=_headers(teacher),
    ).status_code == 403
    assert client.post(
        f"/api/v1/classroom/discussions/{thread['id']}/pin", headers=_headers(admin),
    ).status_code == 200

    deleted_reply = client.delete(
        f"/api/v1/classroom/discussions/replies/{child_reply.json()['data']['id']}",
        headers=_headers(student),
    )
    assert deleted_reply.status_code == 200
    replies = client.get(
        f"/api/v1/classroom/discussions/{thread['id']}/replies", headers=_headers(student),
    ).json()["data"]
    assert replies[-1]["status"] == "deleted"
    assert replies[-1]["content"] == "该回贴已删除"

    assert client.delete(
        f"/api/v1/classroom/discussions/{thread['id']}", headers=_headers(student),
    ).status_code == 200
    assert client.get("/api/v1/classroom/discussions", headers=_headers(student)).json()["data"] == []

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.models.user import User


def test_register_login_and_current_user(client: TestClient) -> None:
    register = client.post(
        "/api/v1/auth/register",
        json={"username": "student01", "password": "secure-pass-123", "role": "student", "identity_no": "S20260001"},
    )
    assert register.status_code == 201
    assert register.json()["data"]["role"] == "student"

    duplicate = client.post(
        "/api/v1/auth/register",
        json={"username": "student01b", "password": "secure-pass-123", "role": "student", "identity_no": "S20260001"},
    )
    assert duplicate.status_code == 409

    login = client.post(
        "/api/v1/auth/login",
        json={"username": "student01", "password": "secure-pass-123"},
    )
    assert login.status_code == 200
    token = login.json()["data"]["access_token"]

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["data"]["username"] == "student01"


def test_protected_endpoint_rejects_anonymous_user(client: TestClient) -> None:
    response = client.get("/api/v1/courses")
    assert response.status_code == 401
    assert response.json()["success"] is False
    assert response.json()["error_code"] == "HTTP_401"
    assert response.headers["X-Request-ID"]


def test_teacher_registration_requires_unique_staff_number(client: TestClient) -> None:
    teacher = client.post(
        "/api/v1/auth/register",
        json={"username": "teacher01", "password": "secure-pass-123", "role": "teacher", "identity_no": "T20260001"},
    )
    assert teacher.status_code == 201
    assert teacher.json()["data"]["role"] == "teacher"
    assert teacher.json()["data"]["identity_no"] == "T20260001"
    assert teacher.json()["data"]["approval_status"] == "pending"

    duplicate_identity = client.post(
        "/api/v1/auth/register",
        json={"username": "teacher02", "password": "secure-pass-123", "role": "teacher", "identity_no": "T20260001"},
    )
    assert duplicate_identity.status_code == 409


def test_pending_teacher_can_login_and_view_account_status(client: TestClient, db: Session) -> None:
    teacher = User(
        username="pending_teacher",
        identity_no="T-PENDING",
        password_hash=hash_password("secure-pass-123"),
        role="teacher",
        approval_status="pending",
    )
    db.add(teacher)
    db.commit()

    login = client.post(
        "/api/v1/auth/login",
        json={"username": teacher.username, "password": "secure-pass-123"},
    )
    assert login.status_code == 200, login.text
    token = login.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["data"]["approval_status"] == "pending"
    assert client.get("/api/v1/assignments", headers=headers).status_code == 403
    assert client.get("/api/v1/courses", headers=headers).status_code == 403
    assert client.get("/api/v1/ai/media/capabilities", headers=headers).status_code == 403
    assert client.get("/api/v1/current-affairs", headers=headers).status_code == 403
    assert client.post(
        "/api/v1/ai/workspace/stream",
        headers=headers,
        json={"mode": "chat", "role": "teacher", "question": "测试"},
    ).status_code == 403


@pytest.mark.parametrize(
    ("approval_status", "expected_message"),
    [
        ("rejected", "教师账号审核未通过"),
        ("disabled", "教师账号已被禁用"),
    ],
)
def test_blocked_teacher_cannot_login_or_reuse_existing_token(
    client: TestClient,
    db: Session,
    approval_status: str,
    expected_message: str,
) -> None:
    teacher = User(
        username=f"{approval_status}_teacher",
        identity_no=f"T-{approval_status.upper()}",
        password_hash=hash_password("secure-pass-123"),
        role="teacher",
        approval_status="approved",
    )
    db.add(teacher)
    db.commit()
    existing_token = create_access_token(str(teacher.id))
    teacher.approval_status = approval_status
    db.commit()

    login = client.post(
        "/api/v1/auth/login",
        json={"username": teacher.username, "password": "secure-pass-123"},
    )
    assert login.status_code == 403
    assert login.json()["message"] == expected_message

    headers = {"Authorization": f"Bearer {existing_token}"}
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
    assert client.get("/api/v1/courses", headers=headers).status_code == 401

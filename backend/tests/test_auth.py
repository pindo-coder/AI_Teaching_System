import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.core.security import create_access_token, hash_password
from app.models.user import User
from app.services.auth_service import AuthService
from app.services.email_service import EmailService


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


def test_email_verification_and_password_reset_invalidate_old_token(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[str] = []
    monkeypatch.setattr(EmailService, "send", lambda self, **kwargs: sent.append(kwargs["text"]))
    register = client.post(
        "/api/v1/auth/register",
        json={"username": "mail-user", "password": "secure-pass-123", "role": "student",
               "identity_no": "S-MAIL-01", "email": "Mail.User@Example.com"},
    )
    assert register.status_code == 201
    assert len(sent) == 1
    verification_code = re.search(r"(?<!\d)\d{6}(?!\d)", sent[-1]).group(0)
    verified = client.post(
        "/api/v1/auth/email/verification/confirm",
        json={"email": "mail.user@example.com", "code": verification_code},
    )
    assert verified.status_code == 200
    assert verified.json()["data"]["email"] == "mail.user@example.com"

    sent.clear()
    reset_request = client.post("/api/v1/auth/password-reset/request", json={"identifier": "mail-user"})
    assert reset_request.status_code == 202
    assert reset_request.json()["data"]["next_step"] == "email"
    reset_code = re.search(r"(?<!\d)\d{6}(?!\d)", sent[-1]).group(0)
    reset = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"identifier": "mail-user", "code": reset_code, "new_password": "new-secure-pass-456"},
    )
    assert reset.status_code == 200
    assert client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"identifier": "mail-user", "code": reset_code, "new_password": "another-pass-789"},
    ).status_code == 400
    assert client.post("/api/v1/auth/login", json={"username": "mail-user", "password": "new-secure-pass-456"}).status_code == 200


def test_email_verification_code_expires_after_five_failed_attempts(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[str] = []
    monkeypatch.setattr(EmailService, "send", lambda self, **kwargs: sent.append(kwargs["text"]))
    register = client.post(
        "/api/v1/auth/register",
        json={"username": "code-user", "password": "secure-pass-123", "role": "student",
               "identity_no": "S-CODE-01", "email": "code@example.com"},
    )
    assert register.status_code == 201
    for _ in range(5):
        response = client.post(
            "/api/v1/auth/email/verification/confirm",
            json={"email": "code@example.com", "code": "000000"},
        )
        assert response.status_code == 400
    actual_code = re.search(r"(?<!\d)\d{6}(?!\d)", sent[-1]).group(0)
    assert client.post(
        "/api/v1/auth/email/verification/confirm",
        json={"email": "code@example.com", "code": actual_code},
    ).status_code == 400


def test_password_reset_by_unverified_email_sends_verification_code(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[str] = []
    monkeypatch.setattr(EmailService, "send", lambda self, **kwargs: sent.append(kwargs["text"]))
    user = User(
        username="unverified-email", identity_no="S-UNVERIFIED-01", email="unverified@example.com",
        email_hash="placeholder", password_hash=hash_password("old-pass-123"), role="student", approval_status="approved",
    )
    user.email_hash = AuthService.email_hash(user.email)
    db.add(user)
    db.commit()
    response = client.post(
        "/api/v1/auth/password-reset/request", json={"identifier": "UNVERIFIED@EXAMPLE.COM"}
    )
    assert response.status_code == 202
    assert response.json()["data"]["next_step"] == "verify_email"
    assert re.search(r"(?<!\d)\d{6}(?!\d)", sent[-1])


def test_admin_temporary_password_forces_change_and_invalidates_session(client: TestClient, db: Session) -> None:
    admin = User(username="admin", password_hash=hash_password("admin-pass-123"), role="admin", approval_status="approved")
    user = User(username="temp-user", identity_no="S-TEMP-01", password_hash=hash_password("old-pass-123"), role="student", approval_status="approved")
    db.add_all([admin, user]); db.commit()
    admin_login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin-pass-123"})
    admin_headers = {"Authorization": f"Bearer {admin_login.json()['data']['access_token']}"}
    result = client.post(f"/api/v1/auth/users/{user.id}/temporary-password", headers=admin_headers)
    assert result.status_code == 200
    temporary = result.json()["data"]["temporary_password"]
    assert temporary == "12345678"
    login = client.post("/api/v1/auth/login", json={"username": "temp-user", "password": temporary})
    assert login.status_code == 200
    token = login.json()["data"]["access_token"]
    assert login.json()["data"]["user"]["must_change_password"] is True
    changed = client.post("/api/v1/auth/password/change", headers={"Authorization": f"Bearer {token}"}, json={"new_password": "final-pass-456"})
    assert changed.status_code == 200
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_unverified_email_login_is_blocked_and_reset_request_is_visible_to_admin(
    client: TestClient, db: Session
) -> None:
    user = User(
        username="legacy-with-email", identity_no="S-LEGACY-01", email="legacy@example.com",
        email_hash="placeholder", password_hash=hash_password("old-pass-123"), role="student", approval_status="approved",
    )
    admin = User(username="queue-admin", password_hash=hash_password("admin-pass-123"), role="admin", approval_status="approved")
    db.add_all([user, admin]); db.commit()
    assert client.post("/api/v1/auth/login", json={"username": user.username, "password": "old-pass-123"}).status_code == 403
    reset_request = client.post("/api/v1/auth/password-reset/request", json={"identifier": user.username})
    assert reset_request.status_code == 202
    assert reset_request.json()["data"]["next_step"] == "admin"
    admin_login = client.post("/api/v1/auth/login", json={"username": admin.username, "password": "admin-pass-123"})
    headers = {"Authorization": f"Bearer {admin_login.json()['data']['access_token']}"}
    pending = client.get("/api/v1/auth/password-reset/pending", headers=headers)
    assert pending.status_code == 200
    assert pending.json()["data"][0]["username"] == user.username

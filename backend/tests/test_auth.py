from fastapi.testclient import TestClient


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

    duplicate_identity = client.post(
        "/api/v1/auth/register",
        json={"username": "teacher02", "password": "secure-pass-123", "role": "teacher", "identity_no": "T20260001"},
    )
    assert duplicate_identity.status_code == 409

from datetime import datetime

import httpx
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.models.ai_operation import AiCallLog
from app.models.user import User
from app.services.ai_operation_service import decrypt_api_key, encrypt_api_key, mask_api_key


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


def test_ai_operations_are_admin_only_and_do_not_expose_plain_api_key(client: TestClient, db: Session) -> None:
    admin = User(username="ai_admin", password_hash=hash_password("secure-pass-123"), role="admin")
    student = User(username="ai_student_ops", password_hash=hash_password("secure-pass-123"), role="student")
    db.add_all([admin, student])
    db.commit()

    assert client.get("/api/v1/admin/ai-operations/config", headers=_headers(student)).status_code == 403
    response = client.get("/api/v1/admin/ai-operations/config", headers=_headers(admin))
    assert response.status_code == 200
    data = response.json()["data"]
    assert "api_key" not in data
    assert data["source"] == "environment"


def test_ai_call_summary_and_listing(client: TestClient, db: Session) -> None:
    admin = User(username="ai_log_admin", password_hash=hash_password("secure-pass-123"), role="admin")
    user = User(username="ai_log_user", password_hash=hash_password("secure-pass-123"), role="student")
    db.add_all([admin, user])
    db.flush()
    db.add(AiCallLog(
        request_id="test-ai-call-1",
        user_id=user.id,
        feature="learning_assist",
        model_name="test-model",
        status="success",
        streaming=True,
        input_chars=120,
        output_chars=80,
        latency_ms=240,
        started_time=datetime.utcnow(),
        finished_time=datetime.utcnow(),
    ))
    db.commit()

    summary = client.get("/api/v1/admin/ai-operations/summary", headers=_headers(admin))
    assert summary.status_code == 200
    assert summary.json()["data"]["total_24h"] == 1
    assert summary.json()["data"]["success_24h"] == 1

    calls = client.get("/api/v1/admin/ai-operations/calls", headers=_headers(admin))
    assert calls.status_code == 200
    assert calls.json()["data"][0]["username"] == user.username
    assert calls.json()["data"][0]["input_chars"] == 120


def test_ai_api_key_encryption_and_masking() -> None:
    secret = "sk-test-sensitive-value"
    encrypted = encrypt_api_key(secret)
    assert secret not in encrypted
    assert decrypt_api_key(encrypted) == secret
    assert mask_api_key(secret) == "sk-********alue"


def test_admin_can_test_and_activate_runtime_config(client: TestClient, db: Session, monkeypatch) -> None:
    admin = User(username="ai_config_admin", password_hash=hash_password("secure-pass-123"), role="admin")
    db.add(admin)
    db.commit()

    def successful_post(url: str, **kwargs):
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={"choices": [{"message": {"role": "assistant", "content": "OK"}}]},
        )

    monkeypatch.setattr("app.services.ai_operation_service.httpx.post", successful_post)
    payload = {
        "base_url": "https://model.example/v1",
        "model_name": "teacher-model-v2",
        "api_key": "sk-runtime-secret",
        "temperature": 0.2,
        "timeout_seconds": 60,
        "streaming_enabled": True,
    }
    tested = client.post("/api/v1/admin/ai-operations/config/test", headers=_headers(admin), json=payload)
    assert tested.status_code == 200

    activated = client.put("/api/v1/admin/ai-operations/config", headers=_headers(admin), json=payload)
    assert activated.status_code == 200
    data = activated.json()["data"]
    assert data["source"] == "database"
    assert data["model_name"] == "teacher-model-v2"
    assert data["api_key_masked"] == "sk-********cret"
    assert "sk-runtime-secret" not in activated.text

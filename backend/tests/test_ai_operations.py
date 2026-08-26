from datetime import timedelta
import socket
from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.core.time import utc_now
from app.models.ai_operation import AiCallLog, AiProviderConfig
from app.models.user import User
from app.services.ai_operation_service import (
    AiCallAuditHandler,
    AiProviderConfigService,
    RuntimeLlmConfig,
    build_chat_model,
    decrypt_api_key,
    encrypt_api_key,
    mask_api_key,
)


@pytest.fixture(autouse=True)
def public_provider_dns(monkeypatch):
    def resolve_public(host: str, port: int, **kwargs):
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("8.8.8.8", port),
            )
        ]

    monkeypatch.setattr(
        "app.services.ai_operation_service.socket.getaddrinfo",
        resolve_public,
    )


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
        prompt_tokens=120,
        completion_tokens=36,
        latency_ms=240,
        started_time=utc_now(),
        finished_time=utc_now(),
    ))
    db.commit()

    summary = client.get("/api/v1/admin/ai-operations/summary", headers=_headers(admin))
    assert summary.status_code == 200
    assert summary.json()["data"]["total_24h"] == 1
    assert summary.json()["data"]["success_24h"] == 1
    assert summary.json()["data"]["prompt_tokens_24h"] == 120
    assert summary.json()["data"]["completion_tokens_24h"] == 36
    assert summary.json()["data"]["total_tokens_24h"] == 156
    assert summary.json()["data"]["tokenized_calls_24h"] == 1
    assert summary.json()["data"]["model_token_usage_24h"] == [{
        "model_name": "test-model",
        "call_count": 1,
        "tokenized_calls": 1,
        "prompt_tokens": 120,
        "completion_tokens": 36,
        "total_tokens": 156,
    }]

    calls = client.get("/api/v1/admin/ai-operations/calls", headers=_headers(admin))
    assert calls.status_code == 200
    assert calls.json()["data"][0]["username"] == user.username
    assert calls.json()["data"][0]["input_chars"] == 120


def test_ai_summary_keeps_missing_provider_usage_distinct_from_zero(
    client: TestClient,
    db: Session,
) -> None:
    admin = User(username="ai_token_admin", password_hash=hash_password("secure-pass-123"), role="admin")
    db.add(admin)
    db.flush()
    db.add(AiCallLog(
        request_id="test-ai-call-without-usage",
        user_id=admin.id,
        feature="learning_assist",
        model_name="provider-without-usage",
        status="success",
        streaming=False,
        input_chars=10,
        output_chars=5,
        prompt_tokens=None,
        completion_tokens=None,
        latency_ms=20,
        started_time=utc_now(),
        finished_time=utc_now(),
    ))
    db.commit()

    response = client.get("/api/v1/admin/ai-operations/summary", headers=_headers(admin))
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total_24h"] == 1
    assert data["tokenized_calls_24h"] == 0
    assert data["prompt_tokens_24h"] is None
    assert data["completion_tokens_24h"] is None
    assert data["total_tokens_24h"] is None
    assert data["model_token_usage_24h"] == [{
        "model_name": "provider-without-usage",
        "call_count": 1,
        "tokenized_calls": 0,
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
    }]


def test_ai_summary_groups_token_usage_by_model_with_stable_null_last_order(
    client: TestClient,
    db: Session,
) -> None:
    admin = User(username="ai_model_usage_admin", password_hash=hash_password("secure-pass-123"), role="admin")
    db.add(admin)
    db.flush()
    now = utc_now()
    rows = [
        ("model-b", 25, 25, now),
        ("model-a", 20, 30, now),
        ("model-a", None, None, now),
        ("model-c", 0, 0, now),
        ("model-z", None, None, now),
        ("old-model", 1000, 1000, now - timedelta(hours=25)),
    ]
    for index, (model_name, prompt_tokens, completion_tokens, started_time) in enumerate(rows):
        db.add(AiCallLog(
            request_id=f"model-usage-{index}",
            user_id=admin.id,
            feature="learning_assist",
            model_name=model_name,
            status="success",
            streaming=False,
            input_chars=10,
            output_chars=5,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=20,
            started_time=started_time,
            finished_time=started_time,
        ))
    db.commit()

    response = client.get("/api/v1/admin/ai-operations/summary", headers=_headers(admin))
    assert response.status_code == 200
    usage = response.json()["data"]["model_token_usage_24h"]
    assert [item["model_name"] for item in usage] == [
        "model-a",
        "model-b",
        "model-c",
        "model-z",
    ]
    assert usage[0] == {
        "model_name": "model-a",
        "call_count": 2,
        "tokenized_calls": 1,
        "prompt_tokens": 20,
        "completion_tokens": 30,
        "total_tokens": 50,
    }
    assert usage[-1]["call_count"] == 1
    assert usage[-1]["tokenized_calls"] == 0
    assert usage[-1]["total_tokens"] is None


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


def _dashscope_payload(api_key: str = "sk-shared-runtime-secret") -> dict:
    compatible = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    return {
        "provider_name": "dashscope",
        "api_key": api_key,
        "capabilities": {
            "text": {
                "enabled": True,
                "base_url": compatible,
                "model_name": "qwen-plus",
                "timeout_seconds": 60,
                "temperature": 0.2,
                "streaming_enabled": True,
            },
            "embedding": {
                "enabled": True,
                "base_url": compatible,
                "model_name": "text-embedding-v4",
                "timeout_seconds": 60,
                "dimensions": 1024,
                "streaming_enabled": False,
            },
            "vision": {
                "enabled": True,
                "base_url": compatible,
                "model_name": "qwen3-vl-plus",
                "timeout_seconds": 90,
                "streaming_enabled": False,
            },
            "asr": {
                "enabled": True,
                "base_url": compatible,
                "model_name": "qwen3-asr-flash",
                "timeout_seconds": 120,
                "streaming_enabled": False,
            },
            "image_generation": {
                "enabled": True,
                "base_url": "https://dashscope.aliyuncs.com/api/v1",
                "model_name": "wan2.7-image-pro",
                "timeout_seconds": 180,
                "streaming_enabled": False,
            },
        },
    }


def test_unified_presets_and_configs_are_admin_only_and_never_return_plain_key(
    client: TestClient,
    db: Session,
) -> None:
    admin = User(username="ai_all_admin", password_hash=hash_password("secure-pass-123"), role="admin")
    student = User(username="ai_all_student", password_hash=hash_password("secure-pass-123"), role="student")
    db.add_all([admin, student])
    db.commit()

    path = "/api/v1/admin/ai-operations/config/presets"
    assert client.get(path, headers=_headers(student)).status_code == 403
    response = client.get(path, headers=_headers(admin))
    assert response.status_code == 200
    preset = response.json()["data"]["presets"][0]
    assert preset["id"] == "dashscope"
    assert set(preset["capabilities"]) == {
        "text",
        "embedding",
        "vision",
        "asr",
        "image_generation",
    }
    assert preset["capabilities"]["embedding"]["dimensions"] == 1024
    assert preset["capabilities"]["image_generation"]["model_name"] == "wan2.7-image-pro"
    assert "api_key" not in response.text

    current = client.get("/api/v1/admin/ai-operations/config/all", headers=_headers(admin))
    assert current.status_code == 200
    assert set(current.json()["data"]["capabilities"]) == set(preset["capabilities"])
    assert "api_key\":" not in current.text


def test_unified_test_calls_four_low_cost_endpoints_and_does_not_generate_image(
    client: TestClient,
    db: Session,
    monkeypatch,
) -> None:
    admin = User(username="ai_test_all_admin", password_hash=hash_password("secure-pass-123"), role="admin")
    db.add(admin)
    db.commit()
    calls: list[tuple[str, dict]] = []

    def successful_post(url: str, **kwargs):
        calls.append((url, kwargs))
        body = kwargs.get("json") or {}
        if url.endswith("/embeddings"):
            data = {"data": [{"index": 0, "embedding": [0.0] * 1024}]}
        else:
            data = {"choices": [{"message": {"role": "assistant", "content": "OK"}}]}
        return httpx.Response(200, request=httpx.Request("POST", url), json=data)

    monkeypatch.setattr("app.services.ai_operation_service.httpx.post", successful_post)
    payload = _dashscope_payload()
    response = client.post(
        "/api/v1/admin/ai-operations/config/all/test",
        headers=_headers(admin),
        json=payload,
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(calls) == 4
    assert sum(url.endswith("/chat/completions") for url, _ in calls) == 3
    assert sum(url.endswith("/embeddings") for url, _ in calls) == 1
    assert all("multimodal-generation" not in url for url, _ in calls)
    assert data["capabilities"]["image_generation"]["skipped"] is True
    assert "未实际出图" in data["capabilities"]["image_generation"]["message"]
    assert all(item["success"] for item in data["capabilities"].values())
    assert payload["api_key"] not in response.text


def test_unified_config_prefers_capability_keys_and_returns_only_masks(
    client: TestClient,
    db: Session,
    monkeypatch,
) -> None:
    admin = User(username="ai_per_capability_key_admin", password_hash=hash_password("secure-pass-123"), role="admin")
    db.add(admin)
    db.commit()
    authorizations: dict[str, str] = {}

    def successful_post(url: str, **kwargs):
        model = (kwargs.get("json") or {}).get("model", "")
        authorizations[model] = kwargs["headers"]["Authorization"]
        data = (
            {"data": [{"index": 0, "embedding": [0.0] * 8}]}
            if url.endswith("/embeddings")
            else {"choices": [{"message": {"role": "assistant", "content": "OK"}}]}
        )
        return httpx.Response(200, request=httpx.Request("POST", url), json=data)

    monkeypatch.setattr("app.services.ai_operation_service.httpx.post", successful_post)
    shared_key = "sk-shared-credential-not-used"
    text_key = "sk-deepseek-text-credential"
    embedding_key = "sk-dashscope-embedding-credential"
    payload = {
        "provider_name": "custom",
        "api_key": shared_key,
        "capabilities": {
            "text": {
                "enabled": True,
                "base_url": "https://api.deepseek.com",
                "model_name": "deepseek-chat",
                "api_key": text_key,
                "timeout_seconds": 60,
                "temperature": 0.2,
                "streaming_enabled": True,
            },
            "embedding": {
                "enabled": True,
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "model_name": "text-embedding-v4",
                "api_key": embedding_key,
                "timeout_seconds": 60,
                "dimensions": 8,
            },
        },
    }

    response = client.put(
        "/api/v1/admin/ai-operations/config/all",
        headers=_headers(admin),
        json=payload,
    )
    assert response.status_code == 200
    assert authorizations == {
        "deepseek-chat": f"Bearer {text_key}",
        "text-embedding-v4": f"Bearer {embedding_key}",
    }
    assert text_key not in response.text
    assert embedding_key not in response.text
    assert shared_key not in response.text
    configs = response.json()["data"]["capabilities"]
    assert configs["text"]["config"]["api_key_masked"] == mask_api_key(text_key)
    assert configs["embedding"]["config"]["api_key_masked"] == mask_api_key(embedding_key)

    rows = db.query(AiProviderConfig).filter(AiProviderConfig.is_active.is_(True)).all()
    stored = {row.capability: decrypt_api_key(row.api_key_encrypted) for row in rows}
    assert stored == {"text": text_key, "embedding": embedding_key}


def test_unified_activation_is_partial_and_disabled_row_overrides_environment(
    client: TestClient,
    db: Session,
    monkeypatch,
) -> None:
    admin = User(username="ai_partial_admin", password_hash=hash_password("secure-pass-123"), role="admin")
    db.add(admin)
    db.flush()
    previous_vision = AiProviderConfig(
        capability="vision",
        provider_name="dashscope",
        enabled=True,
        base_url="https://old.example/v1",
        model_name="old-vision",
        api_key_encrypted=encrypt_api_key("sk-old-vision"),
        temperature=0,
        timeout_seconds=30,
        streaming_enabled=False,
        is_active=True,
        created_by=admin.id,
        last_test_status="passed",
    )
    db.add(previous_vision)
    db.commit()
    previous_vision_id = previous_vision.id

    def partial_post(url: str, **kwargs):
        model = (kwargs.get("json") or {}).get("model")
        if model == "qwen3-vl-plus":
            return httpx.Response(401, request=httpx.Request("POST", url), json={"error": "denied"})
        if url.endswith("/embeddings"):
            data = {"data": [{"index": 0, "embedding": [0.0] * 1024}]}
        else:
            data = {"choices": [{"message": {"role": "assistant", "content": "OK"}}]}
        return httpx.Response(200, request=httpx.Request("POST", url), json=data)

    monkeypatch.setattr("app.services.ai_operation_service.httpx.post", partial_post)
    monkeypatch.setattr(settings, "ai_asr_enabled", True)
    monkeypatch.setattr(settings, "ai_asr_api_key", "sk-environment-asr")
    payload = _dashscope_payload("sk-new-shared-secret")
    payload["capabilities"]["asr"]["enabled"] = False
    payload["capabilities"]["asr"]["base_url"] = ""
    payload["capabilities"]["asr"]["model_name"] = ""
    response = client.put(
        "/api/v1/admin/ai-operations/config/all",
        headers=_headers(admin),
        json=payload,
    )
    assert response.status_code == 200
    result = response.json()["data"]["capabilities"]
    assert result["text"]["success"] is True
    assert result["vision"]["success"] is False
    assert result["vision"]["kept_previous"] is True
    assert result["vision"]["config"]["id"] == previous_vision_id
    assert result["asr"]["success"] is True
    assert result["asr"]["skipped"] is True
    assert result["asr"]["config"]["enabled"] is False
    assert "sk-new-shared-secret" not in response.text
    assert "sk-old-vision" not in response.text

    runtime_vision = AiProviderConfigService.resolve_capability("vision", db)
    runtime_asr = AiProviderConfigService.resolve_capability("asr", db)
    assert runtime_vision.config_id == previous_vision_id
    assert runtime_vision.model_name == "old-vision"
    assert runtime_asr.source == "database"
    assert runtime_asr.enabled is False
    assert runtime_asr.api_key is None

    active_rows = db.query(AiProviderConfig).filter(AiProviderConfig.is_active.is_(True)).all()
    assert {row.capability for row in active_rows} == {
        "text",
        "embedding",
        "vision",
        "asr",
        "image_generation",
    }
    for row in active_rows:
        assert "sk-new-shared-secret" not in row.api_key_encrypted


def test_ai_config_rejects_literal_ssrf_targets_and_userinfo(
    client: TestClient,
    db: Session,
    monkeypatch,
) -> None:
    admin = User(username="ai_ssrf_admin", password_hash=hash_password("secure-pass-123"), role="admin")
    db.add(admin)
    db.commit()

    def unexpected_post(*args, **kwargs):
        raise AssertionError("SSRF target must be rejected before an HTTP request")

    monkeypatch.setattr("app.services.ai_operation_service.httpx.post", unexpected_post)
    base_payload = {
        "model_name": "test-model",
        "api_key": "sk-ssrf-test",
        "temperature": 0.2,
        "timeout_seconds": 60,
        "streaming_enabled": True,
    }
    for target in (
        "https://127.0.0.1/v1",
        "https://2130706433/v1",
        "https://169.254.169.254/latest",
        "https://user:password@model.example/v1",
        "https://metadata.google.internal/v1",
    ):
        response = client.post(
            "/api/v1/admin/ai-operations/config/test",
            headers=_headers(admin),
            json={**base_payload, "base_url": target},
        )
        assert response.status_code == 400
        assert "sk-ssrf-test" not in response.text

    plaintext = client.post(
        "/api/v1/admin/ai-operations/config/test",
        headers=_headers(admin),
        json={**base_payload, "base_url": "http://public.example/v1"},
    )
    assert plaintext.status_code == 422
    assert "https://" in plaintext.text


def test_ai_config_rejects_dns_failures_and_any_private_resolution(
    client: TestClient,
    db: Session,
    monkeypatch,
) -> None:
    admin = User(username="ai_dns_admin", password_hash=hash_password("secure-pass-123"), role="admin")
    db.add(admin)
    db.commit()

    def controlled_dns(host: str, port: int, **kwargs):
        if host == "missing.example":
            raise socket.gaierror("not found")
        addresses = {
            "private.example": ["127.0.0.1"],
            "mixed.example": ["8.8.8.8", "10.0.0.8"],
            "127-0-0-1.nip.io": ["127.0.0.1"],
        }[host]
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port))
            for address in addresses
        ]

    def unexpected_post(*args, **kwargs):
        raise AssertionError("unsafe DNS result must be rejected before HTTP")

    monkeypatch.setattr(
        "app.services.ai_operation_service.socket.getaddrinfo",
        controlled_dns,
    )
    monkeypatch.setattr("app.services.ai_operation_service.httpx.post", unexpected_post)
    for hostname in (
        "missing.example",
        "private.example",
        "mixed.example",
        "127-0-0-1.nip.io",
    ):
        response = client.post(
            "/api/v1/admin/ai-operations/config/test",
            headers=_headers(admin),
            json={
                "base_url": f"https://{hostname}/v1",
                "model_name": "test-model",
                "api_key": "sk-dns-test",
                "temperature": 0.2,
                "timeout_seconds": 60,
                "streaming_enabled": True,
            },
        )
        assert response.status_code == 400
        assert "sk-dns-test" not in response.text


def test_existing_key_is_reused_only_for_the_same_host_and_compatible_provider(
    client: TestClient,
    db: Session,
    monkeypatch,
) -> None:
    admin = User(username="ai_key_scope_admin", password_hash=hash_password("secure-pass-123"), role="admin")
    db.add(admin)
    db.flush()
    secret = "sk-host-scoped-secret"
    db.add(AiProviderConfig(
        capability="text",
        provider_name="custom",
        enabled=True,
        base_url="https://old.example/v1",
        model_name="old-model",
        api_key_encrypted=encrypt_api_key(secret),
        temperature=0.2,
        timeout_seconds=60,
        streaming_enabled=True,
        is_active=True,
        created_by=admin.id,
        last_test_status="passed",
    ))
    db.commit()
    calls: list[dict] = []

    def successful_post(url: str, **kwargs):
        calls.append({"url": url, **kwargs})
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={"choices": [{"message": {"content": "OK"}}]},
        )

    monkeypatch.setattr("app.services.ai_operation_service.httpx.post", successful_post)
    base_payload = {
        "model_name": "new-model",
        "temperature": 0.2,
        "timeout_seconds": 60,
        "streaming_enabled": True,
    }
    same_host = client.post(
        "/api/v1/admin/ai-operations/config/test",
        headers=_headers(admin),
        json={**base_payload, "base_url": "https://old.example/compatible/v1"},
    )
    assert same_host.status_code == 200
    assert calls[-1]["headers"]["Authorization"] == f"Bearer {secret}"

    calls.clear()
    changed_host = client.post(
        "/api/v1/admin/ai-operations/config/test",
        headers=_headers(admin),
        json={**base_payload, "base_url": "https://new.example/v1"},
    )
    assert changed_host.status_code == 400
    assert "重新输入 API Key" in changed_host.text
    assert secret not in changed_host.text
    assert calls == []

    unified_changed_host = client.post(
        "/api/v1/admin/ai-operations/config/all/test",
        headers=_headers(admin),
        json={
            "provider_name": "custom",
            "capabilities": {
                "text": {
                    "enabled": True,
                    "base_url": "https://new.example/v1",
                    "model_name": "new-model",
                    "timeout_seconds": 60,
                    "temperature": 0.2,
                    "streaming_enabled": True,
                }
            },
        },
    )
    assert unified_changed_host.status_code == 200
    unified_result = unified_changed_host.json()["data"]["capabilities"]["text"]
    assert unified_result["success"] is False
    assert "重新输入 API Key" in unified_result["message"]
    assert secret not in unified_changed_host.text
    assert calls == []

    incompatible_provider = client.post(
        "/api/v1/admin/ai-operations/config/all/test",
        headers=_headers(admin),
        json={
            "provider_name": "dashscope",
            "capabilities": {
                "text": {
                    "enabled": True,
                    "base_url": "https://old.example/v1",
                    "model_name": "new-model",
                    "timeout_seconds": 60,
                    "temperature": 0.2,
                    "streaming_enabled": True,
                }
            },
        },
    )
    incompatible_result = incompatible_provider.json()["data"]["capabilities"]["text"]
    assert incompatible_result["success"] is False
    assert "供应商已变化" in incompatible_result["message"]
    assert calls == []


def test_image_generation_requires_wan_host_and_accepts_independent_key(
    client: TestClient,
    db: Session,
) -> None:
    admin = User(username="ai_image_gate_admin", password_hash=hash_password("secure-pass-123"), role="admin")
    db.add(admin)
    db.flush()
    old_image = AiProviderConfig(
        capability="image_generation",
        provider_name="dashscope",
        enabled=True,
        base_url="https://dashscope.aliyuncs.com/api/v1",
        model_name="old-wan",
        api_key_encrypted=encrypt_api_key("sk-old-image"),
        temperature=0,
        timeout_seconds=180,
        streaming_enabled=False,
        is_active=True,
        created_by=admin.id,
        last_test_status="validated",
    )
    db.add(old_image)
    db.commit()
    old_image_id = old_image.id
    image_config = {
        "enabled": True,
        "base_url": "https://image.example/api/v1",
        "model_name": "wan2.7-image-pro",
        "timeout_seconds": 180,
        "streaming_enabled": False,
    }

    wrong_protocol = client.post(
        "/api/v1/admin/ai-operations/config/all/test",
        headers=_headers(admin),
        json={
            "provider_name": "custom",
                "capabilities": {
                    "image_generation": {**image_config, "api_key": "sk-new-image"},
                },
        },
    )
    assert wrong_protocol.status_code == 200
    result = wrong_protocol.json()["data"]["capabilities"]["image_generation"]
    assert result["success"] is False
    assert result["skipped"] is False
    assert "仅支持阿里云百炼 Wan 协议" in result["message"]

    image_config["base_url"] = "https://dashscope.aliyuncs.com/api/v1"
    activated = client.put(
        "/api/v1/admin/ai-operations/config/all",
        headers=_headers(admin),
        json={
            "provider_name": "dashscope",
            "capabilities": {
                "image_generation": {**image_config, "api_key": "sk-new-image"},
            },
        },
    )
    assert activated.status_code == 200
    result = activated.json()["data"]["capabilities"]["image_generation"]
    assert result["success"] is True
    assert result["skipped"] is True
    assert result["config"]["id"] != old_image_id
    assert result["config"]["api_key_masked"] == mask_api_key("sk-new-image")
    assert "sk-new-image" not in activated.text
    active = AiProviderConfigService.active_row(db, "image_generation")
    assert active is not None
    assert decrypt_api_key(active.api_key_encrypted) == "sk-new-image"


def test_embedding_connectivity_uses_model_specific_dimension_rules(
    client: TestClient,
    db: Session,
    monkeypatch,
) -> None:
    admin = User(username="ai_embedding_rule_admin", password_hash=hash_password("secure-pass-123"), role="admin")
    db.add(admin)
    db.commit()
    request_bodies: dict[str, dict] = {}
    returned_dimensions = {
        "text-embedding-v1": 1536,
        "text-embedding-v4": 8,
        "custom-embedding": 7,
    }

    def embedding_post(url: str, **kwargs):
        body = kwargs["json"]
        request_bodies[body["model"]] = body
        dimensions = returned_dimensions[body["model"]]
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={"data": [{"index": 0, "embedding": [0.0] * dimensions}]},
        )

    monkeypatch.setattr("app.services.ai_operation_service.httpx.post", embedding_post)
    cases = (
        ("text-embedding-v1", 1024),
        ("text-embedding-v4", 8),
        ("custom-embedding", 7),
    )
    for model_name, dimensions in cases:
        response = client.post(
            "/api/v1/admin/ai-operations/config/all/test",
            headers=_headers(admin),
            json={
                "provider_name": "dashscope",
                "api_key": "sk-embedding",
                "capabilities": {
                    "embedding": {
                        "enabled": True,
                        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                        "model_name": model_name,
                        "timeout_seconds": 60,
                        "dimensions": dimensions,
                    }
                },
            },
        )
        assert response.status_code == 200
        assert response.json()["data"]["capabilities"]["embedding"]["success"] is True

    assert "dimensions" not in request_bodies["text-embedding-v1"]
    assert request_bodies["text-embedding-v4"]["dimensions"] == 8
    assert "dimensions" not in request_bodies["custom-embedding"]

    activated = client.put(
        "/api/v1/admin/ai-operations/config/all",
        headers=_headers(admin),
        json={
            "provider_name": "dashscope",
            "api_key": "sk-embedding",
            "capabilities": {
                "embedding": {
                    "enabled": True,
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "model_name": "text-embedding-v1",
                    "timeout_seconds": 60,
                    "dimensions": 1024,
                }
            },
        },
    )
    assert activated.status_code == 200
    assert activated.json()["data"]["capabilities"]["embedding"]["config"]["dimensions"] == 1536


def test_ai_connection_error_redacts_api_key(
    client: TestClient,
    db: Session,
    monkeypatch,
) -> None:
    admin = User(username="ai_redaction_admin", password_hash=hash_password("secure-pass-123"), role="admin")
    db.add(admin)
    db.commit()
    secret = "sk-must-never-appear"

    def unsafe_transport_error(*args, **kwargs):
        raise RuntimeError(f"upstream transport included Authorization: Bearer {secret}")

    monkeypatch.setattr("app.services.ai_operation_service.httpx.post", unsafe_transport_error)
    response = client.post(
        "/api/v1/admin/ai-operations/config/test",
        headers=_headers(admin),
        json={
            "base_url": "https://model.example/v1",
            "model_name": "test-model",
            "api_key": secret,
            "temperature": 0.2,
            "timeout_seconds": 60,
            "streaming_enabled": True,
        },
    )
    assert response.status_code == 400
    assert secret not in response.text
    assert "Bearer ***" in response.text


def test_streaming_known_providers_enable_usage_chunks_but_custom_does_not(
    monkeypatch,
) -> None:
    captured: list[dict] = []

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.append(kwargs)

    monkeypatch.setattr("app.services.ai_operation_service.ChatOpenAI", FakeChatOpenAI)
    for base_url in (
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "https://api.openai.com/v1",
        "https://custom.example/v1",
    ):
        runtime = RuntimeLlmConfig(
            config_id=1,
            source="database",
            base_url=base_url,
            api_key="sk-stream-usage",
            model_name="stream-model",
            temperature=0.2,
            timeout_seconds=60,
            streaming_enabled=True,
        )
        monkeypatch.setattr(
            AiProviderConfigService,
            "resolve",
            lambda db=None, selected=runtime: selected,
        )
        build_chat_model(feature="stream-usage-test", streaming=True)

    assert captured[0]["stream_usage"] is True
    assert captured[1]["stream_usage"] is True
    assert "stream_usage" not in captured[2]


def test_build_chat_model_passes_explicit_positive_output_budget(monkeypatch) -> None:
    captured: list[dict] = []

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.append(kwargs)

    monkeypatch.setattr("app.services.ai_operation_service.ChatOpenAI", FakeChatOpenAI)
    runtime = RuntimeLlmConfig(
        config_id=1,
        source="database",
        base_url="https://api.deepseek.com",
        api_key="sk-output-budget",
        model_name="deepseek-v4-flash",
        temperature=0.2,
        timeout_seconds=120,
        streaming_enabled=False,
    )
    monkeypatch.setattr(AiProviderConfigService, "resolve", lambda db=None: runtime)

    build_chat_model(feature="structured-artifacts", max_tokens=8192)

    assert captured[0]["max_tokens"] == 8192
    assert captured[0]["streaming"] is False


def test_audit_token_usage_falls_back_to_generation_message_metadata() -> None:
    result = SimpleNamespace(
        llm_output={"token_usage": {"prompt_tokens": 11}},
        generations=[[
            SimpleNamespace(
                message=SimpleNamespace(
                    usage_metadata={"input_tokens": 99, "output_tokens": 7}
                )
            )
        ]],
    )

    assert AiCallAuditHandler._token_usage(result) == (11, 7)

    metadata_only = SimpleNamespace(
        llm_output=None,
        generations=[[
            SimpleNamespace(
                message=SimpleNamespace(
                    usage_metadata={"input_tokens": 21, "output_tokens": 5}
                )
            )
        ]],
    )
    assert AiCallAuditHandler._token_usage(metadata_only) == (21, 5)

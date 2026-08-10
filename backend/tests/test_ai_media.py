import asyncio
from collections.abc import Iterator
from datetime import timedelta
from hashlib import sha256
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.models.chapter import Chapter
from app.models.course import Course
from app.models.ai_media_asset import AiMediaAsset
from app.models.user import User
from app.core.config import settings
from app.core.time import utc_now
from app.schemas.ai import AiAssistRequest
from app.services.ai_service import AiService
from app.services.ai_media_service import AiMediaService, UPLOAD_CHUNK_BYTES


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"test-image-data"
WEBM_BYTES = b"\x1aE\xdf\xa3" + b"test-audio-data"


def test_media_storage_reads_upload_in_bounded_chunks(tmp_path) -> None:
    payload = b"\x89PNG\r\n\x1a\n" + b"x" * (UPLOAD_CHUNK_BYTES + 17)

    class ChunkedUpload:
        def __init__(self) -> None:
            self.offset = 0
            self.requested_sizes: list[int] = []

        async def read(self, size: int) -> bytes:
            self.requested_sizes.append(size)
            chunk = payload[self.offset : self.offset + size]
            self.offset += len(chunk)
            return chunk

    upload = ChunkedUpload()
    target = tmp_path / "bounded-upload.png"
    byte_size, digest = asyncio.run(
        AiMediaService._stream_upload(
            upload=upload,  # type: ignore[arg-type]
            target=target,
            declared_mime="image/png",
            media_kind="image",
            max_bytes=len(payload),
        )
    )

    assert upload.requested_sizes
    assert set(upload.requested_sizes) == {UPLOAD_CHUNK_BYTES}
    assert byte_size == len(payload)
    assert digest == sha256(payload).hexdigest()
    assert target.read_bytes() == payload


def prepare_user_context(
    db: Session, *, username: str = "media_student"
) -> tuple[User, dict[str, str], Course, Chapter]:
    user = User(
        username=username,
        password_hash=hash_password("secure-pass-123"),
        role="student",
    )
    course = Course(name=f"{username}课程", description="媒体测试课程")
    db.add_all([user, course])
    db.flush()
    chapter = Chapter(
        course_id=course.id,
        title="媒体测试专题",
        content="教材强调理论联系实际。",
        sort_order=1,
    )
    db.add(chapter)
    db.commit()
    db.refresh(user)
    db.refresh(course)
    db.refresh(chapter)
    headers = {"Authorization": f"Bearer {create_access_token(str(user.id))}"}
    return user, headers, course, chapter


def upload_image(
    client: TestClient,
    headers: dict[str, str],
    course: Course,
    chapter: Chapter,
):
    return client.post(
        "/api/v1/ai/media/assets",
        headers=headers,
        data={"course_id": course.id, "chapter_id": chapter.id},
        files={"file": ("课堂板书.png", PNG_BYTES, "image/png")},
    )


def test_media_capabilities_are_safe_when_providers_are_unconfigured(
    client: TestClient, db: Session, monkeypatch
) -> None:
    sessions: list[Session | None] = []

    class UnconfiguredProvider:
        available = False

        def __init__(self, *, db: Session | None = None) -> None:
            sessions.append(db)

    monkeypatch.setattr(
        "app.api.v1.endpoints.ai_media.VisionProvider",
        UnconfiguredProvider,
    )
    monkeypatch.setattr(
        "app.api.v1.endpoints.ai_media.SpeechTranscriptionProvider",
        UnconfiguredProvider,
    )
    _, headers, _, _ = prepare_user_context(db)
    response = client.get("/api/v1/ai/media/capabilities", headers=headers)

    assert response.status_code == 200
    assert response.json()["data"] == {
        "image_enabled": False,
        "audio_enabled": False,
        "max_images": 2,
        "max_image_mb": 5,
        "max_audio_mb": 10,
        "max_audio_seconds": 60,
        "retention_hours": 24,
        "user_quota_mb": 50,
    }
    assert len(sessions) == 2
    assert sessions[0] is not None
    assert sessions[0] is sessions[1]


def test_image_upload_is_private_and_does_not_expose_storage_path(
    client: TestClient, db: Session
) -> None:
    _, headers, course, chapter = prepare_user_context(db)
    response = upload_image(client, headers, course, chapter)

    assert response.status_code == 201
    asset = response.json()["data"]
    assert asset["media_kind"] == "image"
    assert asset["mime_type"] == "image/png"
    assert asset["byte_size"] == len(PNG_BYTES)
    assert "storage_key" not in asset

    _, other_headers, _, _ = prepare_user_context(db, username="other_student")
    hidden = client.get(f"/api/v1/ai/media/assets/{asset['id']}", headers=other_headers)
    assert hidden.status_code == 404

    owner_list = client.get("/api/v1/ai/media/assets", headers=headers)
    assert [item["id"] for item in owner_list.json()["data"]] == [asset["id"]]


def test_upload_rejects_mime_spoofing(client: TestClient, db: Session) -> None:
    _, headers, course, chapter = prepare_user_context(db)
    response = client.post(
        "/api/v1/ai/media/assets",
        headers=headers,
        data={"course_id": course.id, "chapter_id": chapter.id},
        files={"file": ("伪装.png", b"not-a-real-png", "image/png")},
    )

    assert response.status_code == 400
    assert "媒体类型" in response.json()["detail"]


def test_audio_transcription_streams_stored_file_to_provider(
    client: TestClient, db: Session, monkeypatch
) -> None:
    _, headers, course, chapter = prepare_user_context(db)
    monkeypatch.setattr(
        "app.services.ai_media_service.probe_audio_duration_seconds",
        lambda _path: 1.5,
    )
    uploaded = client.post(
        "/api/v1/ai/media/assets",
        headers=headers,
        data={
            "course_id": course.id,
            "chapter_id": chapter.id,
            "duration_seconds": "1.5",
        },
        files={"file": ("课堂提问.webm", WEBM_BYTES, "audio/webm")},
    )
    assert uploaded.status_code == 201

    class FakeSpeechProvider:
        available = True

        def __init__(self, *, db: Session | None = None) -> None:
            assert db is not None

        def transcribe(self, file, **kwargs) -> str:
            assert Path(file).read_bytes() == WEBM_BYTES
            assert kwargs["content_type"] == "audio/webm"
            assert kwargs["language"] == "zh"
            return "请解释教材中的核心观点"

    monkeypatch.setattr(
        "app.api.v1.endpoints.ai_media.SpeechTranscriptionProvider",
        FakeSpeechProvider,
    )
    response = client.post(
        f"/api/v1/ai/media/assets/{uploaded.json()['data']['id']}/transcribe",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["data"]["text"] == "请解释教材中的核心观点"


def test_audio_limit_uses_server_probe_instead_of_claimed_duration(
    client: TestClient, db: Session, monkeypatch
) -> None:
    _, headers, course, chapter = prepare_user_context(db)
    monkeypatch.setattr(
        "app.services.ai_media_service.probe_audio_duration_seconds",
        lambda _path: 61.0,
    )

    rejected = client.post(
        "/api/v1/ai/media/assets",
        headers=headers,
        data={
            "course_id": course.id,
            "chapter_id": chapter.id,
            "duration_seconds": "0.5",
        },
        files={"file": ("伪造时长.webm", WEBM_BYTES, "audio/webm")},
    )

    assert rejected.status_code == 400
    assert "真实时长" in rejected.json()["detail"]
    monkeypatch.setattr(
        "app.services.ai_media_service.probe_audio_duration_seconds",
        lambda _path: 1.25,
    )
    accepted = client.post(
        "/api/v1/ai/media/assets",
        headers=headers,
        data={
            "course_id": course.id,
            "chapter_id": chapter.id,
            "duration_seconds": "59",
        },
        files={"file": ("服务端时长.webm", WEBM_BYTES, "audio/webm")},
    )
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["data"]["duration_seconds"] == 1.25


def test_media_user_quota_is_enforced_across_assets(
    client: TestClient, db: Session, monkeypatch
) -> None:
    user, headers, course, chapter = prepare_user_context(db)
    monkeypatch.setattr(settings, "ai_media_user_quota_mb", 10)
    now = utc_now()
    db.add(
        AiMediaAsset(
            owner_user_id=user.id,
            course_id=course.id,
            chapter_id=chapter.id,
            media_kind="image",
            original_filename="existing.png",
            mime_type="image/png",
            byte_size=10 * 1024 * 1024,
            sha256="a" * 64,
            storage_key=f"{user.id}/existing.png",
            status="ready",
            created_time=now,
            updated_time=now,
        )
    )
    db.commit()

    response = upload_image(client, headers, course, chapter)

    assert response.status_code == 413
    assert "个人临时媒体空间不能超过 10 MB" in response.json()["detail"]


def test_expired_media_is_removed_on_next_owned_access(
    client: TestClient, db: Session
) -> None:
    user, headers, course, chapter = prepare_user_context(db)
    storage_path = AiMediaService.media_root() / str(user.id) / "expired.png"
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    storage_path.write_bytes(PNG_BYTES)
    stale_time = utc_now() - timedelta(hours=25)
    asset = AiMediaAsset(
        owner_user_id=user.id,
        course_id=course.id,
        chapter_id=chapter.id,
        media_kind="image",
        original_filename="expired.png",
        mime_type="image/png",
        byte_size=len(PNG_BYTES),
        sha256=sha256(PNG_BYTES).hexdigest(),
        storage_key=f"{user.id}/expired.png",
        status="ready",
        created_time=stale_time,
        updated_time=stale_time,
    )
    db.add(asset)
    db.commit()
    asset_id = asset.id

    response = client.get("/api/v1/ai/media/assets", headers=headers)

    assert response.status_code == 200
    assert response.json()["data"] == []
    # The request uses its own session; expire this fixture's identity map so
    # the assertion observes the committed delete instead of its cached row.
    db.expire_all()
    assert db.get(AiMediaAsset, asset_id) is None
    assert not storage_path.exists()


def test_ai_service_uses_owned_image_with_grounded_prompt(
    client: TestClient, db: Session
) -> None:
    user, headers, course, chapter = prepare_user_context(db)
    uploaded = upload_image(client, headers, course, chapter)
    asset_id = uploaded.json()["data"]["id"]

    class FakeVisionProvider:
        available = True
        model_name = "test-vision"
        prompt = ""
        paths: list[str] = []

        def generate(self, prompt: str, images, *, max_total_bytes: int) -> str:
            self.prompt = prompt
            self.paths = list(images)
            assert max_total_bytes == 10 * 1024 * 1024
            assert all(Path(item).is_file() for item in self.paths)
            return "图片展示了与教材观点相关的课堂板书。"

        def stream(self, prompt: str, images, *, max_total_bytes: int) -> Iterator[str]:
            yield self.generate(prompt, images, max_total_bytes=max_total_bytes)

    provider = FakeVisionProvider()
    result = AiService(db, user=user, vision_provider=provider).assist(
        AiAssistRequest(
            course_id=course.id,
            chapter_id=chapter.id,
            learning_stage="preview",
            task_type="question_answer",
            question="这张板书与教材有什么关系？",
            attachment_ids=[asset_id],
        )
    )

    assert result.model == "test-vision"
    assert result.grounded is True
    assert result.answer.startswith("图片展示了")
    assert "图片不是已核验的教材或权威资料" in provider.prompt
    assert "教材强调理论联系实际" in provider.prompt
    assert len(provider.paths) == 1


def test_workspace_chat_forwards_image_ids_but_agent_rejects_them(
    client: TestClient, db: Session, monkeypatch
) -> None:
    _, headers, course, chapter = prepare_user_context(db)
    uploaded = upload_image(client, headers, course, chapter)
    asset_id = uploaded.json()["data"]["id"]

    class FakeVisionProvider:
        available = True
        model_name = "workspace-vision"

        def __init__(self, *, db: Session | None = None) -> None:
            assert db is not None

        def generate(self, prompt: str, images, *, max_total_bytes: int) -> str:
            assert list(images)
            return "已结合图片与教材回答。"

        def stream(self, prompt: str, images, *, max_total_bytes: int) -> Iterator[str]:
            yield self.generate(prompt, images, max_total_bytes=max_total_bytes)

    monkeypatch.setattr("app.services.ai_service.VisionProvider", FakeVisionProvider)
    payload = {
        "role": "student",
        "course_id": course.id,
        "chapter_id": chapter.id,
        "learning_stage": "preview",
        "question": "请分析图片",
        "attachment_ids": [asset_id],
    }
    chat = client.post(
        "/api/v1/ai/workspace/stream",
        headers=headers,
        json={"mode": "chat", **payload},
    )
    assert chat.status_code == 200
    assert "workspace-vision" in chat.text
    assert "已结合图片与教材回答" in chat.text

    agent = client.post(
        "/api/v1/ai/workspace/stream",
        headers=headers,
        json={"mode": "agent", **payload},
    )
    assert agent.status_code == 400
    assert agent.json()["detail"] == "图片附件仅支持 Chat 模式"

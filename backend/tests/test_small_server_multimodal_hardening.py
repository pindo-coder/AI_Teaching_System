from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
from typing import Iterator

import httpx
import pytest

from app.core.config import settings
import app.services.multimodal_provider as provider_module
from app.services.multimodal_provider import (
    MultimodalProviderError,
    SpeechTranscriptionProvider,
)
import app.services.ppt_multimodal_service as ppt_module
from app.services.ppt_multimodal_service import PptMultimodalService


class _ImageStreamResponse:
    def __init__(
        self,
        chunks: list[bytes],
        *,
        content_length: int | None = None,
    ) -> None:
        self.status_code = 200
        self.headers = {"content-type": "image/png"}
        if content_length is not None:
            self.headers["content-length"] = str(content_length)
        self._chunks = chunks
        self.iterated_chunks = 0
        self.chunk_sizes: list[int] = []

    def __enter__(self) -> _ImageStreamResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def iter_bytes(self, *, chunk_size: int) -> Iterator[bytes]:
        self.chunk_sizes.append(chunk_size)
        for chunk in self._chunks:
            self.iterated_chunks += 1
            yield chunk


class _ImageClient:
    def __init__(self, stream_response: _ImageStreamResponse) -> None:
        self.stream_response = stream_response
        self.stream_calls: list[tuple[str, str]] = []

    def __enter__(self) -> _ImageClient:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def post(self, url: str, **_kwargs: object) -> httpx.Response:
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "output": {
                    "choices": [
                        {
                            "message": {
                                "content": [
                                    {
                                        "image": (
                                            "https://generated-assets.aliyuncs.com/slide.png"
                                        )
                                    }
                                ]
                            }
                        }
                    ]
                }
            },
        )

    def stream(self, method: str, url: str) -> _ImageStreamResponse:
        self.stream_calls.append((method, url))
        return self.stream_response


def _ppt_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stream_response: _ImageStreamResponse | None = None,
) -> PptMultimodalService:
    monkeypatch.setattr(settings, "generated_artifact_directory", str(tmp_path))
    service = PptMultimodalService(
        701,
        api_key="sk-image-test",
        base_url="https://dashscope.aliyuncs.com/api/v1",
        model="wan-test",
        timeout_seconds=10,
        enabled=True,
    )
    if stream_response is not None:
        fake_client = _ImageClient(stream_response)
        monkeypatch.setattr(
            ppt_module.httpx,
            "Client",
            lambda **_kwargs: fake_client,
        )
    return service


def test_ppt_image_download_streams_to_part_then_atomically_replaces(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from PIL import Image
    buffer = BytesIO()
    Image.new("RGB", (32, 32), "white").save(buffer, format="PNG")
    bitmap = buffer.getvalue()
    response = _ImageStreamResponse([bitmap[:20], bitmap[20:]])
    service = _ppt_service(tmp_path, monkeypatch, response)

    asset = service._generate_one({"title": "测试"}, {}, 0)

    output = service.asset_dir / asset["file_name"]
    assert output.read_bytes() == bitmap
    assert asset["storage_path"] == f"701/ppt_visuals/{output.name}"
    assert output.name.startswith("slide-1-")
    assert response.chunk_sizes == [64 * 1024]
    assert list(service.asset_dir.glob("*.part")) == []
    assert list(service.asset_dir.glob(".*.part")) == []


def test_ppt_image_download_rejects_oversized_content_length_before_streaming(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ppt_module, "MAX_GENERATED_IMAGE_BYTES", 10)
    response = _ImageStreamResponse([b"must-not-be-read"], content_length=11)
    service = _ppt_service(tmp_path, monkeypatch, response)

    with pytest.raises(RuntimeError, match="超过 20MB"):
        service._generate_one({"title": "测试"}, {}, 0)

    assert response.iterated_chunks == 0


def test_image_moderation_failure_is_not_retried_or_exposed_raw(tmp_path, monkeypatch):
    service = _ppt_service(tmp_path, monkeypatch)
    calls = []
    class Client:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def post(self, url, **kwargs):
            calls.append(kwargs)
            return httpx.Response(400, json={"code": "DataInspectionFailed", "message": "private provider diagnostic"})
    monkeypatch.setattr(ppt_module.httpx, "Client", lambda **kwargs: Client())
    with pytest.raises(ppt_module.PptImageGenerationError, match="内容审核") as error:
        service._generate_one({"visual_prompt": "教学插图"}, {}, 0)
    assert len(calls) == 1
    assert "private provider diagnostic" not in str(error.value)
    assert list(service.asset_dir.iterdir()) == []


def test_ppt_image_download_cleans_partial_file_on_stream_overflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ppt_module, "MAX_GENERATED_IMAGE_BYTES", 10)
    response = _ImageStreamResponse([b"12345678", b"abcd", b"must-not-be-read"])
    service = _ppt_service(tmp_path, monkeypatch, response)

    with pytest.raises(RuntimeError, match="超过 20MB"):
        service._generate_one({"title": "测试"}, {}, 0)

    assert response.iterated_chunks == 2
    assert list(service.asset_dir.iterdir()) == []


def test_ppt_image_gate_falls_back_immediately_and_removes_image_slots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _ppt_service(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "ppt_multimodal_max_images", 1)
    monkeypatch.setattr(
        service,
        "_generate_one",
        lambda *_args, **_kwargs: pytest.fail("忙时不应调用图片模型"),
    )
    ppt = {
        "design": {},
        "slides": [
            {
                "layout": "concept",
                "svg": '<svg xmlns="http://www.w3.org/2000/svg"><image id="visual-asset" /></svg>',
                "visual_asset": {"storage_path": "stale.png"},
            }
        ],
    }

    assert ppt_module._PPT_IMAGE_CALL_GATE.acquire(blocking=False) is True
    try:
        enhanced = service.enhance_svg(ppt)
    finally:
        ppt_module._PPT_IMAGE_CALL_GATE.release()

    assert enhanced["multimodal"]["status"] == "fallback"
    assert "正忙" in enhanced["multimodal"]["message"]
    assert "image" not in enhanced["slides"][0]["svg"]
    assert "visual_asset" not in enhanced["slides"][0]


def test_ppt_image_gate_is_released_after_generation_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _ppt_service(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "ppt_multimodal_max_images", 1)

    def fail_generation(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise RuntimeError("provider failed")

    monkeypatch.setattr(service, "_generate_one", fail_generation)
    ppt = {
        "design": {},
        "slides": [
            {
                "layout": "concept",
                "svg": '<svg xmlns="http://www.w3.org/2000/svg"><image id="visual-asset" /></svg>',
            }
        ],
    }

    enhanced = service.enhance_svg(ppt)

    assert enhanced["multimodal"]["status"] == "fallback"
    assert ppt_module._PPT_IMAGE_CALL_GATE.acquire(blocking=False) is True
    ppt_module._PPT_IMAGE_CALL_GATE.release()


def test_ppt_image_prompt_uses_topic_style_and_partial_failure_is_visible(tmp_path, monkeypatch):
    service = _ppt_service(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "ppt_multimodal_max_images", 2)
    theme = {"name": "同心协商", "topic_keywords": ["社区协商"],
        "visual_motif": "围坐交流", "image_style": "暖色纪实教学插画", "primary": "1F4E5F"}
    prompt = service._safe_prompt({"visual_prompt": "居民协商公共事务"}, theme)
    assert all(value in prompt for value in ["居民协商公共事务", "暖色纪实教学插画", "1F4E5F"])
    assert "主题关键词" not in prompt
    def generate(slide, design, index):
        if index == 1:
            raise RuntimeError("provider failed")
        return {"storage_path": "generated.png"}
    monkeypatch.setattr(service, "_generate_one", generate)
    result = service.enhance_svg({"design": theme, "slides": [
        {"svg": '<svg xmlns="http://www.w3.org/2000/svg"><image id="visual-asset" /></svg>'}
        for _ in range(2)]})
    assert result["multimodal"]["status"] == "partial"
    assert result["multimodal"]["generated_count"] == 1
    assert result["multimodal"]["selected_slides"] == [1]
    assert "1/2" in result["multimodal"]["message"]
    assert "visual_asset" in result["slides"][0]
    assert "image" not in result["slides"][1]["svg"]


def test_image_retry_keeps_existing_paid_image_and_fills_only_missing(tmp_path, monkeypatch):
    from PIL import Image
    service = _ppt_service(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "generated_artifact_directory", str(tmp_path))
    monkeypatch.setattr(settings, "ppt_multimodal_max_images", 2)
    Image.new("RGB", (32, 32), "white").save(tmp_path / "paid.png")
    generated = []
    def generate(slide, design, index):
        generated.append(index)
        return {"storage_path": "new.png"}
    monkeypatch.setattr(service, "_generate_one", generate)
    source = '<svg xmlns="http://www.w3.org/2000/svg"><image id="visual-asset" /></svg>'
    result = service.enhance_svg({"design": {}, "slides": [
        {"svg": source, "visual_asset": {"storage_path": "paid.png"}}, {"svg": source}]}, preserve_slots=True)
    assert generated == [1]
    assert result["slides"][0]["visual_asset"]["storage_path"] == "paid.png"
    assert result["multimodal"]["generated_count"] == 2


def _qwen_provider() -> SpeechTranscriptionProvider:
    return SpeechTranscriptionProvider(
        api_key="sk-asr-test",
        base_url="https://dashscope.example/compatible-mode/v1",
        model="qwen3-asr-flash",
        timeout_seconds=10,
    )


def test_qwen3_asr_raw_limit_is_largest_value_within_10_mib_data_url() -> None:
    media_type = "audio/wav"
    prefix_size = len(f"data:{media_type};base64,")
    raw_limit = provider_module._qwen3_audio_max_raw_bytes(media_type)

    encoded_at_limit = 4 * ((raw_limit + 2) // 3)
    encoded_one_byte_over = 4 * ((raw_limit + 3) // 3)
    assert prefix_size + encoded_at_limit <= 10 * 1024 * 1024
    assert prefix_size + encoded_one_byte_over > 10 * 1024 * 1024
    assert 7.49 < raw_limit / (1024 * 1024) < 7.5


def test_qwen3_asr_accepts_exact_data_url_boundary_and_rejects_next_byte(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A small protocol budget exercises the exact boundary without allocating
    # a multi-megabyte fixture.
    monkeypatch.setattr(provider_module, "DASHSCOPE_ASR_DATA_URL_MAX_BYTES", 64)
    monkeypatch.setattr(provider_module.settings, "ai_media_max_audio_mb", 10)
    raw_limit = provider_module._qwen3_audio_max_raw_bytes("audio/wav")
    captured_data_urls: list[str] = []

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        body = kwargs["json"]
        data_url = body["messages"][0]["content"][0]["input_audio"]["data"]
        captured_data_urls.append(data_url)
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={"choices": [{"message": {"content": "边界转写成功"}}]},
        )

    monkeypatch.setattr(provider_module.httpx, "post", fake_post)

    assert (
        _qwen_provider().transcribe(
            BytesIO(b"x" * raw_limit),
            filename="boundary.wav",
            content_type="audio/wav",
        )
        == "边界转写成功"
    )
    assert len(captured_data_urls[0]) <= 64
    assert captured_data_urls[0].endswith(
        base64.b64encode(b"x" * raw_limit).decode("ascii")
    )

    with pytest.raises(MultimodalProviderError, match="Base64 Data URL"):
        _qwen_provider().transcribe(
            BytesIO(b"x" * (raw_limit + 1)),
            filename="too-large.wav",
            content_type="audio/wav",
        )

    assert len(captured_data_urls) == 1


def test_multipart_asr_does_not_apply_qwen3_base64_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnreadAudio(BytesIO):
        def read(self, size: int = -1) -> bytes:
            raise AssertionError(f"multipart ASR 不应预读录音：{size}")

    monkeypatch.setattr(provider_module, "DASHSCOPE_ASR_DATA_URL_MAX_BYTES", 64)
    audio = UnreadAudio(b"x" * 100)

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        assert kwargs["files"]["file"][1] is audio
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={"text": "multipart 转写成功"},
        )

    monkeypatch.setattr(provider_module.httpx, "post", fake_post)
    provider = SpeechTranscriptionProvider(
        api_key="sk-asr-test",
        base_url="https://models.example/v1",
        model="whisper-1",
    )

    assert (
        provider.transcribe(
            audio,
            filename="recording.webm",
            content_type="audio/webm",
        )
        == "multipart 转写成功"
    )

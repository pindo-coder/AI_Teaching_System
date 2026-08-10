import base64
from io import BytesIO
from types import SimpleNamespace

import httpx
import pytest

import app.services.multimodal_provider as provider_module
from app.services.multimodal_provider import (
    MultimodalProviderError,
    SpeechTranscriptionProvider,
    VisionImage,
    VisionProvider,
)


def _vision_provider() -> VisionProvider:
    return VisionProvider(
        api_key="sk-vision-test",
        base_url="https://models.example/v1/",
        model="vision-test-model",
        timeout_seconds=15,
    )


def _asr_provider() -> SpeechTranscriptionProvider:
    return SpeechTranscriptionProvider(
        api_key="sk-asr-test",
        base_url="https://models.example/v1/",
        model="asr-test-model",
        timeout_seconds=20,
    )


def test_vision_request_uses_text_and_bounded_data_url_images(tmp_path, monkeypatch) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.webp"
    first_bytes = b"\x89PNG\r\n\x1a\nfirst-image"
    second_bytes = b"RIFF\x04\x00\x00\x00WEBPsecond-image"
    first.write_bytes(first_bytes)
    second.write_bytes(second_bytes)
    captured: dict[str, object] = {}

    def fake_post(url: str, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={"choices": [{"message": {"content": "图中展示了两个知识点。"}}]},
        )

    monkeypatch.setattr("app.services.multimodal_provider.httpx.post", fake_post)

    answer = _vision_provider().generate(
        "请解释这些图片",
        [first, second],
        max_total_bytes=len(first_bytes) + len(second_bytes),
    )

    assert answer == "图中展示了两个知识点。"
    assert captured["url"] == "https://models.example/v1/chat/completions"
    assert captured["headers"] == {
        "Authorization": "Bearer sk-vision-test",
        "Content-Type": "application/json",
    }
    body = captured["json"]
    assert body["model"] == "vision-test-model"
    assert body["stream"] is False
    parts = body["messages"][0]["content"]
    assert parts[0] == {"type": "text", "text": "请解释这些图片"}
    assert parts[1] == {
        "type": "image_url",
        "image_url": {
            "url": f"data:image/png;base64,{base64.b64encode(first_bytes).decode('ascii')}"
        },
    }
    assert parts[2] == {
        "type": "image_url",
        "image_url": {
            "url": f"data:image/webp;base64,{base64.b64encode(second_bytes).decode('ascii')}"
        },
    }


def test_vision_stream_chunks_non_streaming_response(tmp_path, monkeypatch) -> None:
    image = tmp_path / "question.jpg"
    image.write_bytes(b"\xff\xd8\xffimage")
    answer = "答" * 150

    def fake_post(url: str, **kwargs):
        assert kwargs["json"]["stream"] is False
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={"choices": [{"message": {"content": answer}}]},
        )

    monkeypatch.setattr("app.services.multimodal_provider.httpx.post", fake_post)

    chunks = list(
        _vision_provider().stream(
            "识别图片",
            [image],
            max_total_bytes=1024,
        )
    )

    assert [len(chunk) for chunk in chunks] == [72, 72, 6]
    assert "".join(chunks) == answer


def test_vision_rejects_more_than_two_images_before_reading(monkeypatch) -> None:
    class NeverRead(BytesIO):
        def read(self, *_args, **_kwargs):
            raise AssertionError("图片数量应在文件读取前完成校验")

    def should_not_post(*_args, **_kwargs):
        raise AssertionError("无效图片请求不应调用远程服务")

    monkeypatch.setattr("app.services.multimodal_provider.httpx.post", should_not_post)

    with pytest.raises(MultimodalProviderError, match="最多上传 2 张"):
        _vision_provider().generate(
            "查看图片",
            [NeverRead(), NeverRead(), NeverRead()],
            max_total_bytes=100,
        )


def test_vision_reads_only_one_byte_beyond_remaining_total_limit(monkeypatch) -> None:
    class TrackedImage(BytesIO):
        def __init__(self, value: bytes) -> None:
            super().__init__(value)
            self.read_sizes: list[int] = []

        def read(self, size: int = -1) -> bytes:
            self.read_sizes.append(size)
            return super().read(size)

    first = TrackedImage(b"\xff\xd8\xff")
    second = TrackedImage(b"\xff\xd8\xff")

    def should_not_post(*_args, **_kwargs):
        raise AssertionError("超限图片不应调用远程服务")

    monkeypatch.setattr("app.services.multimodal_provider.httpx.post", should_not_post)

    with pytest.raises(MultimodalProviderError, match="总大小超过限制"):
        _vision_provider().generate(
            "查看图片",
            [VisionImage(first, "image/jpeg"), VisionImage(second, "image/jpeg")],
            max_total_bytes=4,
        )

    assert first.read_sizes == [5]
    # 第一张用了 3 bytes，第二张最多读取剩余 1 byte 再多一个探测字节。
    assert second.read_sizes == [2]


def test_speech_transcription_passes_original_stream_to_multipart(monkeypatch) -> None:
    class UnreadAudio(BytesIO):
        def __init__(self, value: bytes) -> None:
            super().__init__(value)
            self.read_calls = 0

        def read(self, size: int = -1) -> bytes:
            self.read_calls += 1
            return super().read(size)

    audio = UnreadAudio(b"fake-audio-payload")
    captured: dict[str, object] = {}

    def fake_post(url: str, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        file_tuple = kwargs["files"]["file"]
        assert file_tuple[1] is audio
        assert audio.tell() == 0
        assert audio.read_calls == 0
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={"text": "这是语音转写结果。"},
        )

    monkeypatch.setattr("app.services.multimodal_provider.httpx.post", fake_post)

    text = _asr_provider().transcribe(
        audio,
        filename="question.webm",
        content_type="audio/webm",
        language="zh",
    )

    assert text == "这是语音转写结果。"
    assert audio.read_calls == 0
    assert captured["url"] == "https://models.example/v1/audio/transcriptions"
    assert captured["headers"] == {"Authorization": "Bearer sk-asr-test"}
    assert captured["data"] == {"model": "asr-test-model", "language": "zh"}
    assert captured["files"]["file"] == ("question.webm", audio, "audio/webm")


def test_media_providers_prefer_shared_dashscope_key_and_embedding_url(monkeypatch) -> None:
    fake_settings = SimpleNamespace(
        ai_vision_api_key=None,
        ai_vision_base_url=None,
        ai_asr_api_key=None,
        ai_asr_base_url=None,
        dashscope_api_key="sk-shared-dashscope",
        embedding_provider="dashscope",
        embedding_api_key="sk-embedding-fallback",
        embedding_base_url="https://workspace.example/compatible-mode/v1/",
    )
    monkeypatch.setattr(provider_module, "settings", fake_settings)

    vision = VisionProvider(model="qwen-vl-plus")
    speech = SpeechTranscriptionProvider(model="qwen3-asr-flash")

    assert vision.api_key == "sk-shared-dashscope"
    assert speech.api_key == "sk-shared-dashscope"
    assert vision.base_url == "https://workspace.example/compatible-mode/v1"
    assert speech.base_url == "https://workspace.example/compatible-mode/v1"
    assert vision.available is True
    assert speech.available is True


def test_media_providers_fall_back_to_dashscope_embedding_key_and_default_url(
    monkeypatch,
) -> None:
    fake_settings = SimpleNamespace(
        ai_vision_api_key="",
        ai_vision_base_url="",
        ai_asr_api_key=None,
        ai_asr_base_url=None,
        dashscope_api_key=None,
        embedding_provider="DASHSCOPE",
        embedding_api_key="sk-vector-dashscope",
        embedding_base_url=None,
    )
    monkeypatch.setattr(provider_module, "settings", fake_settings)

    vision = VisionProvider(model="qwen-vl-plus")
    speech = SpeechTranscriptionProvider(model="qwen3-asr-flash")

    assert vision.api_key == "sk-vector-dashscope"
    assert speech.api_key == "sk-vector-dashscope"
    assert vision.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert speech.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"


def test_generic_embedding_key_is_not_reused_for_non_dashscope_provider(monkeypatch) -> None:
    fake_settings = SimpleNamespace(
        ai_vision_api_key=None,
        ai_vision_base_url=None,
        ai_asr_api_key=None,
        ai_asr_base_url=None,
        dashscope_api_key=None,
        embedding_provider="openai_compatible",
        embedding_api_key="sk-unrelated-provider",
        embedding_base_url="https://unrelated.example/v1",
    )
    monkeypatch.setattr(provider_module, "settings", fake_settings)

    vision = VisionProvider(model="vision-model")
    speech = SpeechTranscriptionProvider(model="asr-model")

    assert vision.api_key is None
    assert speech.api_key is None
    assert vision.base_url == ""
    assert speech.base_url == ""
    assert vision.available is False
    assert speech.available is False


def test_qwen3_asr_uses_bounded_input_audio_data_url(monkeypatch) -> None:
    class TrackedAudio(BytesIO):
        def __init__(self, value: bytes) -> None:
            super().__init__(value)
            self.read_sizes: list[int] = []

        def read(self, size: int = -1) -> bytes:
            self.read_sizes.append(size)
            return super().read(size)

    monkeypatch.setattr(provider_module.settings, "ai_media_max_audio_mb", 1)
    audio_bytes = b"RIFF\x04\x00\x00\x00WAVEvoice"
    audio = TrackedAudio(audio_bytes)
    captured: dict[str, object] = {}

    def fake_post(url: str, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={"choices": [{"message": {"content": "百炼语音转写结果。"}}]},
        )

    monkeypatch.setattr("app.services.multimodal_provider.httpx.post", fake_post)
    provider = SpeechTranscriptionProvider(
        api_key="sk-qwen-asr",
        base_url="https://dashscope.example/compatible-mode/v1",
        model="qwen3-asr-flash",
    )

    text = provider.transcribe(
        audio,
        filename="question.wav",
        content_type="audio/wav",
        language="zh",
    )

    assert text == "百炼语音转写结果。"
    assert audio.read_sizes == [1024 * 1024 + 1]
    assert captured["url"] == "https://dashscope.example/compatible-mode/v1/chat/completions"
    assert captured["headers"] == {
        "Authorization": "Bearer sk-qwen-asr",
        "Content-Type": "application/json",
    }
    assert "files" not in captured
    assert "data" not in captured
    body = captured["json"]
    assert body["model"] == "qwen3-asr-flash"
    assert body["stream"] is False
    assert body["asr_options"] == {"enable_itn": False, "language": "zh"}
    assert body["messages"] == [
        {
            "role": "user",
            "content": [
                {
                    "type": "input_audio",
                    "input_audio": {
                        "data": (
                            "data:audio/wav;base64,"
                            f"{base64.b64encode(audio_bytes).decode('ascii')}"
                        )
                    },
                }
            ],
        }
    ]


def test_qwen3_asr_rejects_audio_beyond_configured_limit(monkeypatch) -> None:
    class OversizedAudio:
        requested_size: int | None = None

        def read(self, size: int = -1) -> bytes:
            self.requested_size = size
            return b"x" * size

    audio = OversizedAudio()
    monkeypatch.setattr(provider_module.settings, "ai_media_max_audio_mb", 1)

    def should_not_post(*_args, **_kwargs):
        raise AssertionError("超限录音不应调用远程服务")

    monkeypatch.setattr("app.services.multimodal_provider.httpx.post", should_not_post)
    provider = SpeechTranscriptionProvider(
        api_key="sk-qwen-asr",
        base_url="https://dashscope.example/compatible-mode/v1",
        model="qwen3-asr-flash-2026-02-10",
    )

    with pytest.raises(MultimodalProviderError, match="不能超过 1 MB"):
        provider.transcribe(
            audio,
            filename="large.webm",
            content_type="audio/webm",
        )

    assert audio.requested_size == 1024 * 1024 + 1


def test_speech_calls_share_one_process_wide_gate() -> None:
    provider = _asr_provider()
    assert provider_module._SPEECH_CALL_GATE.acquire(blocking=False) is True
    try:
        with pytest.raises(MultimodalProviderError, match="服务正忙"):
            provider.transcribe(
                BytesIO(b"audio"),
                filename="question.webm",
                content_type="audio/webm",
            )
    finally:
        provider_module._SPEECH_CALL_GATE.release()


@pytest.mark.parametrize("provider_kind", ["vision", "asr"])
def test_remote_errors_do_not_leak_secrets_or_file_content(
    tmp_path,
    monkeypatch,
    provider_kind: str,
) -> None:
    secret = "sk-super-secret-value"
    uploaded_content = "private-uploaded-content"

    def failed_post(url: str, **_kwargs):
        return httpx.Response(
            500,
            request=httpx.Request("POST", url),
            text=f"provider debug: {secret}; body={uploaded_content}",
        )

    monkeypatch.setattr("app.services.multimodal_provider.httpx.post", failed_post)

    if provider_kind == "vision":
        image = tmp_path / "private.png"
        image.write_bytes(b"\x89PNG\r\n\x1a\n" + uploaded_content.encode())
        provider = VisionProvider(
            api_key=secret,
            base_url="https://models.example/v1",
            model="vision-model",
        )
        call = lambda: provider.generate("私密问题", [image], max_total_bytes=1024)
    else:
        provider = SpeechTranscriptionProvider(
            api_key=secret,
            base_url="https://models.example/v1",
            model="asr-model",
        )
        call = lambda: provider.transcribe(
            BytesIO(uploaded_content.encode()),
            filename="private.webm",
            content_type="audio/webm",
        )

    with pytest.raises(MultimodalProviderError) as captured:
        call()

    error_text = str(captured.value)
    assert secret not in error_text
    assert uploaded_content not in error_text
    assert "models.example" not in error_text

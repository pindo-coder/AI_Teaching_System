"""Low-memory adapters for OpenAI-compatible vision and speech APIs.

The application keeps media storage and provider calls separate. Vision models
and Qwen3 ASR need data URLs, so their inputs are opened with strict byte bounds.
Other speech models receive the original file object through multipart encoding.
"""

from __future__ import annotations

import base64
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import mimetypes
from pathlib import Path
from threading import BoundedSemaphore
from typing import Any, BinaryIO

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.ai_operation_service import AiProviderConfigService
from app.services.llm_compat import chunk_text, clean_model_text


MAX_VISION_IMAGES = 2
DEFAULT_AUDIO_MAX_MB = 10
DASHSCOPE_ASR_DATA_URL_MAX_BYTES = 10 * 1024 * 1024
DASHSCOPE_COMPATIBLE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
# 单进程最多各执行一个视觉/转写请求，避免并发 Data URL 编码在小服务器上
# 叠加内存峰值。
_VISION_CALL_GATE = BoundedSemaphore(1)
_SPEECH_CALL_GATE = BoundedSemaphore(1)


class MultimodalProviderError(RuntimeError):
    """A safe, user-displayable provider failure.

    Remote response bodies and low-level exceptions are deliberately omitted so
    API keys, prompts, and uploaded file contents cannot leak through error text.
    """


@dataclass(frozen=True, slots=True)
class VisionImage:
    """Optional wrapper used when a file's MIME type cannot be inferred by name."""

    source: str | Path | BinaryIO
    media_type: str | None = None


def _setting(name: str, default: Any = None) -> Any:
    """Read newly introduced settings without breaking older deployments."""

    return getattr(settings, name, default)


def _nonempty_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _uses_dashscope_settings() -> bool:
    provider = str(_setting("embedding_provider", "") or "").strip().lower()
    return bool(_nonempty_text(_setting("dashscope_api_key")) or provider == "dashscope")


def _resolve_api_key(explicit: str | None, media_setting: str) -> str | None:
    """Resolve media credentials without treating a generic embedding key as DashScope."""

    direct = _nonempty_text(explicit) or _nonempty_text(_setting(media_setting))
    if direct:
        return direct
    dashscope_key = _nonempty_text(_setting("dashscope_api_key"))
    if dashscope_key:
        return dashscope_key
    provider = str(_setting("embedding_provider", "") or "").strip().lower()
    if provider == "dashscope":
        return _nonempty_text(_setting("embedding_api_key"))
    return None


def _resolve_base_url(explicit: str | None, media_setting: str) -> str:
    direct = _nonempty_text(explicit) or _nonempty_text(_setting(media_setting))
    if direct:
        return direct.rstrip("/")
    if _uses_dashscope_settings():
        embedding_url = _nonempty_text(_setting("embedding_base_url"))
        return (embedding_url or DASHSCOPE_COMPATIBLE_BASE_URL).rstrip("/")
    return ""


def _audio_max_bytes() -> int:
    try:
        max_mb = int(_setting("ai_media_max_audio_mb", DEFAULT_AUDIO_MAX_MB))
    except (TypeError, ValueError):
        max_mb = DEFAULT_AUDIO_MAX_MB
    if max_mb <= 0:
        max_mb = DEFAULT_AUDIO_MAX_MB
    return max_mb * 1024 * 1024


def _qwen3_audio_max_raw_bytes(media_type: str) -> int:
    """Largest raw payload whose Base64 Data URL stays within 10 MiB."""

    prefix_bytes = len(f"data:{media_type};base64,")
    encoded_budget = max(0, DASHSCOPE_ASR_DATA_URL_MAX_BYTES - prefix_bytes)
    # Four Base64 characters encode at most three input bytes. Using complete
    # groups ensures ceil(raw_bytes / 3) * 4 never exceeds the provider limit.
    return (encoded_budget // 4) * 3


def _database_capability(capability: str, db: Session | None) -> Any | None:
    """Return only an explicit DB override; env values keep legacy resolution."""

    config = AiProviderConfigService.resolve_capability(capability, db)
    return config if config.source == "database" else None


def _clean_media_type(value: object) -> str | None:
    media_type = str(value or "").split(";", 1)[0].strip().lower()
    if media_type == "image/jpg":
        media_type = "image/jpeg"
    return media_type or None


def _guess_image_type(name: object, data: bytes, explicit: str | None) -> str:
    media_type = _clean_media_type(explicit)
    if media_type is None and name:
        media_type = _clean_media_type(mimetypes.guess_type(str(name))[0])
    if media_type is None:
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            media_type = "image/png"
        elif data.startswith(b"\xff\xd8\xff"):
            media_type = "image/jpeg"
        elif data.startswith(b"RIFF") and data[8:12] == b"WEBP":
            media_type = "image/webp"
    if media_type not in _SUPPORTED_IMAGE_TYPES:
        raise MultimodalProviderError("仅支持 JPEG、PNG 或 WebP 图片")
    return media_type


@contextmanager
def _binary_source(source: object) -> Iterator[tuple[BinaryIO, str | None, str | None]]:
    """Yield a binary stream, its name and an optional UploadFile MIME type."""

    if isinstance(source, (str, Path)):
        try:
            stream = Path(source).open("rb")
        except (OSError, ValueError):
            raise MultimodalProviderError("无法读取所选媒体文件") from None
        try:
            yield stream, Path(source).name, None
        finally:
            stream.close()
        return

    # FastAPI/Starlette UploadFile exposes the underlying spooled stream through
    # ``.file``.  Using it avoids the async ``read()`` helper and an extra copy.
    upload_stream = getattr(source, "file", None)
    if upload_stream is not None and callable(getattr(upload_stream, "read", None)):
        yield (
            upload_stream,
            Path(str(getattr(source, "filename", "") or "")).name or None,
            _clean_media_type(getattr(source, "content_type", None)),
        )
        return

    if callable(getattr(source, "read", None)):
        raw_name = getattr(source, "name", None)
        safe_name = Path(str(raw_name)).name if raw_name else None
        yield source, safe_name, None  # type: ignore[misc]
        return

    raise MultimodalProviderError("无法读取所选媒体文件")


def _extract_chat_text(
    payload: object,
    *,
    malformed_message: str,
    empty_message: str,
) -> str:
    try:
        content = payload["choices"][0]["message"]["content"]  # type: ignore[index]
    except (KeyError, IndexError, TypeError):
        raise MultimodalProviderError(malformed_message) from None

    if isinstance(content, str):
        answer = content
    elif isinstance(content, list):
        # A few compatible gateways return output content parts even for chat
        # completions.  Only textual parts are exposed to the application.
        answer = "".join(
            str(part.get("text") or "")
            for part in content
            if isinstance(part, dict) and part.get("type") in {None, "text", "output_text"}
        )
    else:
        answer = ""
    answer = clean_model_text(answer)
    if not answer:
        raise MultimodalProviderError(empty_message)
    return answer


def _extract_assistant_text(payload: object) -> str:
    return _extract_chat_text(
        payload,
        malformed_message="视觉模型返回格式无效",
        empty_message="视觉模型未返回有效文字",
    )


class VisionProvider:
    """Call an OpenAI-compatible chat-completions vision model."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
        enabled: bool | None = None,
        db: Session | None = None,
    ) -> None:
        runtime = _database_capability("vision", db)
        if runtime is None:
            self.api_key = _resolve_api_key(api_key, "ai_vision_api_key")
            self.base_url = _resolve_base_url(base_url, "ai_vision_base_url")
            self.model_name = str(
                model if model is not None else _setting("ai_vision_model", "")
            ).strip()
            configured_timeout = (
                timeout_seconds
                if timeout_seconds is not None
                else _setting("ai_vision_timeout_seconds", 60)
            )
            configured_enabled = (
                enabled if enabled is not None else _setting("ai_vision_enabled", True)
            )
        else:
            self.api_key = _nonempty_text(api_key) if api_key is not None else runtime.api_key
            selected_base_url = base_url if base_url is not None else runtime.base_url
            self.base_url = (_nonempty_text(selected_base_url) or "").rstrip("/")
            self.model_name = str(
                model if model is not None else runtime.model_name
            ).strip()
            configured_timeout = (
                timeout_seconds if timeout_seconds is not None else runtime.timeout_seconds
            )
            configured_enabled = enabled if enabled is not None else runtime.enabled
        try:
            self.timeout_seconds = float(configured_timeout)
        except (TypeError, ValueError):
            self.timeout_seconds = 60.0
        self.enabled = bool(configured_enabled)

    @property
    def available(self) -> bool:
        return bool(self.enabled and self.api_key and self.base_url and self.model_name)

    def _content_parts(
        self,
        prompt: str,
        images: Iterable[str | Path | BinaryIO | VisionImage],
        *,
        max_total_bytes: int,
    ) -> list[dict[str, Any]]:
        image_list = list(images)
        if not image_list:
            raise MultimodalProviderError("请至少选择一张图片")
        if len(image_list) > MAX_VISION_IMAGES:
            raise MultimodalProviderError("每次最多上传 2 张图片")
        if not isinstance(max_total_bytes, int) or isinstance(max_total_bytes, bool) or max_total_bytes <= 0:
            raise MultimodalProviderError("图片大小限制无效")

        parts: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        total_bytes = 0
        for image in image_list:
            wrapped = image if isinstance(image, VisionImage) else VisionImage(image)
            with _binary_source(wrapped.source) as (stream, name, upload_media_type):
                remaining = max_total_bytes - total_bytes
                if remaining <= 0:
                    raise MultimodalProviderError("图片总大小超过限制")
                try:
                    # Reading at most one byte beyond the remaining allowance
                    # bounds memory even when a file's metadata is untrusted.
                    data = stream.read(remaining + 1)
                except (OSError, ValueError, TypeError):
                    raise MultimodalProviderError("无法读取所选图片") from None
            if not isinstance(data, bytes):
                raise MultimodalProviderError("无法读取所选图片")
            if not data:
                raise MultimodalProviderError("图片文件为空")
            if len(data) > remaining:
                raise MultimodalProviderError("图片总大小超过限制")
            total_bytes += len(data)
            media_type = _guess_image_type(name, data, wrapped.media_type or upload_media_type)
            encoded = base64.b64encode(data).decode("ascii")
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{media_type};base64,{encoded}"},
                }
            )
        return parts

    def _generate_once(
        self,
        prompt: str,
        images: Iterable[str | Path | BinaryIO | VisionImage],
        *,
        max_total_bytes: int,
    ) -> str:
        if not self.available:
            raise MultimodalProviderError("视觉模型服务尚未配置")
        normalized_prompt = str(prompt or "").strip()
        if not normalized_prompt:
            raise MultimodalProviderError("图片问题不能为空")
        content = self._content_parts(
            normalized_prompt,
            images,
            max_total_bytes=max_total_bytes,
        )
        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model_name,
                    "messages": [{"role": "user", "content": content}],
                    # The public application stream is created locally with
                    # chunk_text; compatible providers need only return JSON.
                    "stream": False,
                },
                timeout=self.timeout_seconds,
                follow_redirects=False,
            )
        except (httpx.RequestError, httpx.TimeoutException):
            raise MultimodalProviderError("视觉模型服务暂时不可用，请稍后重试") from None
        except Exception:
            raise MultimodalProviderError("视觉模型请求失败，请稍后重试") from None
        if response.status_code >= 400:
            raise MultimodalProviderError("视觉模型服务暂时不可用，请稍后重试")
        try:
            payload = response.json()
        except (ValueError, TypeError):
            raise MultimodalProviderError("视觉模型返回格式无效") from None
        return _extract_assistant_text(payload)

    def generate(
        self,
        prompt: str,
        images: Iterable[str | Path | BinaryIO | VisionImage],
        *,
        max_total_bytes: int,
    ) -> str:
        if not _VISION_CALL_GATE.acquire(blocking=False):
            raise MultimodalProviderError("图片理解服务正忙，请稍后重试")
        try:
            return self._generate_once(prompt, images, max_total_bytes=max_total_bytes)
        finally:
            _VISION_CALL_GATE.release()

    def stream(
        self,
        prompt: str,
        images: Iterable[str | Path | BinaryIO | VisionImage],
        *,
        max_total_bytes: int,
    ) -> Iterator[str]:
        """Expose a stable local stream for providers that only return JSON."""

        yield from chunk_text(
            self.generate(prompt, images, max_total_bytes=max_total_bytes)
        )


class SpeechTranscriptionProvider:
    """Call Qwen3 chat ASR or a standard audio-transcriptions endpoint."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
        enabled: bool | None = None,
        db: Session | None = None,
    ) -> None:
        runtime = _database_capability("asr", db)
        if runtime is None:
            self.api_key = _resolve_api_key(api_key, "ai_asr_api_key")
            self.base_url = _resolve_base_url(base_url, "ai_asr_base_url")
            self.model_name = str(
                model if model is not None else _setting("ai_asr_model", "")
            ).strip()
            configured_timeout = (
                timeout_seconds
                if timeout_seconds is not None
                else _setting("ai_asr_timeout_seconds", 60)
            )
            configured_enabled = (
                enabled if enabled is not None else _setting("ai_asr_enabled", True)
            )
        else:
            self.api_key = _nonempty_text(api_key) if api_key is not None else runtime.api_key
            selected_base_url = base_url if base_url is not None else runtime.base_url
            self.base_url = (_nonempty_text(selected_base_url) or "").rstrip("/")
            self.model_name = str(
                model if model is not None else runtime.model_name
            ).strip()
            configured_timeout = (
                timeout_seconds if timeout_seconds is not None else runtime.timeout_seconds
            )
            configured_enabled = enabled if enabled is not None else runtime.enabled
        try:
            self.timeout_seconds = float(configured_timeout)
        except (TypeError, ValueError):
            self.timeout_seconds = 60.0
        self.enabled = bool(configured_enabled)

    @property
    def available(self) -> bool:
        return bool(self.enabled and self.api_key and self.base_url and self.model_name)

    @property
    def uses_qwen3_chat_api(self) -> bool:
        return self.model_name.lower().startswith("qwen3-asr")

    @staticmethod
    def _audio_media_type(
        explicit: str | None,
        inferred: str | None,
        filename: str,
    ) -> str:
        media_type = _clean_media_type(explicit) or inferred
        if not media_type:
            media_type = _clean_media_type(mimetypes.guess_type(filename)[0])
        # Python's MIME database often labels WebM/MP4 by their container type;
        # these assets have already been validated as audio by AiMediaService.
        if media_type == "video/webm":
            media_type = "audio/webm"
        elif media_type == "video/mp4":
            media_type = "audio/mp4"
        return media_type or "application/octet-stream"

    def _transcribe_qwen3(
        self,
        stream: BinaryIO,
        *,
        media_type: str,
        language: str | None,
    ) -> str:
        configured_max_bytes = _audio_max_bytes()
        data_url_max_raw_bytes = _qwen3_audio_max_raw_bytes(media_type)
        max_bytes = min(configured_max_bytes, data_url_max_raw_bytes)
        try:
            audio = stream.read(max_bytes + 1)
        except (OSError, ValueError, TypeError):
            raise MultimodalProviderError("无法读取所选录音") from None
        if not isinstance(audio, bytes):
            raise MultimodalProviderError("无法读取所选录音")
        if not audio:
            raise MultimodalProviderError("录音文件为空")
        if len(audio) > max_bytes:
            if data_url_max_raw_bytes < configured_max_bytes:
                approximate_mb = data_url_max_raw_bytes / (1024 * 1024)
                raise MultimodalProviderError(
                    "Qwen3-ASR 使用 Base64 Data URL 传输，"
                    f"录音原文件不能超过约 {approximate_mb:.1f} MB（编码后上限 10 MiB）"
                )
            raise MultimodalProviderError(
                f"录音文件不能超过 {max_bytes // (1024 * 1024)} MB"
            )

        encoded_audio = base64.b64encode(audio).decode("ascii")
        del audio
        data_url = f"data:{media_type};base64,{encoded_audio}"
        # 构造 Data URL 后立即释放中间字符串，避免 JSON 序列化期间同时保留两份 Base64。
        del encoded_audio
        if len(data_url) > DASHSCOPE_ASR_DATA_URL_MAX_BYTES:
            raise MultimodalProviderError("录音 Base64 编码后超过 Qwen3-ASR 的 10 MiB 限制")
        asr_options: dict[str, object] = {"enable_itn": False}
        if language:
            asr_options["language"] = str(language)
        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model_name,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_audio",
                                    "input_audio": {"data": data_url},
                                }
                            ],
                        }
                    ],
                    "stream": False,
                    "asr_options": asr_options,
                },
                timeout=self.timeout_seconds,
                follow_redirects=False,
            )
        except (httpx.RequestError, httpx.TimeoutException):
            raise MultimodalProviderError("语音识别服务暂时不可用，请稍后重试") from None
        except Exception:
            raise MultimodalProviderError("语音识别请求失败，请稍后重试") from None
        if response.status_code >= 400:
            raise MultimodalProviderError("语音识别服务暂时不可用，请稍后重试")
        try:
            payload = response.json()
        except (ValueError, TypeError):
            raise MultimodalProviderError("语音识别返回格式无效") from None
        return _extract_chat_text(
            payload,
            malformed_message="语音识别返回格式无效",
            empty_message="语音识别未返回有效文字",
        )

    def _transcribe_multipart(
        self,
        stream: BinaryIO,
        *,
        filename: str,
        media_type: str,
        language: str | None,
    ) -> str:
        form_data = {"model": self.model_name}
        if language:
            form_data["language"] = str(language)
        try:
            response = httpx.post(
                f"{self.base_url}/audio/transcriptions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                data=form_data,
                # Passing the open stream lets httpx encode multipart in
                # chunks instead of materialising the audio file in memory.
                files={"file": (filename, stream, media_type)},
                timeout=self.timeout_seconds,
                follow_redirects=False,
            )
        except (httpx.RequestError, httpx.TimeoutException):
            raise MultimodalProviderError("语音识别服务暂时不可用，请稍后重试") from None
        except Exception:
            raise MultimodalProviderError("语音识别请求失败，请稍后重试") from None
        if response.status_code >= 400:
            raise MultimodalProviderError("语音识别服务暂时不可用，请稍后重试")
        try:
            payload = response.json()
            text = clean_model_text(payload.get("text")) if isinstance(payload, dict) else ""
        except (ValueError, TypeError):
            raise MultimodalProviderError("语音识别返回格式无效") from None
        if not text:
            raise MultimodalProviderError("语音识别未返回有效文字")
        return text

    def _transcribe_once(
        self,
        file: str | Path | BinaryIO | object,
        *,
        filename: str | None = None,
        content_type: str | None = None,
        language: str | None = None,
    ) -> str:
        if not self.available:
            raise MultimodalProviderError("语音识别服务尚未配置")

        with _binary_source(file) as (stream, inferred_name, inferred_type):
            safe_filename = Path(filename or inferred_name or "audio.bin").name
            media_type = self._audio_media_type(content_type, inferred_type, safe_filename)
            if self.uses_qwen3_chat_api:
                return self._transcribe_qwen3(
                    stream,
                    media_type=media_type,
                    language=language,
                )
            return self._transcribe_multipart(
                stream,
                filename=safe_filename,
                media_type=media_type,
                language=language,
            )

    def transcribe(
        self,
        file: str | Path | BinaryIO | object,
        *,
        filename: str | None = None,
        content_type: str | None = None,
        language: str | None = None,
    ) -> str:
        if not _SPEECH_CALL_GATE.acquire(blocking=False):
            raise MultimodalProviderError("语音识别服务正忙，请稍后重试")
        try:
            return self._transcribe_once(
                file,
                filename=filename,
                content_type=content_type,
                language=language,
            )
        finally:
            _SPEECH_CALL_GATE.release()

from __future__ import annotations

import base64
import hashlib
import ipaddress
import logging
import socket
import struct
import zlib
from dataclasses import dataclass
from datetime import timedelta
from threading import Lock
from time import monotonic
from typing import Any
from urllib.parse import urlparse
from uuid import UUID, uuid4

import httpx
from cryptography.fernet import Fernet, InvalidToken
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from langchain_openai import ChatOpenAI
from sqlalchemy import Integer, and_, case, func, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.time import utc_now
from app.db.session import SessionLocal
from app.models.ai_operation import AiCallLog, AiProviderConfig
from app.models.user import User
from app.schemas.ai_operation import (
    AiAllProviderConfigInput,
    AiCapabilityConfigInput,
    AiCapabilityName,
    AiProviderConfigInput,
    AiProviderPresetData,
)


logger = logging.getLogger(__name__)

DASHSCOPE_COMPATIBLE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DASHSCOPE_NATIVE_BASE_URL = "https://dashscope.aliyuncs.com/api/v1"
AI_CAPABILITIES: tuple[AiCapabilityName, ...] = (
    "text",
    "embedding",
    "vision",
    "asr",
    "image_generation",
)


@dataclass(frozen=True)
class RuntimeLlmConfig:
    config_id: int | None
    source: str
    base_url: str | None
    api_key: str | None
    model_name: str
    temperature: float
    timeout_seconds: int
    streaming_enabled: bool


@dataclass(frozen=True)
class RuntimeCapabilityConfig:
    config_id: int | None
    source: str
    capability: AiCapabilityName
    provider_name: str
    enabled: bool
    base_url: str | None
    api_key: str | None
    model_name: str
    dimensions: int | None
    temperature: float
    timeout_seconds: int
    streaming_enabled: bool


@dataclass
class CapabilityTestOutcome:
    capability: AiCapabilityName
    success: bool
    skipped: bool
    latency_ms: int | None
    message: str
    api_key: str | None
    kept_previous: bool = False
    row: AiProviderConfig | None = None


@dataclass(frozen=True)
class ExistingCredential:
    api_key: str | None
    base_url: str | None
    provider_name: str


def _fernet() -> Fernet:
    secret = settings.ai_config_encryption_key or settings.jwt_secret_key
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_api_key(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_api_key(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError("AI 配置密钥无法解密，请检查 AI_CONFIG_ENCRYPTION_KEY") from exc


def mask_api_key(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:3]}{'*' * 8}{value[-4:]}"


class AiProviderConfigService:
    @staticmethod
    def presets() -> list[AiProviderPresetData]:
        compatible = DASHSCOPE_COMPATIBLE_BASE_URL
        return [
            AiProviderPresetData(
                id="dashscope",
                name="阿里云百炼",
                description="使用一个百炼 API Key 自动配置文本、向量、视觉、语音和配图模型。",
                capabilities={
                    "text": AiCapabilityConfigInput(
                        enabled=True,
                        base_url=compatible,
                        model_name="qwen-plus",
                        timeout_seconds=60,
                        temperature=0.2,
                        streaming_enabled=True,
                    ),
                    "embedding": AiCapabilityConfigInput(
                        enabled=True,
                        base_url=compatible,
                        model_name="text-embedding-v4",
                        timeout_seconds=60,
                        dimensions=1024,
                        streaming_enabled=False,
                    ),
                    "vision": AiCapabilityConfigInput(
                        enabled=True,
                        base_url=compatible,
                        model_name="qwen3-vl-plus",
                        timeout_seconds=90,
                        streaming_enabled=False,
                    ),
                    "asr": AiCapabilityConfigInput(
                        enabled=True,
                        base_url=compatible,
                        model_name="qwen3-asr-flash",
                        timeout_seconds=120,
                        streaming_enabled=False,
                    ),
                    "image_generation": AiCapabilityConfigInput(
                        enabled=True,
                        base_url=DASHSCOPE_NATIVE_BASE_URL,
                        model_name="wan2.7-image-pro",
                        timeout_seconds=180,
                        streaming_enabled=False,
                    ),
                },
            )
        ]

    @staticmethod
    def _provider_from_url(base_url: str | None, fallback: str = "openai_compatible") -> str:
        hostname = (urlparse(base_url or "").hostname or "").lower()
        is_aliyun = hostname == "aliyuncs.com" or hostname.endswith(".aliyuncs.com")
        return "dashscope" if is_aliyun else fallback

    @staticmethod
    def _environment_capability(capability: AiCapabilityName) -> RuntimeCapabilityConfig:
        if capability == "text":
            return RuntimeCapabilityConfig(
                config_id=None,
                source="environment",
                capability=capability,
                provider_name=AiProviderConfigService._provider_from_url(settings.llm_base_url),
                enabled=True,
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key,
                model_name=settings.llm_model,
                dimensions=None,
                temperature=settings.llm_temperature,
                timeout_seconds=settings.llm_timeout_seconds,
                streaming_enabled=True,
            )

        if capability == "embedding":
            provider = str(settings.embedding_provider or "mock").strip().lower()
            model = settings.embedding_model
            dimensions = settings.embedding_dimensions
            if provider == "mock":
                dimensions = 256
                base_url = None
                api_key = None
            elif provider == "dashscope":
                dimensions = 1536 if model in {"text-embedding-v1", "text-embedding-v2"} else dimensions
                base_url = settings.embedding_base_url or DASHSCOPE_COMPATIBLE_BASE_URL
                api_key = settings.dashscope_api_key or settings.embedding_api_key
            else:
                base_url = settings.embedding_base_url
                api_key = settings.embedding_api_key
            return RuntimeCapabilityConfig(
                config_id=None,
                source="environment",
                capability=capability,
                provider_name=provider,
                enabled=True,
                base_url=base_url,
                api_key=api_key,
                model_name=model,
                dimensions=dimensions,
                temperature=0.0,
                timeout_seconds=60,
                streaming_enabled=False,
            )

        if capability in {"vision", "asr"}:
            is_vision = capability == "vision"
            explicit_key = settings.ai_vision_api_key if is_vision else settings.ai_asr_api_key
            explicit_url = settings.ai_vision_base_url if is_vision else settings.ai_asr_base_url
            dashscope_environment = bool(
                settings.dashscope_api_key
                or str(settings.embedding_provider or "").strip().lower() == "dashscope"
            )
            api_key = explicit_key or settings.dashscope_api_key
            if not api_key and str(settings.embedding_provider or "").strip().lower() == "dashscope":
                api_key = settings.embedding_api_key
            base_url = explicit_url
            if not base_url and dashscope_environment:
                base_url = settings.embedding_base_url or DASHSCOPE_COMPATIBLE_BASE_URL
            return RuntimeCapabilityConfig(
                config_id=None,
                source="environment",
                capability=capability,
                provider_name=AiProviderConfigService._provider_from_url(base_url),
                enabled=settings.ai_vision_enabled if is_vision else settings.ai_asr_enabled,
                base_url=base_url,
                api_key=api_key,
                model_name=settings.ai_vision_model if is_vision else settings.ai_asr_model,
                dimensions=None,
                temperature=0.0,
                timeout_seconds=(
                    settings.ai_vision_timeout_seconds
                    if is_vision
                    else settings.ai_asr_timeout_seconds
                ),
                streaming_enabled=False,
            )

        return RuntimeCapabilityConfig(
            config_id=None,
            source="environment",
            capability="image_generation",
            provider_name=AiProviderConfigService._provider_from_url(
                settings.ppt_multimodal_base_url
            ),
            enabled=settings.ppt_multimodal_enabled,
            base_url=settings.ppt_multimodal_base_url,
            api_key=settings.ppt_multimodal_api_key,
            model_name=settings.ppt_multimodal_model,
            dimensions=None,
            temperature=0.0,
            timeout_seconds=settings.ppt_multimodal_timeout_seconds,
            streaming_enabled=False,
        )

    @staticmethod
    def resolve_capability(name: str, db: Session | None = None) -> RuntimeCapabilityConfig:
        if name not in AI_CAPABILITIES:
            raise ValueError(f"不支持的 AI 能力：{name}")
        capability: AiCapabilityName = name  # type: ignore[assignment]
        owns_session = db is None
        session = db or SessionLocal()
        try:
            row = session.scalar(
                select(AiProviderConfig)
                .where(
                    AiProviderConfig.capability == capability,
                    AiProviderConfig.is_active.is_(True),
                )
                .order_by(AiProviderConfig.id.desc())
            )
            if row is not None:
                decrypted = decrypt_api_key(row.api_key_encrypted) if row.enabled else ""
                return RuntimeCapabilityConfig(
                    config_id=row.id,
                    source="database",
                    capability=capability,
                    provider_name=row.provider_name,
                    enabled=row.enabled,
                    base_url=row.base_url,
                    api_key=decrypted or None,
                    model_name=row.model_name,
                    dimensions=row.dimensions,
                    temperature=row.temperature,
                    timeout_seconds=row.timeout_seconds,
                    streaming_enabled=row.streaming_enabled,
                )
        except Exception:
            logger.exception(
                "runtime_ai_capability_config_load_failed_using_environment capability=%s",
                capability,
            )
        finally:
            if owns_session:
                session.close()
        return AiProviderConfigService._environment_capability(capability)

    @staticmethod
    def resolve(db: Session | None = None) -> RuntimeLlmConfig:
        config = AiProviderConfigService.resolve_capability("text", db)
        return RuntimeLlmConfig(
            config_id=config.config_id,
            source=config.source,
            base_url=config.base_url,
            api_key=config.api_key if config.enabled else None,
            model_name=config.model_name,
            temperature=config.temperature,
            timeout_seconds=config.timeout_seconds,
            streaming_enabled=config.streaming_enabled,
        )

    @staticmethod
    def active_row(db: Session, capability: AiCapabilityName) -> AiProviderConfig | None:
        return db.scalar(
            select(AiProviderConfig)
            .where(
                AiProviderConfig.capability == capability,
                AiProviderConfig.is_active.is_(True),
            )
            .order_by(AiProviderConfig.id.desc())
        )

    @staticmethod
    def _existing_credential(
        capability: AiCapabilityName,
        db: Session,
    ) -> ExistingCredential:
        row = AiProviderConfigService.active_row(db, capability)
        if row is not None:
            decrypted = decrypt_api_key(row.api_key_encrypted)
            return ExistingCredential(
                api_key=decrypted or None,
                base_url=row.base_url,
                provider_name=row.provider_name,
            )
        runtime = AiProviderConfigService._environment_capability(capability)
        return ExistingCredential(
            api_key=runtime.api_key,
            base_url=runtime.base_url,
            provider_name=runtime.provider_name,
        )

    @staticmethod
    def _hostname(base_url: str | None) -> str | None:
        hostname = (urlparse(base_url or "").hostname or "").strip().lower().rstrip(".")
        if not hostname:
            return None
        try:
            return hostname.encode("idna").decode("ascii")
        except UnicodeError:
            return hostname

    @staticmethod
    def _provider_family(provider_name: str, base_url: str | None) -> str:
        normalized = provider_name.strip().lower().replace("-", "_")
        if normalized == "dashscope":
            return "dashscope"
        if normalized in {"openai", "openai_compatible"}:
            hostname = AiProviderConfigService._hostname(base_url) or ""
            # Rows created before provider_name existed were backfilled as
            # openai_compatible; infer DashScope only for that legacy label.
            is_aliyun = hostname == "aliyuncs.com" or hostname.endswith(".aliyuncs.com")
            return "dashscope" if is_aliyun else "openai_compatible"
        if normalized == "custom":
            return "openai_compatible"
        return normalized

    @staticmethod
    def _reusable_key(
        capability: AiCapabilityName,
        db: Session,
        *,
        target_base_url: str,
        target_provider_name: str,
    ) -> str:
        current = AiProviderConfigService._existing_credential(capability, db)
        if not current.api_key:
            raise ValueError("请填写 API Key")
        current_host = AiProviderConfigService._hostname(current.base_url)
        target_host = AiProviderConfigService._hostname(target_base_url)
        if not current_host or not target_host or current_host != target_host:
            raise ValueError("接口主机已变化，请重新输入 API Key，旧密钥不会发送到新主机")
        current_provider = AiProviderConfigService._provider_family(
            current.provider_name,
            current.base_url,
        )
        target_provider = AiProviderConfigService._provider_family(
            target_provider_name,
            target_base_url,
        )
        if current_provider != target_provider:
            raise ValueError("供应商已变化，请重新输入 API Key")
        return current.api_key

    @staticmethod
    def _effective_key(payload: AiProviderConfigInput, db: Session) -> str:
        if payload.api_key and payload.api_key.strip():
            return payload.api_key.strip()
        return AiProviderConfigService._reusable_key(
            "text",
            db,
            target_base_url=payload.base_url,
            target_provider_name=AiProviderConfigService._provider_from_url(payload.base_url),
        )

    @staticmethod
    def _validate_remote_url(base_url: str) -> None:
        parsed = urlparse(base_url)
        hostname = (parsed.hostname or "").strip().lower().rstrip(".")
        if parsed.scheme != "https" or not hostname:
            raise ValueError("接口地址必须是有效的 https:// 地址，禁止明文传输 API Key")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("接口地址不能包含用户名或密码")
        if parsed.query or parsed.fragment:
            raise ValueError("接口地址不能包含查询参数或片段")
        if hostname in {
            "localhost",
            "metadata.google.internal",
            "metadata.azure.internal",
        } or hostname.endswith(".localhost"):
            raise ValueError("不允许访问本机或云主机元数据地址")
        literal_address: ipaddress.IPv4Address | ipaddress.IPv6Address | None = None
        try:
            literal_address = ipaddress.ip_address(hostname)
        except ValueError:
            # inet_aton only parses IPv4 literals and catches legacy decimal,
            # octal and hexadecimal spellings without performing a DNS lookup.
            try:
                literal_address = ipaddress.ip_address(socket.inet_aton(hostname))
            except OSError:
                pass
        if literal_address is not None and not literal_address.is_global:
            raise ValueError("不允许访问内网、本机或云主机元数据地址")
        try:
            port = parsed.port or 443
        except ValueError as exc:
            raise ValueError("接口地址端口无效") from exc
        try:
            address_info = socket.getaddrinfo(
                hostname,
                port,
                family=socket.AF_UNSPEC,
                type=socket.SOCK_STREAM,
            )
        except OSError as exc:
            raise ValueError("接口域名无法解析，请检查地址后重试") from exc
        resolved_addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
        for _family, _socktype, _protocol, _canonical_name, socket_address in address_info:
            try:
                resolved_addresses.append(
                    ipaddress.ip_address(str(socket_address[0]).split("%", 1)[0])
                )
            except (ValueError, IndexError, TypeError):
                raise ValueError("接口域名解析结果无效") from None
        if not resolved_addresses:
            raise ValueError("接口域名无法解析，请检查地址后重试")
        if any(not address.is_global for address in resolved_addresses):
            raise ValueError("接口域名解析到内网、本机或保留地址，已拒绝访问")

    @staticmethod
    def _silent_wav_data_url() -> str:
        sample_rate = 8000
        samples = b"\x00\x00" * sample_rate
        header = (
            b"RIFF"
            + struct.pack("<I", 36 + len(samples))
            + b"WAVEfmt "
            + struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16)
            + b"data"
            + struct.pack("<I", len(samples))
        )
        return "data:audio/wav;base64," + base64.b64encode(header + samples).decode("ascii")

    @staticmethod
    def _tiny_png_data_url() -> str:
        width = height = 32
        scanlines = b"".join(
            b"\x00" + (b"\xff\xff\xff" * width)
            for _ in range(height)
        )

        def chunk(kind: bytes, data: bytes) -> bytes:
            return (
                struct.pack(">I", len(data))
                + kind
                + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
            )

        png = (
            b"\x89PNG\r\n\x1a\n"
            + chunk("IHDR".encode("ascii"), struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk("IDAT".encode("ascii"), zlib.compress(scanlines))
            + chunk("IEND".encode("ascii"), b"")
        )
        return "data:image/png;base64," + base64.b64encode(png).decode("ascii")

    @staticmethod
    def _remote_test(
        capability: AiCapabilityName,
        config: AiCapabilityConfigInput,
        api_key: str | None,
        credential_error: str | None = None,
    ) -> CapabilityTestOutcome:
        try:
            if config.base_url:
                AiProviderConfigService._validate_remote_url(config.base_url)
            if not config.enabled:
                return CapabilityTestOutcome(
                    capability=capability,
                    success=True,
                    skipped=True,
                    latency_ms=None,
                    message="该能力已禁用，未发送远程测试请求",
                    api_key=api_key,
                )
            if capability == "image_generation":
                hostname = AiProviderConfigService._hostname(config.base_url) or ""
                if hostname != "aliyuncs.com" and not hostname.endswith(".aliyuncs.com"):
                    raise ValueError(
                        "图片生成运行时仅支持阿里云百炼 Wan 协议，"
                        "接口地址必须使用 aliyuncs.com 域名"
                    )
            if credential_error:
                raise ValueError(credential_error)
            if not api_key:
                raise ValueError("请填写 API Key")
            if capability == "image_generation":
                return CapabilityTestOutcome(
                    capability=capability,
                    success=True,
                    skipped=True,
                    latency_ms=None,
                    message="图片生成配置校验通过；为避免产生费用，本次未实际出图",
                    api_key=api_key,
                )

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            endpoint: str
            kwargs: dict[str, Any]
            if capability == "embedding":
                endpoint = f"{config.base_url}/embeddings"
                body: dict[str, Any] = {
                    "model": config.model_name,
                    "input": ["连通性测试"],
                }
                if (
                    config.dimensions is not None
                    and config.model_name in {"text-embedding-v3", "text-embedding-v4"}
                ):
                    body["dimensions"] = config.dimensions
                kwargs = {"headers": headers, "json": body}
            elif capability == "vision":
                endpoint = f"{config.base_url}/chat/completions"
                # 32x32 PNG 仅用于验证视觉请求格式，避免读取或上传用户文件。
                tiny_png = AiProviderConfigService._tiny_png_data_url()
                kwargs = {
                    "headers": headers,
                    "json": {
                        "model": config.model_name,
                        "messages": [{
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "只回复 OK"},
                                {"type": "image_url", "image_url": {"url": tiny_png}},
                            ],
                        }],
                        "max_tokens": 8,
                        "stream": False,
                    },
                }
            elif capability == "asr" and config.model_name.lower().startswith("qwen3-asr"):
                endpoint = f"{config.base_url}/chat/completions"
                kwargs = {
                    "headers": headers,
                    "json": {
                        "model": config.model_name,
                        "messages": [{
                            "role": "user",
                            "content": [{
                                "type": "input_audio",
                                "input_audio": {"data": AiProviderConfigService._silent_wav_data_url()},
                            }],
                        }],
                        "stream": False,
                        "asr_options": {"enable_itn": False},
                    },
                }
            elif capability == "asr":
                endpoint = f"{config.base_url}/audio/transcriptions"
                wav_url = AiProviderConfigService._silent_wav_data_url()
                audio = base64.b64decode(wav_url.split(",", 1)[1])
                kwargs = {
                    "headers": {"Authorization": f"Bearer {api_key}"},
                    "data": {"model": config.model_name},
                    "files": {"file": ("connectivity-test.wav", audio, "audio/wav")},
                }
            else:
                endpoint = f"{config.base_url}/chat/completions"
                kwargs = {
                    "headers": headers,
                    "json": {
                        "model": config.model_name,
                        "messages": [{"role": "user", "content": "只回复 OK"}],
                        "temperature": 0,
                        "max_tokens": 8,
                        "stream": False,
                    },
                }

            started = monotonic()
            response = httpx.post(
                endpoint,
                timeout=min(config.timeout_seconds, 30),
                follow_redirects=False,
                **kwargs,
            )
            response.raise_for_status()
            data = response.json()
            if capability == "embedding":
                items = data.get("data") if isinstance(data, dict) else None
                embedding = items[0].get("embedding") if items and isinstance(items[0], dict) else None
                if not isinstance(embedding, list) or not embedding:
                    raise ValueError("接口返回成功，但没有 embedding 内容")
                expected_dimensions = (
                    1536
                    if config.model_name in {"text-embedding-v1", "text-embedding-v2"}
                    else config.dimensions
                )
                if expected_dimensions is not None and len(embedding) != expected_dimensions:
                    raise ValueError(
                        f"Embedding 返回 {len(embedding)} 维，与配置的 {expected_dimensions} 维不一致"
                    )
            elif capability == "asr" and not config.model_name.lower().startswith("qwen3-asr"):
                if not isinstance(data, dict) or "text" not in data:
                    raise ValueError("接口返回成功，但没有转写结果")
            else:
                choices = data.get("choices") if isinstance(data, dict) else None
                if not choices:
                    raise ValueError("接口返回成功，但没有 choices 内容")
            latency = round((monotonic() - started) * 1000)
            labels = {
                "text": "文本对话",
                "embedding": "向量模型",
                "vision": "视觉模型",
                "asr": "语音识别",
            }
            return CapabilityTestOutcome(
                capability=capability,
                success=True,
                skipped=False,
                latency_ms=latency,
                message=f"{labels[capability]}响应正常，耗时 {latency} ms",
                api_key=api_key,
            )
        except Exception as exc:
            detail = str(exc).strip() or type(exc).__name__
            if api_key:
                detail = detail.replace(api_key, "***")
            return CapabilityTestOutcome(
                capability=capability,
                success=False,
                skipped=False,
                latency_ms=None,
                message=f"{capability} 连通性测试失败：{detail[:500]}",
                api_key=api_key,
            )

    @staticmethod
    def test(payload: AiProviderConfigInput, db: Session) -> tuple[int, str, str]:
        api_key = AiProviderConfigService._effective_key(payload, db)
        outcome = AiProviderConfigService._remote_test(
            "text",
            AiCapabilityConfigInput(
                enabled=True,
                base_url=payload.base_url,
                model_name=payload.model_name,
                timeout_seconds=payload.timeout_seconds,
                temperature=payload.temperature,
                streaming_enabled=payload.streaming_enabled,
            ),
            api_key,
        )
        if not outcome.success:
            raise ValueError(outcome.message)
        return outcome.latency_ms or 0, api_key, outcome.message

    @staticmethod
    def activate(payload: AiProviderConfigInput, db: Session, user: User) -> AiProviderConfig:
        latency, api_key, message = AiProviderConfigService.test(payload, db)
        db.execute(
            update(AiProviderConfig)
            .where(
                AiProviderConfig.capability == "text",
                AiProviderConfig.is_active.is_(True),
            )
            .values(is_active=False)
        )
        row = AiProviderConfig(
            capability="text",
            provider_name=AiProviderConfigService._provider_from_url(payload.base_url),
            enabled=True,
            base_url=payload.base_url,
            model_name=payload.model_name,
            api_key_encrypted=encrypt_api_key(api_key),
            dimensions=None,
            temperature=payload.temperature,
            timeout_seconds=payload.timeout_seconds,
            streaming_enabled=payload.streaming_enabled,
            is_active=True,
            created_by=user.id,
            last_test_status="passed",
            last_test_message=message,
            last_test_time=utc_now(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        logger.info("ai_provider_config_activated config_id=%s user_id=%s latency_ms=%s", row.id, user.id, latency)
        return row

    @staticmethod
    def test_all(
        payload: AiAllProviderConfigInput,
        db: Session,
    ) -> dict[AiCapabilityName, CapabilityTestOutcome]:
        outcomes: dict[AiCapabilityName, CapabilityTestOutcome] = {}
        for capability, config in payload.capabilities.items():
            # A capability-specific credential wins.  The shared credential is
            # only a convenience fallback for providers whose models share one
            # account, such as DashScope.
            key = config.api_key or payload.api_key
            credential_error: str | None = None
            if not key:
                try:
                    key = AiProviderConfigService._reusable_key(
                        capability,
                        db,
                        target_base_url=config.base_url,
                        target_provider_name=AiProviderConfigService._provider_from_url(
                            config.base_url,
                            fallback=payload.provider_name,
                        ),
                    )
                except ValueError as exc:
                    # Disabling is allowed without a credential.  Changed-host
                    # credentials are deliberately discarded rather than being
                    # associated with the new host for a later re-enable.
                    if config.enabled:
                        credential_error = str(exc)
                    key = None
            outcomes[capability] = AiProviderConfigService._remote_test(
                capability,
                config,
                key,
                credential_error,
            )
        return outcomes

    @staticmethod
    def activate_all(
        payload: AiAllProviderConfigInput,
        db: Session,
        user: User,
    ) -> dict[AiCapabilityName, CapabilityTestOutcome]:
        outcomes = AiProviderConfigService.test_all(payload, db)
        now = utc_now()
        for capability, outcome in outcomes.items():
            if not outcome.success:
                outcome.kept_previous = True
                continue
            config = payload.capabilities[capability]
            db.execute(
                update(AiProviderConfig)
                .where(
                    AiProviderConfig.capability == capability,
                    AiProviderConfig.is_active.is_(True),
                )
                .values(is_active=False)
            )
            row = AiProviderConfig(
                capability=capability,
                provider_name=AiProviderConfigService._provider_from_url(
                    config.base_url,
                    fallback=payload.provider_name,
                ),
                enabled=config.enabled,
                base_url=config.base_url,
                model_name=config.model_name,
                api_key_encrypted=encrypt_api_key(outcome.api_key or ""),
                dimensions=(
                    1536
                    if capability == "embedding"
                    and config.model_name in {"text-embedding-v1", "text-embedding-v2"}
                    else config.dimensions
                    if capability == "embedding"
                    else None
                ),
                temperature=(
                    config.temperature
                    if config.temperature is not None
                    else (0.2 if capability == "text" else 0.0)
                ),
                timeout_seconds=config.timeout_seconds,
                streaming_enabled=(
                    config.streaming_enabled
                    if config.streaming_enabled is not None
                    else capability == "text"
                ),
                is_active=True,
                created_by=user.id,
                last_test_status=(
                    "disabled"
                    if not config.enabled
                    else "validated"
                    if capability == "image_generation"
                    else "passed"
                ),
                last_test_message=outcome.message,
                last_test_time=now,
            )
            db.add(row)
            db.flush()
            outcome.row = row
        db.commit()
        for outcome in outcomes.values():
            if outcome.row is not None:
                db.refresh(outcome.row)
        logger.info(
            "ai_capability_configs_updated user_id=%s updated=%s kept=%s",
            user.id,
            [name for name, item in outcomes.items() if item.success],
            [name for name, item in outcomes.items() if item.kept_previous],
        )
        return outcomes


class AiCallAuditHandler(BaseCallbackHandler):
    """记录调用元数据；不保存提示词和模型正文。审计失败不影响模型调用。"""

    def __init__(self, *, feature: str, config: RuntimeLlmConfig, user_id: int | None, streaming: bool) -> None:
        self.feature = feature[:80]
        self.config = config
        self.user_id = user_id
        self.streaming = streaming
        self._rows: dict[str, tuple[int, float]] = {}
        self._lock = Lock()

    @staticmethod
    def _text_length(value: Any) -> int:
        if isinstance(value, str):
            return len(value)
        if isinstance(value, list):
            return sum(AiCallAuditHandler._text_length(item) for item in value)
        content = getattr(value, "content", None)
        return AiCallAuditHandler._text_length(content) if content is not None else len(str(value))

    @staticmethod
    def _token_count(value: object) -> int | None:
        if isinstance(value, bool) or value is None:
            return None
        try:
            count = int(value)
        except (TypeError, ValueError):
            return None
        return count if count >= 0 else None

    @classmethod
    def _token_usage(cls, result: LLMResult | Any) -> tuple[int | None, int | None]:
        llm_output = getattr(result, "llm_output", None) or {}
        provider_usage = llm_output.get("token_usage", {}) if isinstance(llm_output, dict) else {}
        if not isinstance(provider_usage, dict):
            provider_usage = {}
        prompt_tokens = cls._token_count(
            provider_usage.get("prompt_tokens", provider_usage.get("input_tokens"))
        )
        completion_tokens = cls._token_count(
            provider_usage.get("completion_tokens", provider_usage.get("output_tokens"))
        )

        if prompt_tokens is not None and completion_tokens is not None:
            return prompt_tokens, completion_tokens
        for group in getattr(result, "generations", None) or []:
            for generation in group:
                message = getattr(generation, "message", None)
                metadata = getattr(message, "usage_metadata", None)
                if metadata is None:
                    metadata = getattr(generation, "usage_metadata", None)
                if not isinstance(metadata, dict):
                    continue
                if prompt_tokens is None:
                    prompt_tokens = cls._token_count(
                        metadata.get("input_tokens", metadata.get("prompt_tokens"))
                    )
                if completion_tokens is None:
                    completion_tokens = cls._token_count(
                        metadata.get("output_tokens", metadata.get("completion_tokens"))
                    )
                if prompt_tokens is not None and completion_tokens is not None:
                    return prompt_tokens, completion_tokens
        return prompt_tokens, completion_tokens

    def _start(self, run_id: UUID, input_chars: int) -> None:
        key = str(run_id)
        with self._lock:
            if key in self._rows:
                return
        try:
            with SessionLocal() as db:
                row = AiCallLog(
                    request_id=key or uuid4().hex,
                    user_id=self.user_id,
                    feature=self.feature,
                    provider_config_id=self.config.config_id,
                    model_name=self.config.model_name,
                    base_url=self.config.base_url,
                    status="running",
                    streaming=self.streaming,
                    input_chars=input_chars,
                    started_time=utc_now(),
                )
                db.add(row)
                db.commit()
                db.refresh(row)
                with self._lock:
                    self._rows[key] = (row.id, monotonic())
        except Exception:
            logger.exception("ai_call_audit_start_failed")

    def on_chat_model_start(self, serialized: dict[str, Any], messages: list[list[Any]], *, run_id: UUID, **kwargs: Any) -> None:
        self._start(run_id, sum(self._text_length(message) for batch in messages for message in batch))

    def on_llm_start(self, serialized: dict[str, Any], prompts: list[str], *, run_id: UUID, **kwargs: Any) -> None:
        self._start(run_id, sum(len(prompt) for prompt in prompts))

    def _finish(self, run_id: UUID, *, status: str, output_chars: int = 0, error: BaseException | None = None, result: LLMResult | None = None) -> None:
        key = str(run_id)
        with self._lock:
            tracked = self._rows.pop(key, None)
        if tracked is None:
            return
        row_id, started = tracked
        prompt_tokens, completion_tokens = self._token_usage(result) if result else (None, None)
        try:
            with SessionLocal() as db:
                row = db.get(AiCallLog, row_id)
                if row is None:
                    return
                row.status = status
                row.output_chars = output_chars
                row.prompt_tokens = prompt_tokens
                row.completion_tokens = completion_tokens
                row.latency_ms = round((monotonic() - started) * 1000)
                row.finished_time = utc_now()
                if error is not None:
                    row.error_type = type(error).__name__[:120]
                    row.error_message = (str(error).strip() or type(error).__name__)[:1000]
                db.commit()
        except Exception:
            logger.exception("ai_call_audit_finish_failed")

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        output_chars = sum(self._text_length(item.text) for group in response.generations for item in group)
        self._finish(run_id, status="success", output_chars=output_chars, result=response)

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self._finish(run_id, status="failed", error=error)


def build_chat_model(
    *,
    feature: str,
    user_id: int | None = None,
    db: Session | None = None,
    temperature: float | None = None,
    timeout: int | None = None,
    max_tokens: int | None = None,
    streaming: bool = False,
) -> tuple[ChatOpenAI, RuntimeLlmConfig]:
    config = AiProviderConfigService.resolve(db)
    if not config.api_key:
        raise RuntimeError("尚未配置 LLM_API_KEY")
    effective_streaming = streaming and config.streaming_enabled
    handler = AiCallAuditHandler(feature=feature, config=config, user_id=user_id, streaming=effective_streaming)
    model_options: dict[str, Any] = {
        "api_key": config.api_key,
        "base_url": config.base_url,
        "model": config.model_name,
        "temperature": config.temperature if temperature is None else temperature,
        "timeout": config.timeout_seconds if timeout is None else timeout,
        "streaming": effective_streaming,
        "callbacks": [handler],
    }
    if max_tokens is not None:
        # Some OpenAI-compatible gateways interpret an omitted output budget as
        # zero.  Structured Agent responses must always send an explicit,
        # positive budget.
        model_options["max_tokens"] = max(1, int(max_tokens))
    hostname = AiProviderConfigService._hostname(config.base_url) or ""
    supports_stream_usage = hostname == "api.openai.com" or (
        hostname.startswith("dashscope") and hostname.endswith(".aliyuncs.com")
    )
    if effective_streaming and supports_stream_usage:
        # Unknown OpenAI-compatible gateways may reject stream_options.  Enable
        # usage chunks only for providers whose compatible APIs support them.
        model_options["stream_usage"] = True
    model = ChatOpenAI(**model_options)
    return model, config


class AiOperationQueryService:
    @staticmethod
    def list_logs(db: Session, *, status: str | None, feature: str | None, limit: int) -> list[tuple[AiCallLog, str | None]]:
        statement = (
            select(AiCallLog, User.username)
            .outerjoin(User, User.id == AiCallLog.user_id)
            .order_by(AiCallLog.started_time.desc())
            .limit(limit)
        )
        if status:
            statement = statement.where(AiCallLog.status == status)
        if feature:
            statement = statement.where(AiCallLog.feature == feature)
        return list(db.execute(statement).all())

    @staticmethod
    def summary(db: Session) -> dict[str, Any]:
        since = utc_now() - timedelta(hours=24)
        has_usage = and_(
            AiCallLog.prompt_tokens.is_not(None),
            AiCallLog.completion_tokens.is_not(None),
        )
        (
            total,
            success,
            failed,
            average,
            prompt_tokens,
            completion_tokens,
            total_tokens,
            tokenized_calls,
        ) = db.execute(
            select(
                func.count(AiCallLog.id),
                func.sum(func.cast(AiCallLog.status == "success", Integer)),
                func.sum(func.cast(AiCallLog.status == "failed", Integer)),
                func.avg(AiCallLog.latency_ms),
                func.sum(case((has_usage, AiCallLog.prompt_tokens), else_=None)),
                func.sum(case((has_usage, AiCallLog.completion_tokens), else_=None)),
                func.sum(
                    case(
                        (
                            has_usage,
                            AiCallLog.prompt_tokens + AiCallLog.completion_tokens,
                        ),
                        else_=None,
                    )
                ),
                func.sum(case((has_usage, 1), else_=0)),
            ).where(AiCallLog.started_time >= since)
        ).one()
        model_usage_rows = db.execute(
            select(
                AiCallLog.model_name,
                func.count(AiCallLog.id),
                func.sum(case((has_usage, 1), else_=0)),
                func.sum(case((has_usage, AiCallLog.prompt_tokens), else_=None)),
                func.sum(case((has_usage, AiCallLog.completion_tokens), else_=None)),
                func.sum(
                    case(
                        (
                            has_usage,
                            AiCallLog.prompt_tokens + AiCallLog.completion_tokens,
                        ),
                        else_=None,
                    )
                ),
            )
            .where(AiCallLog.started_time >= since)
            .group_by(AiCallLog.model_name)
        ).all()
        model_token_usage = [
            {
                "model_name": model_name,
                "call_count": int(call_count or 0),
                "tokenized_calls": int(model_tokenized_calls or 0),
                "prompt_tokens": (
                    int(model_prompt_tokens)
                    if model_prompt_tokens is not None
                    else None
                ),
                "completion_tokens": (
                    int(model_completion_tokens)
                    if model_completion_tokens is not None
                    else None
                ),
                "total_tokens": (
                    int(model_total_tokens)
                    if model_total_tokens is not None
                    else None
                ),
            }
            for (
                model_name,
                call_count,
                model_tokenized_calls,
                model_prompt_tokens,
                model_completion_tokens,
                model_total_tokens,
            ) in model_usage_rows
        ]
        model_token_usage.sort(
            key=lambda item: (
                item["total_tokens"] is None,
                -(item["total_tokens"] or 0),
                item["model_name"],
            )
        )
        running = db.scalar(select(func.count(AiCallLog.id)).where(AiCallLog.status == "running")) or 0
        config = AiProviderConfigService.resolve(db)
        total_value = int(total or 0)
        success_value = int(success or 0)
        return {
            "total_24h": total_value,
            "success_24h": success_value,
            "failed_24h": int(failed or 0),
            "running": int(running),
            "average_latency_ms": round(float(average)) if average is not None else None,
            "success_rate": round(success_value / total_value, 4) if total_value else 1.0,
            "prompt_tokens_24h": int(prompt_tokens) if prompt_tokens is not None else None,
            "completion_tokens_24h": (
                int(completion_tokens) if completion_tokens is not None else None
            ),
            "total_tokens_24h": int(total_tokens) if total_tokens is not None else None,
            "tokenized_calls_24h": int(tokenized_calls or 0),
            "model_token_usage_24h": model_token_usage,
            "active_model": config.model_name,
            "config_source": config.source,
        }

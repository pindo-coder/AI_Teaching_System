from __future__ import annotations

import base64
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
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
from sqlalchemy import Integer, func, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.ai_operation import AiCallLog, AiProviderConfig
from app.models.user import User
from app.schemas.ai_operation import AiProviderConfigInput


logger = logging.getLogger(__name__)


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
    def resolve(db: Session | None = None) -> RuntimeLlmConfig:
        owns_session = db is None
        session = db or SessionLocal()
        try:
            row = session.scalar(
                select(AiProviderConfig)
                .where(AiProviderConfig.is_active.is_(True))
                .order_by(AiProviderConfig.id.desc())
            )
            if row is not None:
                return RuntimeLlmConfig(
                    config_id=row.id,
                    source="database",
                    base_url=row.base_url,
                    api_key=decrypt_api_key(row.api_key_encrypted),
                    model_name=row.model_name,
                    temperature=row.temperature,
                    timeout_seconds=row.timeout_seconds,
                    streaming_enabled=row.streaming_enabled,
                )
        except Exception:
            logger.exception("runtime_ai_config_load_failed_using_environment")
        finally:
            if owns_session:
                session.close()
        return RuntimeLlmConfig(
            config_id=None,
            source="environment",
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model_name=settings.llm_model,
            temperature=settings.llm_temperature,
            timeout_seconds=settings.llm_timeout_seconds,
            streaming_enabled=True,
        )

    @staticmethod
    def _effective_key(payload: AiProviderConfigInput, db: Session) -> str:
        if payload.api_key and payload.api_key.strip():
            return payload.api_key.strip()
        current = AiProviderConfigService.resolve(db)
        if not current.api_key:
            raise ValueError("请填写 API Key")
        return current.api_key

    @staticmethod
    def test(payload: AiProviderConfigInput, db: Session) -> tuple[int, str, str]:
        api_key = AiProviderConfigService._effective_key(payload, db)
        parsed = urlparse(payload.base_url)
        if parsed.hostname in {"169.254.169.254", "metadata.google.internal"}:
            raise ValueError("不允许访问云主机元数据地址")
        endpoint = f"{payload.base_url.rstrip('/')}/chat/completions"
        started = monotonic()
        try:
            response = httpx.post(
                endpoint,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": payload.model_name,
                    "messages": [{"role": "user", "content": "只回复 OK"}],
                    "temperature": 0,
                    "max_tokens": 8,
                    "stream": False,
                },
                timeout=min(payload.timeout_seconds, 30),
            )
            response.raise_for_status()
            data = response.json()
            choices = data.get("choices") if isinstance(data, dict) else None
            if not choices:
                raise ValueError("接口返回成功，但没有 choices 内容")
        except Exception as exc:
            detail = str(exc).strip() or type(exc).__name__
            raise ValueError(f"模型连通性测试失败：{detail[:500]}") from exc
        latency = round((monotonic() - started) * 1000)
        return latency, api_key, f"对话接口响应正常，耗时 {latency} ms"

    @staticmethod
    def activate(payload: AiProviderConfigInput, db: Session, user: User) -> AiProviderConfig:
        latency, api_key, message = AiProviderConfigService.test(payload, db)
        db.execute(update(AiProviderConfig).where(AiProviderConfig.is_active.is_(True)).values(is_active=False))
        row = AiProviderConfig(
            base_url=payload.base_url,
            model_name=payload.model_name,
            api_key_encrypted=encrypt_api_key(api_key),
            temperature=payload.temperature,
            timeout_seconds=payload.timeout_seconds,
            streaming_enabled=payload.streaming_enabled,
            is_active=True,
            created_by=user.id,
            last_test_status="passed",
            last_test_message=message,
            last_test_time=datetime.utcnow(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        logger.info("ai_provider_config_activated config_id=%s user_id=%s latency_ms=%s", row.id, user.id, latency)
        return row


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
                    started_time=datetime.utcnow(),
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
        usage = (result.llm_output or {}).get("token_usage", {}) if result else {}
        try:
            with SessionLocal() as db:
                row = db.get(AiCallLog, row_id)
                if row is None:
                    return
                row.status = status
                row.output_chars = output_chars
                row.prompt_tokens = usage.get("prompt_tokens")
                row.completion_tokens = usage.get("completion_tokens")
                row.latency_ms = round((monotonic() - started) * 1000)
                row.finished_time = datetime.utcnow()
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
    streaming: bool = False,
) -> tuple[ChatOpenAI, RuntimeLlmConfig]:
    config = AiProviderConfigService.resolve(db)
    if not config.api_key:
        raise RuntimeError("尚未配置 LLM_API_KEY")
    effective_streaming = streaming and config.streaming_enabled
    handler = AiCallAuditHandler(feature=feature, config=config, user_id=user_id, streaming=effective_streaming)
    model = ChatOpenAI(
        api_key=config.api_key,
        base_url=config.base_url,
        model=config.model_name,
        temperature=config.temperature if temperature is None else temperature,
        timeout=config.timeout_seconds if timeout is None else timeout,
        streaming=effective_streaming,
        callbacks=[handler],
    )
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
        since = datetime.utcnow() - timedelta(hours=24)
        total, success, failed, average = db.execute(
            select(
                func.count(AiCallLog.id),
                func.sum(func.cast(AiCallLog.status == "success", Integer)),
                func.sum(func.cast(AiCallLog.status == "failed", Integer)),
                func.avg(AiCallLog.latency_ms),
            ).where(AiCallLog.started_time >= since)
        ).one()
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
            "active_model": config.model_name,
            "config_source": config.source,
        }

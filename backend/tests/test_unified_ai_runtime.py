from types import SimpleNamespace

import pytest

from app.api.v1.endpoints.agents import agent_capabilities
from app.core.config import settings
from app.rag.embeddings import get_embedding_profile, get_embeddings
from app.services.ai_operation_service import AiProviderConfigService
from app.services.multimodal_provider import SpeechTranscriptionProvider, VisionProvider
from app.services.ppt_multimodal_service import PptMultimodalService


def _runtime(capability: str, **overrides):
    values = {
        "config_id": 12,
        "source": "database",
        "capability": capability,
        "provider_name": "dashscope",
        "enabled": True,
        "base_url": "https://runtime.example/v1",
        "api_key": "sk-runtime",
        "model_name": f"runtime-{capability}",
        "dimensions": None,
        "temperature": 0.2,
        "timeout_seconds": 37,
        "streaming_enabled": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_embedding_profile_and_client_share_runtime_configuration(monkeypatch) -> None:
    runtime = _runtime(
        "embedding",
        provider_name="dashscope",
        model_name="text-embedding-v4",
        dimensions=768,
    )
    captured: dict[str, object] = {}

    class FakeEmbeddings:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(
        AiProviderConfigService,
        "resolve_capability",
        lambda capability, db=None: runtime,
    )
    monkeypatch.setattr("app.rag.embeddings.OpenAICompatibleEmbeddings", FakeEmbeddings)

    profile = get_embedding_profile()
    embedding = get_embeddings()

    assert profile.provider == "dashscope"
    assert profile.model == "text-embedding-v4"
    assert profile.dimensions == 768
    assert isinstance(embedding, FakeEmbeddings)
    assert captured == {
        "api_key": "sk-runtime",
        "base_url": "https://runtime.example/v1",
        "model": "text-embedding-v4",
        "dimensions": 768,
        "timeout_seconds": 37,
    }


def test_disabled_runtime_embedding_does_not_fall_back_to_environment(monkeypatch) -> None:
    runtime = _runtime("embedding", enabled=False, dimensions=1024)
    monkeypatch.setattr(settings, "embedding_provider", "mock")
    monkeypatch.setattr(
        AiProviderConfigService,
        "resolve_capability",
        lambda capability, db=None: runtime,
    )

    with pytest.raises(RuntimeError, match="已禁用"):
        get_embeddings()


def test_vision_and_asr_use_independent_runtime_capabilities(monkeypatch) -> None:
    configs = {
        "vision": _runtime(
            "vision",
            base_url="https://vision.example/v1/",
            api_key="sk-vision-runtime",
            model_name="qwen-vl-runtime",
            timeout_seconds=41,
        ),
        "asr": _runtime(
            "asr",
            base_url="https://asr.example/v1/",
            api_key="sk-asr-runtime",
            model_name="qwen3-asr-runtime",
            timeout_seconds=52,
        ),
    }
    monkeypatch.setattr(
        AiProviderConfigService,
        "resolve_capability",
        lambda capability, db=None: configs[capability],
    )

    vision = VisionProvider()
    speech = SpeechTranscriptionProvider()

    assert (vision.api_key, vision.base_url, vision.model_name, vision.timeout_seconds) == (
        "sk-vision-runtime",
        "https://vision.example/v1",
        "qwen-vl-runtime",
        41.0,
    )
    assert (speech.api_key, speech.base_url, speech.model_name, speech.timeout_seconds) == (
        "sk-asr-runtime",
        "https://asr.example/v1",
        "qwen3-asr-runtime",
        52.0,
    )
    assert vision.available is True
    assert speech.available is True


def test_explicit_media_arguments_override_runtime_configuration(monkeypatch) -> None:
    monkeypatch.setattr(
        AiProviderConfigService,
        "resolve_capability",
        lambda capability, db=None: _runtime(capability, enabled=False),
    )

    vision = VisionProvider(
        api_key="sk-explicit",
        base_url="https://explicit.example/v1/",
        model="explicit-vision",
        timeout_seconds=9,
        enabled=True,
    )

    assert vision.available is True
    assert vision.api_key == "sk-explicit"
    assert vision.base_url == "https://explicit.example/v1"
    assert vision.model_name == "explicit-vision"
    assert vision.timeout_seconds == 9.0


def test_ppt_service_uses_image_generation_runtime_config(monkeypatch, tmp_path) -> None:
    runtime = _runtime(
        "image_generation",
        base_url="https://dashscope.aliyuncs.com/api/v1/",
        api_key="sk-image-runtime",
        model_name="wan-runtime",
        timeout_seconds=73,
    )
    monkeypatch.setattr(settings, "generated_artifact_directory", str(tmp_path))
    monkeypatch.setattr(
        AiProviderConfigService,
        "resolve_capability",
        lambda capability, db=None: runtime,
    )

    service = PptMultimodalService(501)

    assert service.available is True
    assert service.api_key == "sk-image-runtime"
    assert service.base_url == "https://dashscope.aliyuncs.com/api/v1"
    assert service.model_name == "wan-runtime"
    assert service.timeout_seconds == 73.0


def test_agent_capability_reports_runtime_image_generation(monkeypatch) -> None:
    runtime = _runtime("image_generation", model_name="wan-runtime")
    monkeypatch.setattr(
        AiProviderConfigService,
        "resolve_capability",
        lambda capability, db=None: runtime,
    )
    monkeypatch.setattr(settings, "ppt_multimodal_max_images", 2)

    response = agent_capabilities(_=SimpleNamespace(), db=SimpleNamespace())

    assert response.data.ppt_multimodal_available is True
    assert response.data.ppt_multimodal_model == "wan-runtime"
    assert response.data.ppt_multimodal_max_images == 2

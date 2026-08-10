"""OpenAI 兼容模型的轻量输出适配。

部分自建推理服务接受 ``stream=true``，却仍返回一次性 JSON；部分微调模型
还会把 system/user/assistant 模板复述到答案里。本模块只处理协议与展示层
兼容，不改变教学提示词或业务判断。
"""

from __future__ import annotations

import re
from threading import Lock


_stream_capabilities: dict[tuple[str, str], bool] = {}
_stream_capabilities_lock = Lock()


def capability_key(base_url: str | None, model: str) -> tuple[str, str]:
    return ((base_url or "").rstrip("/"), model.strip())


def known_streaming_support(key: tuple[str, str]) -> bool | None:
    with _stream_capabilities_lock:
        return _stream_capabilities.get(key)


def remember_streaming_support(key: tuple[str, str], supported: bool) -> None:
    with _stream_capabilities_lock:
        _stream_capabilities[key] = supported


def clean_model_text(value: object) -> str:
    """移除微调/Chat Template 不一致造成的整段会话回显。"""
    text = str(value or "").strip()
    if not text:
        return ""

    # 部分推理模型会把内部思考过程放在 think/reasoning 标签中。该内容既不应
    # 展示给用户，也不能进入 Agent 执行记录。闭合标签和只有起始标签的异常
    # 响应都要处理，避免本地模型协议不完整时泄漏推理文本。
    text = re.sub(r"<(?:think|reasoning)>.*?</(?:think|reasoning)>\s*", "", text, flags=re.I | re.S)
    text = re.sub(r"^\s*<(?:think|reasoning)>.*$", "", text, flags=re.I | re.S)

    # 兼容服务把换行作为字面量 ``\\n`` 返回的情况；仅在答案明显以
    # 会话角色开头时转换，避免误伤普通正文中的转义内容。
    probe = text.lstrip().lower()
    if probe.startswith(("system\\n", "system:", "<|system|>")):
        text = text.replace("\\r\\n", "\n").replace("\\n", "\n")

    # 常见 ChatML / 简易 role 模板。取最后一个 assistant 段，因为前面
    # 可能包含训练样例中的 assistant 占位符。
    patterns = (
        r"(?:^|\n)\s*assistant\s*(?:\n|:)\s*",
        r"<\|assistant\|>\s*",
        r"<\|im_start\|>assistant\s*",
    )
    if text.lstrip().lower().startswith(("system", "<|system|>", "<|im_start|>system")):
        matches = [match for pattern in patterns for match in re.finditer(pattern, text, flags=re.I)]
        if matches:
            text = text[max(matches, key=lambda item: item.start()).end():]

    text = re.sub(r"^\s*(?:assistant|助手)\s*[:：]\s*", "", text, flags=re.I)
    return text.strip()


def chunk_text(text: str, *, size: int = 72):
    """把非流式回退结果切成前端可消费的小块。"""
    for start in range(0, len(text), size):
        yield text[start:start + size]

from __future__ import annotations

from dataclasses import dataclass
from math import exp
from threading import Lock
from typing import Iterable, Sequence

from app.core.config import settings
from app.core.logging import get_logger


logger = get_logger(__name__)


def reciprocal_rank_fusion(
    rankings: dict[str, Sequence[int]],
    *,
    weights: dict[str, float] | None = None,
    rank_constant: int | None = None,
) -> dict[int, float]:
    """融合不同量纲的排名，并对单个排名中的重复 ID 去重。"""
    constant = rank_constant or int(settings.authority_matching_rrf_rank_constant)
    scores: dict[int, float] = {}
    for name, ranking in rankings.items():
        weight = float((weights or {}).get(name, 1.0))
        seen: set[int] = set()
        rank = 0
        for raw_item_id in ranking:
            item_id = int(raw_item_id)
            if item_id in seen:
                continue
            seen.add(item_id)
            rank += 1
            scores[item_id] = scores.get(item_id, 0.0) + weight / (constant + rank)
    return scores


def normalize_rrf_scores(
    scores: dict[int, float],
    *,
    channel_weights: Iterable[float],
    rank_constant: int | None = None,
) -> dict[int, float]:
    """将 RRF 分数映射到 0..1；缺失召回通道会自然降低一致性分。"""
    constant = rank_constant or int(settings.authority_matching_rrf_rank_constant)
    maximum = sum(max(0.0, float(weight)) for weight in channel_weights) / (constant + 1)
    if maximum <= 0:
        return {item_id: 0.0 for item_id in scores}
    return {item_id: max(0.0, min(1.0, score / maximum)) for item_id, score in scores.items()}


def lexical_relevance(left: str, right: str) -> float:
    """保守的中文字符二元组余弦，用作模型不可用时的绝对相关性门槛。"""
    left_compact = "".join((left or "").lower().split())
    right_compact = "".join((right or "").lower().split())
    if len(left_compact) < 2 or len(right_compact) < 2:
        return 0.0
    left_grams = {left_compact[index:index + 2] for index in range(len(left_compact) - 1)}
    right_grams = {right_compact[index:index + 2] for index in range(len(right_compact) - 1)}
    if not left_grams or not right_grams:
        return 0.0
    shared = len(left_grams & right_grams)
    return shared / ((len(left_grams) * len(right_grams)) ** 0.5)


def calibrated_sigmoid(value: float, *, midpoint: float = 0.5, steepness: float = 7.0) -> float:
    """冷启动置信度的稳定映射；正式概率仍需用管理员标签离线校准。"""
    bounded = max(0.0, min(1.0, float(value)))
    return 1.0 / (1.0 + exp(-steepness * (bounded - midpoint)))


@dataclass(frozen=True)
class NliPrediction:
    label: str
    confidence: float
    probabilities: dict[str, float]


class OptionalOpenSourceMatcher:
    """按需加载 BGE Cross-Encoder 与中文 NLI；任何失败均返回 None。"""

    def __init__(self) -> None:
        self._load_lock = Lock()
        self._inference_lock = Lock()
        self._reranker = None
        self._reranker_failed = False
        self._nli_tokenizer = None
        self._nli_model = None
        self._nli_failed = False

    def _load_reranker(self):
        if not settings.authority_matching_reranker_enabled or self._reranker_failed:
            return None
        if self._reranker is not None:
            return self._reranker
        with self._load_lock:
            if self._reranker is not None or self._reranker_failed:
                return self._reranker
            try:
                from FlagEmbedding import FlagReranker  # type: ignore[import-not-found]

                device = str(settings.authority_matching_reranker_device).lower()
                self._reranker = FlagReranker(
                    settings.authority_matching_reranker_model,
                    use_fp16=device not in {"cpu", "mps"},
                    devices=[device],
                )
            except Exception as exc:  # pragma: no cover - 依赖和模型下载由部署环境决定
                self._reranker_failed = True
                logger.warning("BGE reranker 不可用，已降级到确定性匹配：%s", exc)
            return self._reranker

    def rerank(self, pairs: Sequence[tuple[str, str]]) -> list[float] | None:
        if not pairs:
            return []
        model = self._load_reranker()
        if model is None:
            return None
        try:
            with self._inference_lock:
                raw_scores = model.compute_score(
                    [[left, right] for left, right in pairs],
                    normalize=True,
                )
            if isinstance(raw_scores, (int, float)):
                raw_scores = [raw_scores]
            scores = [max(0.0, min(1.0, float(score))) for score in raw_scores]
            return scores if len(scores) == len(pairs) else None
        except Exception as exc:  # pragma: no cover - 依赖和设备由部署环境决定
            self._reranker_failed = True
            logger.warning("BGE reranker 推理失败，已降级到确定性匹配：%s", exc)
            return None

    def _load_nli(self):
        if not settings.authority_matching_nli_enabled or self._nli_failed:
            return None, None
        if self._nli_model is not None and self._nli_tokenizer is not None:
            return self._nli_tokenizer, self._nli_model
        with self._load_lock:
            if self._nli_model is not None or self._nli_failed:
                return self._nli_tokenizer, self._nli_model
            try:
                from transformers import AutoModelForSequenceClassification, AutoTokenizer  # type: ignore[import-not-found]

                self._nli_tokenizer = AutoTokenizer.from_pretrained(settings.authority_matching_nli_model)
                self._nli_model = AutoModelForSequenceClassification.from_pretrained(
                    settings.authority_matching_nli_model
                )
                self._nli_model.to(str(settings.authority_matching_nli_device))
                self._nli_model.eval()
            except Exception as exc:  # pragma: no cover - 依赖和模型下载由部署环境决定
                self._nli_failed = True
                logger.warning("中文 NLI 模型不可用，已降级到规则分类：%s", exc)
            return self._nli_tokenizer, self._nli_model

    def nli(self, pairs: Sequence[tuple[str, str]]) -> list[NliPrediction] | None:
        if not pairs:
            return []
        tokenizer, model = self._load_nli()
        if tokenizer is None or model is None:
            return None
        try:
            import torch  # type: ignore[import-not-found]

            encoded = tokenizer(
                [left for left, _ in pairs],
                [right for _, right in pairs],
                padding=True,
                truncation=True,
                max_length=512,
                return_tensors="pt",
            )
            device = str(settings.authority_matching_nli_device)
            encoded = {key: value.to(device) for key, value in encoded.items()}
            with self._inference_lock, torch.no_grad():
                probabilities = torch.softmax(model(**encoded).logits, dim=-1).cpu().tolist()
            id_to_label = {
                int(key): str(value).lower()
                for key, value in dict(getattr(model.config, "id2label", {})).items()
            }
            output: list[NliPrediction] = []
            for row in probabilities:
                mapped = {id_to_label.get(index, f"label_{index}"): float(score) for index, score in enumerate(row)}
                label, confidence = max(mapped.items(), key=lambda item: item[1])
                output.append(NliPrediction(label=label, confidence=confidence, probabilities=mapped))
            return output
        except Exception as exc:  # pragma: no cover - 依赖和设备由部署环境决定
            self._nli_failed = True
            logger.warning("中文 NLI 推理失败，已降级到规则分类：%s", exc)
            return None


open_source_matcher = OptionalOpenSourceMatcher()

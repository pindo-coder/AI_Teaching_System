from __future__ import annotations

import logging
from pathlib import Path
import re
from threading import BoundedSemaphore
import time
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from sqlalchemy.orm import Session

from app.core.config import BACKEND_DIR, settings
from app.services.ai_operation_service import AiProviderConfigService


logger = logging.getLogger(__name__)

MAX_GENERATED_IMAGE_BYTES = 20 * 1024 * 1024
IMAGE_DOWNLOAD_CHUNK_BYTES = 64 * 1024
# Small deployments must not run multiple 2K image jobs in the same process.
# Busy requests fall back immediately instead of occupying another worker.
_PPT_IMAGE_CALL_GATE = BoundedSemaphore(1)


class PptMultimodalService:
    """调用百炼图像模型，为少量关键页面生成可本地持久化的辅助视觉。"""

    def __init__(
        self,
        run_id: int,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
        enabled: bool | None = None,
        db: Session | None = None,
    ) -> None:
        root = Path(settings.generated_artifact_directory)
        if not root.is_absolute():
            root = (BACKEND_DIR / root).resolve()
        self.root = root
        self.asset_dir = root / str(run_id) / "ppt_visuals"
        self.asset_dir.mkdir(parents=True, exist_ok=True)

        runtime = AiProviderConfigService.resolve_capability("image_generation", db)
        if runtime.source == "database":
            selected_key = api_key if api_key is not None else runtime.api_key
            selected_base_url = base_url if base_url is not None else runtime.base_url
            selected_model = model if model is not None else runtime.model_name
            selected_timeout = (
                timeout_seconds if timeout_seconds is not None else runtime.timeout_seconds
            )
            selected_enabled = enabled if enabled is not None else runtime.enabled
        else:
            selected_key = api_key if api_key is not None else settings.ppt_multimodal_api_key
            selected_base_url = (
                base_url if base_url is not None else settings.ppt_multimodal_base_url
            )
            selected_model = model if model is not None else settings.ppt_multimodal_model
            selected_timeout = (
                timeout_seconds
                if timeout_seconds is not None
                else settings.ppt_multimodal_timeout_seconds
            )
            selected_enabled = (
                enabled if enabled is not None else settings.ppt_multimodal_enabled
            )
        self.api_key = str(selected_key or "").strip() or None
        self.base_url = str(selected_base_url or "").strip().rstrip("/")
        self.model_name = str(selected_model or "").strip()
        try:
            self.timeout_seconds = float(selected_timeout)
        except (TypeError, ValueError):
            self.timeout_seconds = 180.0
        self.enabled = bool(selected_enabled)

    @property
    def available(self) -> bool:
        return bool(
            self.enabled
            and self.api_key
            and self.base_url
            and self.model_name
        )

    @staticmethod
    def _safe_prompt(slide: dict[str, Any], design: dict[str, Any]) -> str:
        raw = str(slide.get("visual_prompt") or "").strip()
        if not raw:
            raw = (
                f"围绕“{slide.get('title') or ''}”和“{slide.get('takeaway') or ''}”创作课堂课件配图，"
                f"视觉主题为“{design.get('name') or '高校思政课'}”。"
            )
        raw = re.sub(r"\s+", " ", raw)[:1200]
        return (
            f"{raw} 横向16:9构图，画面清晰、庄重、自然，适合高校课堂投影。"
            "不要出现文字、标题、标语、水印、二维码、国旗、国徽、公章、政策文件原件；"
            "不要生成真实政治人物肖像，不伪造新闻摄影或历史档案。"
            "优先使用象征性场景、自然景观、城市发展、青年学习或抽象文化意象，"
            "主体位于画面右侧或中央偏右，为左侧课件文字保留干净空间。"
        )

    @staticmethod
    def _extract_image_url(payload: dict[str, Any]) -> str:
        for choice in ((payload.get("output") or {}).get("choices") or []):
            for item in ((choice.get("message") or {}).get("content") or []):
                if not isinstance(item, dict):
                    continue
                url = item.get("image") or item.get("url")
                if url:
                    return str(url)
        raise RuntimeError("百炼图像模型未返回图片地址")

    @staticmethod
    def _overlap_area(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> float:
        lx, ly, lw, lh = left
        rx, ry, rw, rh = right
        return max(0.0, min(lx + lw, rx + rw) - max(lx, rx)) * max(
            0.0, min(ly + lh, ry + rh) - max(ly, ry)
        )

    @classmethod
    def _append_auto_image_slot(cls, slide: dict[str, Any]) -> bool:
        """为没有输出 image 占位的页面补一个不遮挡正文的视觉槽位。

        视觉 Agent 偶尔会因为 JSON 过长而漏掉 image 元素。此时不应直接放弃多模态
        生成，而是从页面剩余空间中选一个右侧/底部安全区域，保证图片最终能进入 PPT。
        """
        canvas = slide.get("canvas")
        if not isinstance(canvas, list):
            return False
        if any(item.get("type") == "image" for item in canvas if isinstance(item, dict)):
            return True
        text_boxes = [
            (
                float(item.get("x") or 0),
                float(item.get("y") or 0),
                float(item.get("w") or 0),
                float(item.get("h") or 0),
            )
            for item in canvas
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        # 优先右侧竖图，其次底部横图；每个候选都留出 4% 的视觉边距。
        candidates = [
            (62.0, 22.0, 32.0, 54.0),
            (58.0, 58.0, 36.0, 30.0),
            (6.0, 58.0, 38.0, 30.0),
        ]
        for x, y, w, h in candidates:
            box = (x, y, w, h)
            if all(cls._overlap_area(box, text_box) <= 12.0 for text_box in text_boxes):
                canvas.append(
                    {
                        "type": "image",
                        "source": "visual_asset",
                        "style": "body",
                        "x": x,
                        "y": y,
                        "w": w,
                        "h": h,
                        "color": "text",
                        "fill": "",
                        "shape": "roundRect",
                        "align": "center",
                        "bold": False,
                        "background": str(slide.get("canvas_background") or "background"),
                    }
                )
                return True
        return False

    @staticmethod
    def _candidate_score(slide: dict[str, Any], index: int, total: int) -> int:
        layout = str(slide.get("layout") or "content")
        if index == 0 or index == total - 1 or layout in {"title", "summary"}:
            return -100
        score = {
            "concept": 8,
            "process": 8,
            "timeline": 8,
            "comparison": 7,
            "discussion": 6,
            "content": 5,
            "question": 4,
            "agenda": 2,
        }.get(layout, 3)
        if slide.get("steps"):
            score += 2
        if slide.get("timeline"):
            score += 2
        if slide.get("left") or slide.get("right"):
            score += 1
        if slide.get("bullets"):
            score += 1
        return score

    @classmethod
    def _select_candidates(cls, slides: list[dict[str, Any]]) -> list[tuple[int, dict[str, Any]]]:
        """选择最适合插图的 1—3 页，避免封面、总结页被强行配图。"""
        limit = max(0, settings.ppt_multimodal_max_images)
        if limit == 0:
            return []
        explicit = [
            (index, slide)
            for index, slide in enumerate(slides)
            if any(
                isinstance(item, dict) and item.get("type") == "image"
                for item in (slide.get("canvas") or [])
            )
        ]
        explicit_indexes = {index for index, _ in explicit}
        remaining = [
            (cls._candidate_score(slide, index, len(slides)), index, slide)
            for index, slide in enumerate(slides)
            if index not in explicit_indexes
        ]
        remaining.sort(key=lambda item: (-item[0], item[1]))
        ordered = explicit + [(index, slide) for score, index, slide in remaining if score > 0]
        return ordered[:limit]

    @staticmethod
    def _validate_result_url(url: str) -> None:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not (
            hostname.endswith(".aliyuncs.com") or hostname.endswith(".alicdn.com")
        ):
            raise RuntimeError("百炼返回了不受信任的图片地址")

    @staticmethod
    def _remove_image_slots(slides: list[dict[str, Any]]) -> None:
        """Remove unresolved image placeholders when falling back to vector shapes."""

        for slide in slides:
            canvas = slide.get("canvas")
            if isinstance(canvas, list):
                slide["canvas"] = [
                    item
                    for item in canvas
                    if not isinstance(item, dict) or item.get("type") != "image"
                ]
            slide.pop("visual_asset", None)

    def _generate_one(self, slide: dict[str, Any], design: dict[str, Any], index: int) -> dict[str, Any]:
        endpoint = f"{self.base_url}/services/aigc/multimodal-generation/generation"
        request_body = {
            "model": self.model_name,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [{"text": self._safe_prompt(slide, design)}],
                    }
                ]
            },
            "parameters": {
                "size": "2K",
                "n": 1,
                "watermark": False,
                "thinking_mode": True,
            },
        }
        timeout = httpx.Timeout(self.timeout_seconds)
        temporary_path: Path | None = None
        try:
            with httpx.Client(timeout=timeout, follow_redirects=False) as client:
                response = None
                for attempt in range(2):
                    try:
                        response = client.post(
                            endpoint,
                            headers={
                                "Authorization": f"Bearer {self.api_key}",
                                "Content-Type": "application/json",
                            },
                            json=request_body,
                        )
                    except httpx.RequestError as exc:
                        if attempt == 0:
                            time.sleep(1)
                            continue
                        raise RuntimeError(f"百炼图像服务连接失败：{exc}") from exc
                    if response.status_code not in {429, 500, 502, 503, 504} or attempt == 1:
                        break
                    time.sleep(1.5)
                if response is None or response.status_code >= 400:
                    detail = response.text[:500] if response is not None else "无响应"
                    code = response.status_code if response is not None else "连接失败"
                    raise RuntimeError(f"百炼图像生成失败（{code}）：{detail}")
                image_url = self._extract_image_url(response.json())
                self._validate_result_url(image_url)

                with client.stream("GET", image_url) as image_response:
                    if image_response.status_code >= 400:
                        raise RuntimeError(
                            f"百炼生成图片下载失败（{image_response.status_code}）"
                        )
                    content_type = image_response.headers.get("content-type", "").lower()
                    media_type = content_type.split(";", 1)[0].strip()
                    if not media_type.startswith("image/"):
                        raise RuntimeError("百炼生成结果不是有效图片")
                    content_length = image_response.headers.get("content-length")
                    if content_length:
                        try:
                            declared_bytes = int(content_length)
                        except (TypeError, ValueError):
                            declared_bytes = -1
                        if declared_bytes > MAX_GENERATED_IMAGE_BYTES:
                            raise RuntimeError("百炼生成图片超过 20MB")

                    suffix = (
                        ".jpg"
                        if "jpeg" in media_type
                        else ".webp"
                        if "webp" in media_type
                        else ".png"
                    )
                    path = self.asset_dir / f"slide-{index + 1}{suffix}"
                    temporary_path = path.with_name(
                        f".{path.name}.{uuid4().hex}.part"
                    )
                    downloaded_bytes = 0
                    with temporary_path.open("wb") as output:
                        for chunk in image_response.iter_bytes(
                            chunk_size=IMAGE_DOWNLOAD_CHUNK_BYTES
                        ):
                            if not chunk:
                                continue
                            downloaded_bytes += len(chunk)
                            if downloaded_bytes > MAX_GENERATED_IMAGE_BYTES:
                                raise RuntimeError("百炼生成图片超过 20MB")
                            output.write(chunk)
                    if downloaded_bytes == 0:
                        raise RuntimeError("百炼生成图片为空")
                    temporary_path.replace(path)
                    temporary_path = None

            return {
                "storage_path": str(path.relative_to(self.root)),
                "file_name": path.name,
                "media_type": media_type,
                "model": self.model_name,
                "prompt": self._safe_prompt(slide, design),
            }
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def enhance(self, ppt_data: dict[str, Any]) -> dict[str, Any]:
        slides = ppt_data.get("slides") or []
        design = ppt_data.get("design") or {}
        if not self.available:
            self._remove_image_slots(slides)
            ppt_data["multimodal"] = {
                "status": "unavailable",
                "generated_count": 0,
                "message": "未配置可用的阿里云 PPT 多模态服务，已保留纯图形课件。",
            }
            return ppt_data
        candidates = self._select_candidates(slides)
        if candidates and not _PPT_IMAGE_CALL_GATE.acquire(blocking=False):
            self._remove_image_slots(slides)
            ppt_data["multimodal"] = {
                "status": "fallback",
                "generated_count": 0,
                "requested_count": len(candidates),
                "selected_slides": [index + 1 for index, _ in candidates],
                "model": self.model_name,
                "message": "配图服务正忙，已立即回退为纯图形课件。",
                "errors": ["配图服务正忙"],
            }
            return ppt_data

        gate_acquired = bool(candidates)
        generated = 0
        errors: list[str] = []
        try:
            # 设计 Agent 未输出图片槽位时自动补槽；失败的页面保留原有文字构图。
            candidates = [
                (index, slide)
                for index, slide in candidates
                if self._append_auto_image_slot(slide)
            ]
            for index, slide in candidates:
                try:
                    slide["visual_asset"] = self._generate_one(slide, design, index)
                    generated += 1
                except Exception as exc:
                    logger.warning("ppt_multimodal_fallback slide=%s reason=%s", index + 1, exc)
                    errors.append(f"第 {index + 1} 页：{exc}")
                    self._remove_image_slots([slide])
        finally:
            if gate_acquired:
                _PPT_IMAGE_CALL_GATE.release()
        ppt_data["multimodal"] = {
            "status": "completed" if generated else "fallback",
            "generated_count": generated,
            "requested_count": len(candidates),
            "selected_slides": [index + 1 for index, _ in candidates],
            "model": self.model_name,
            "message": "辅助插图已保存到本地课件资源目录。" if generated else "多模态生成未成功，已回退为纯图形课件。",
            "errors": errors[:3],
        }
        return ppt_data

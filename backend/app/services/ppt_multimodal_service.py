from __future__ import annotations

import logging
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import BACKEND_DIR, settings


logger = logging.getLogger(__name__)


class PptMultimodalService:
    """调用百炼图像模型，为少量关键页面生成可本地持久化的辅助视觉。"""

    def __init__(self, run_id: int) -> None:
        root = Path(settings.generated_artifact_directory)
        if not root.is_absolute():
            root = (BACKEND_DIR / root).resolve()
        self.root = root
        self.asset_dir = root / str(run_id) / "ppt_visuals"
        self.asset_dir.mkdir(parents=True, exist_ok=True)

    @property
    def available(self) -> bool:
        return bool(
            settings.ppt_multimodal_enabled
            and settings.ppt_multimodal_api_key
            and settings.ppt_multimodal_model
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
                url = item.get("image")
                if url:
                    return str(url)
        raise RuntimeError("百炼图像模型未返回图片地址")

    @staticmethod
    def _validate_result_url(url: str) -> None:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not (
            hostname.endswith(".aliyuncs.com") or hostname.endswith(".alicdn.com")
        ):
            raise RuntimeError("百炼返回了不受信任的图片地址")

    def _generate_one(self, slide: dict[str, Any], design: dict[str, Any], index: int) -> dict[str, Any]:
        base_url = settings.ppt_multimodal_base_url.rstrip("/")
        endpoint = f"{base_url}/services/aigc/multimodal-generation/generation"
        request_body = {
            "model": settings.ppt_multimodal_model,
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
        timeout = httpx.Timeout(settings.ppt_multimodal_timeout_seconds)
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            response = client.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {settings.ppt_multimodal_api_key}",
                    "Content-Type": "application/json",
                },
                json=request_body,
            )
            if response.status_code >= 400:
                detail = response.text[:500]
                raise RuntimeError(f"百炼图像生成失败（{response.status_code}）：{detail}")
            image_url = self._extract_image_url(response.json())
            self._validate_result_url(image_url)
            image_response = client.get(image_url)
            if image_response.status_code >= 400:
                raise RuntimeError(f"百炼生成图片下载失败（{image_response.status_code}）")
            content_type = image_response.headers.get("content-type", "").lower()
            if "image/" not in content_type:
                raise RuntimeError("百炼生成结果不是有效图片")
            content = image_response.content
        if not content or len(content) > 20 * 1024 * 1024:
            raise RuntimeError("百炼生成图片为空或超过 20MB")
        suffix = ".jpg" if "jpeg" in content_type else ".webp" if "webp" in content_type else ".png"
        path = self.asset_dir / f"slide-{index + 1}{suffix}"
        path.write_bytes(content)
        return {
            "storage_path": str(path.relative_to(self.root)),
            "file_name": path.name,
            "media_type": content_type.split(";")[0],
            "model": settings.ppt_multimodal_model,
            "prompt": self._safe_prompt(slide, design),
        }

    def enhance(self, ppt_data: dict[str, Any]) -> dict[str, Any]:
        slides = ppt_data.get("slides") or []
        design = ppt_data.get("design") or {}
        if not self.available:
            ppt_data["multimodal"] = {
                "status": "unavailable",
                "generated_count": 0,
                "message": "未配置可用的阿里云 PPT 多模态服务，已保留纯图形课件。",
            }
            return ppt_data
        candidates = [
            (index, slide)
            for index, slide in enumerate(slides)
            if any(item.get("type") == "image" for item in (slide.get("canvas") or []))
        ][: max(0, settings.ppt_multimodal_max_images)]
        generated = 0
        errors: list[str] = []
        for index, slide in candidates:
            try:
                slide["visual_asset"] = self._generate_one(slide, design, index)
                generated += 1
            except Exception as exc:
                logger.warning("ppt_multimodal_fallback slide=%s reason=%s", index + 1, exc)
                errors.append(f"第 {index + 1} 页：{exc}")
                slide["canvas"] = [
                    item for item in (slide.get("canvas") or []) if item.get("type") != "image"
                ]
        ppt_data["multimodal"] = {
            "status": "completed" if generated else "fallback",
            "generated_count": generated,
            "requested_count": len(candidates),
            "model": settings.ppt_multimodal_model,
            "message": "辅助插图已保存到本地课件资源目录。" if generated else "多模态生成未成功，已回退为纯图形课件。",
            "errors": errors[:3],
        }
        return ppt_data

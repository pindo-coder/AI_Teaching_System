from __future__ import annotations

from datetime import datetime
import json
import logging
from pathlib import Path
import re
from typing import Any

from fastapi import HTTPException, status
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from sqlalchemy import Engine, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.prompts import (
    LESSON_ARTIFACT_SYSTEM_PROMPT,
    LESSON_ARTIFACT_USER_PROMPT,
    LESSON_PPT_DESIGN_SYSTEM_PROMPT,
    LESSON_PPT_DESIGN_USER_PROMPT,
    LESSON_PPT_REVIEW_SYSTEM_PROMPT,
    LESSON_PPT_REVIEW_USER_PROMPT,
    LESSON_PPT_REVISION_SYSTEM_PROMPT,
    LESSON_PPT_REVISION_USER_PROMPT,
    LESSON_PREP_SYSTEM_PROMPT,
    LESSON_PREP_USER_PROMPT,
)
from app.services.llm_compat import clean_model_text
from app.models.agent_run import AgentRun, AgentStep
from app.models.chapter import Chapter
from app.models.course import Course
from app.models.teaching_class import TeachingClass, TeachingClassTeacher
from app.models.user import User
from app.schemas.agent import (
    AgentArtifactRequest,
    AgentRunCreate,
    AgentRunData,
    AgentStepData,
    PptSlideRevisionRequest,
)
from app.schemas.ai import AiAssistData, AiAssistRequest
from app.services.ai_service import AiService
from app.services.presentation_artifact_service import PresentationArtifactService
from app.services.presentation_template_service import PresentationTemplateService
from app.services.ppt_multimodal_service import PptMultimodalService


logger = logging.getLogger(__name__)

STEP_DEFINITIONS = [
    ("set_context", "设置任务"),
    ("build_evidence", "构建证据"),
    ("generate_outline", "生成课纲"),
    ("generate_artifacts", "生成成果"),
    ("preview_publish", "预览发布"),
]


def _now() -> datetime:
    return datetime.now()


def _clean_ppt_visible_text(value: Any) -> Any:
    """PPT 面向学生的可见文本不展示系统引用编号。"""
    if isinstance(value, str):
        cleaned = re.sub(r"\[资料\d+\]", "", value)
        cleaned = re.sub(r"^资料依据[：:]\s*.*$", "", cleaned)
        return re.sub(r"\s{2,}", " ", cleaned).strip(" ；;、")
    if isinstance(value, list):
        return [item for item in (_clean_ppt_visible_text(item) for item in value) if item]
    return value


PPT_LAYOUTS = {
    "title",
    "agenda",
    "question",
    "content",
    "concept",
    "process",
    "comparison",
    "timeline",
    "discussion",
    "summary",
}

PPT_COLOR_ROLES = {
    "background",
    "surface",
    "primary",
    "secondary",
    "accent",
    "text",
    "muted",
    "inverse",
}
PPT_ELEMENT_TYPES = {"text", "shape", "line", "image"}
PPT_TEXT_STYLES = {"hero", "title", "subtitle", "body", "label", "number", "quote"}
PPT_SHAPES = {"rect", "roundRect", "ellipse", "arc"}
PPT_ALIGNMENTS = {"left", "center", "right"}
PPT_BACKGROUNDS = {"background", "surface", "primary", "secondary"}
PPT_SOURCE_PATTERN = re.compile(
    r"^(?:title|takeaway|keyword|page_number|bullet:\d+|"
    r"(?:left|right)\.(?:title|point:\d+)|"
    r"step:\d+\.(?:title|description)|timeline:\d+\.(?:label|title))$"
)
PPT_DEFAULT_PALETTE = {
    "background": "F7F4EE",
    "surface": "FFFFFF",
    "primary": "9E2335",
    "secondary": "2459B8",
    "accent": "D3A23A",
    "text": "172033",
    "muted": "758198",
    "inverse": "FFFFFF",
}


def _fit_ppt_phrase(value: Any, limit: int) -> str:
    text = str(_clean_ppt_visible_text(value or ""))
    if len(text) <= limit:
        return text
    candidate = text[:limit]
    for separator in ("。", "；", "，", "、"):
        position = candidate.rfind(separator)
        if position >= int(limit * 0.6):
            return candidate[: position + 1]
    return f"{candidate.rstrip('，；、 ')}…"


def _split_ppt_point(value: Any, limit: int = 48) -> list[str]:
    text = str(_clean_ppt_visible_text(value or "")).strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    parts = [part.strip() for part in re.split(r"(?<=[。；！？])", text) if part.strip()]
    if len(parts) > 1 and all(len(part) <= limit + 12 for part in parts):
        return parts
    return [
        text[index : index + limit].strip()
        for index in range(0, len(text), limit)
        if text[index : index + limit].strip()
    ]


def _normalize_ppt_items(values: Any, *, limit: int = 48, maximum: int = 8) -> list[str]:
    if not isinstance(values, list):
        return []
    normalized: list[str] = []
    for value in values:
        normalized.extend(_split_ppt_point(value, limit))
    return normalized[:maximum]


def _sanitize_ppt_visible_content(ppt_data: dict[str, Any]) -> dict[str, Any]:
    cleaned = json.loads(json.dumps(ppt_data, ensure_ascii=False))
    cleaned["title"] = _fit_ppt_phrase(cleaned.get("title"), 32)
    cleaned["subtitle"] = _fit_ppt_phrase(cleaned.get("subtitle"), 42)
    normalized_slides: list[dict[str, Any]] = []
    for index, raw_slide in enumerate(cleaned.get("slides") or []):
        if not isinstance(raw_slide, dict):
            continue
        slide = raw_slide
        layout = str(slide.get("layout") or "content").lower()
        slide["layout"] = layout if layout in PPT_LAYOUTS else "content"
        if index == 0:
            slide["layout"] = "title"
        slide["title"] = _fit_ppt_phrase(slide.get("title"), 30)
        slide["takeaway"] = _fit_ppt_phrase(slide.get("takeaway"), 62)
        slide["keyword"] = _fit_ppt_phrase(slide.get("keyword"), 16)
        slide["bullets"] = _normalize_ppt_items(slide.get("bullets"), maximum=10)
        for side in ("left", "right"):
            block = slide.get(side)
            if not isinstance(block, dict):
                block = {}
            block["title"] = _fit_ppt_phrase(block.get("title"), 16)
            block["points"] = _normalize_ppt_items(block.get("points"), maximum=4)
            slide[side] = block
        steps: list[dict[str, str]] = []
        for item in (slide.get("steps") or [])[:5]:
            if not isinstance(item, dict):
                continue
            steps.append(
                {
                    "title": _fit_ppt_phrase(item.get("title"), 12),
                    "description": _fit_ppt_phrase(item.get("description"), 34),
                }
            )
        slide["steps"] = steps
        timeline: list[dict[str, str]] = []
        for item in (slide.get("timeline") or [])[:5]:
            if not isinstance(item, dict):
                continue
            timeline.append(
                {
                    "label": _fit_ppt_phrase(item.get("label"), 10),
                    "title": _fit_ppt_phrase(item.get("title"), 28),
                }
            )
        slide["timeline"] = timeline
        bullet_groups = [
            slide["bullets"][offset : offset + 5]
            for offset in range(0, len(slide["bullets"]), 5)
        ] or [[]]
        slide["bullets"] = bullet_groups[0]
        normalized_slides.append(slide)
        if len(bullet_groups) > 1 and slide["layout"] in {"content", "agenda"}:
            for continuation_index, group in enumerate(bullet_groups[1:], start=2):
                continuation = json.loads(json.dumps(slide, ensure_ascii=False))
                continuation["layout"] = "content"
                continuation["title"] = _fit_ppt_phrase(
                    f"{slide['title']}（续{continuation_index - 1}）",
                    30,
                )
                continuation["bullets"] = group
                normalized_slides.append(continuation)
    cleaned["slides"] = normalized_slides
    return cleaned


def _enforce_ppt_slide_count(
    ppt_data: dict[str, Any],
    target: int | None,
    outline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """模型轻微偏离页数时做安全收敛，保证教师设置的精确页数可兑现。"""
    if target is None or not 6 <= target <= 30:
        return ppt_data
    slides = list(ppt_data.get("slides") or [])
    if len(slides) > target:
        slides = slides[: target - 1] + [slides[-1]]
    fallback_points = (
        list((outline or {}).get("key_points") or [])
        + list((outline or {}).get("difficult_points") or [])
        + list((outline or {}).get("discussion_questions") or [])
    )
    while slides and len(slides) < target:
        offset = len(slides)
        point = fallback_points[offset % len(fallback_points)] if fallback_points else "联系教材原文梳理本专题核心观点"
        supplemental = {
            "layout": "content",
            "title": _fit_ppt_phrase(f"深化理解：{point}", 30),
            "takeaway": _fit_ppt_phrase(point, 62),
            "bullets": [_fit_ppt_phrase(point, 45)],
            "keyword": "",
            "left": {"title": "", "points": []},
            "right": {"title": "", "points": []},
            "steps": [],
            "timeline": [],
            "speaker_notes": "结合已确认课纲与教材证据补充讲解。",
            "evidence_refs": list(slides[-1].get("evidence_refs") or []),
        }
        slides.insert(max(1, len(slides) - 1), supplemental)
    ppt_data["slides"] = slides
    return ppt_data


def _sanitize_hex_color(value: Any, fallback: str) -> str:
    candidate = str(value or "").strip().lstrip("#").upper()
    return candidate if re.fullmatch(r"[0-9A-F]{6}", candidate) else fallback


def _bounded_number(value: Any, minimum: float, maximum: float, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return round(min(maximum, max(minimum, number)), 2)


def _sanitize_ppt_design(
    design_result: dict[str, Any],
    slide_count: int,
) -> tuple[dict[str, Any], dict[int, list[dict[str, Any]]]]:
    raw_design = design_result.get("design")
    if not isinstance(raw_design, dict):
        raw_design = {}
    raw_palette = raw_design.get("palette")
    if not isinstance(raw_palette, dict):
        raw_palette = {}
    palette = {
        role: _sanitize_hex_color(raw_palette.get(role), fallback)
        for role, fallback in PPT_DEFAULT_PALETTE.items()
    }
    design = {
        "name": _fit_ppt_phrase(raw_design.get("name") or "专题视觉叙事", 24),
        "concept": _fit_ppt_phrase(raw_design.get("concept"), 90),
        "mood": _fit_ppt_phrase(raw_design.get("mood"), 36),
        "fonts": {
            "heading": _fit_ppt_phrase(
                (raw_design.get("fonts") or {}).get("heading")
                if isinstance(raw_design.get("fonts"), dict)
                else "Microsoft YaHei",
                80,
            )
            or "Microsoft YaHei",
            "body": _fit_ppt_phrase(
                (raw_design.get("fonts") or {}).get("body")
                if isinstance(raw_design.get("fonts"), dict)
                else "Microsoft YaHei",
                80,
            )
            or "Microsoft YaHei",
        },
        "palette": palette,
        "agent": "ppt-visual-designer-v1",
        "visual_prompts": {},
    }
    pages: dict[int, list[dict[str, Any]]] = {}
    for raw_page in design_result.get("pages") or []:
        if not isinstance(raw_page, dict):
            continue
        try:
            index = int(raw_page.get("index"))
        except (TypeError, ValueError):
            continue
        if not 0 <= index < slide_count or index in pages:
            continue
        background = str(raw_page.get("background") or "background")
        if background not in PPT_BACKGROUNDS:
            background = "background"
        elements: list[dict[str, Any]] = []
        image_count = 0
        for raw_element in (raw_page.get("elements") or [])[:12]:
            if not isinstance(raw_element, dict):
                continue
            element_type = str(raw_element.get("type") or "text")
            if element_type not in PPT_ELEMENT_TYPES:
                continue
            source = str(raw_element.get("source") or "")
            if element_type == "text" and not PPT_SOURCE_PATTERN.fullmatch(source):
                continue
            if element_type == "image":
                if source != "visual_asset" or image_count >= 1:
                    continue
                image_count += 1
            x = _bounded_number(raw_element.get("x"), 0, 96, 8)
            y = _bounded_number(raw_element.get("y"), 6, 91, 12)
            w = _bounded_number(raw_element.get("w"), 1, 100 - x, 30)
            h = _bounded_number(raw_element.get("h"), 1, 94 - y, 10)
            style = str(raw_element.get("style") or "body")
            color = str(raw_element.get("color") or "text")
            fill = str(raw_element.get("fill") or "")
            shape = str(raw_element.get("shape") or "rect")
            align = str(raw_element.get("align") or "left")
            elements.append(
                {
                    "type": element_type,
                    "source": source,
                    "style": style if style in PPT_TEXT_STYLES else "body",
                    "x": x,
                    "y": y,
                    "w": w,
                    "h": h,
                    "color": color if color in PPT_COLOR_ROLES else "text",
                    "fill": fill if fill in PPT_COLOR_ROLES else "",
                    "shape": shape if shape in PPT_SHAPES else "rect",
                    "align": align if align in PPT_ALIGNMENTS else "left",
                    "bold": bool(raw_element.get("bold", False)),
                    "background": background,
                }
            )
        if len(elements) >= 3 and any(item["source"] == "title" for item in elements):
            pages[index] = elements
            if image_count:
                prompt = _fit_ppt_phrase(raw_page.get("visual_prompt"), 1200)
                if prompt:
                    design["visual_prompts"][str(index)] = prompt
    return design, pages


def _resolve_ppt_canvas_source(
    slide: dict[str, Any],
    source: str,
    slide_index: int = 0,
) -> str:
    """Resolve the same source vocabulary used by the Node PPT renderer."""
    if source == "title":
        return str(slide.get("title") or "").strip()
    if source == "takeaway":
        return str(slide.get("takeaway") or "").strip()
    if source == "keyword":
        return str(slide.get("keyword") or "").strip()
    if source == "page_number":
        return str(slide_index + 1)
    if source in {"left.title", "right.title"}:
        side, _ = source.split(".", 1)
        value = slide.get(side)
        return str(value.get("title") or "").strip() if isinstance(value, dict) else ""

    match = re.fullmatch(r"bullet:(\d+)", source)
    if match:
        values = slide.get("bullets") or []
        index = int(match.group(1))
        return str(values[index]).strip() if index < len(values) else ""

    match = re.fullmatch(r"(left|right)\.point:(\d+)", source)
    if match:
        value = slide.get(match.group(1))
        points = value.get("points") or [] if isinstance(value, dict) else []
        index = int(match.group(2))
        return str(points[index]).strip() if index < len(points) else ""

    match = re.fullmatch(r"step:(\d+)\.(title|description)", source)
    if match:
        values = slide.get("steps") or []
        index = int(match.group(1))
        value = values[index] if index < len(values) else {}
        return (
            str(value.get(match.group(2)) or "").strip()
            if isinstance(value, dict)
            else ""
        )

    match = re.fullmatch(r"timeline:(\d+)\.(label|title)", source)
    if match:
        values = slide.get("timeline") or []
        index = int(match.group(1))
        value = values[index] if index < len(values) else {}
        return (
            str(value.get(match.group(2)) or "").strip()
            if isinstance(value, dict)
            else ""
        )
    return ""


def _prepare_ppt_canvas_for_slide(
    slide: dict[str, Any],
    canvas: list[dict[str, Any]],
    slide_index: int,
) -> tuple[list[dict[str, Any]] | None, dict[str, Any]]:
    """Drop empty text slots and reject canvases that would render as blank pages."""
    prepared: list[dict[str, Any]] = []
    visible_sources: list[str] = []
    visible_characters = 0
    for item in canvas:
        if item.get("type") != "text":
            prepared.append(item)
            continue
        source = str(item.get("source") or "")
        resolved = _resolve_ppt_canvas_source(slide, source, slide_index)
        if not resolved:
            continue
        prepared.append(item)
        if source != "page_number":
            visible_sources.append(source)
            visible_characters += len(resolved)

    body_sources = [
        source for source in visible_sources if source not in {"title", "page_number"}
    ]
    valid = (
        "title" in visible_sources
        and bool(body_sources)
        and visible_characters >= 16
    )
    diagnostics = {
        "visible_sources": visible_sources,
        "body_source_count": len(body_sources),
        "visible_characters": visible_characters,
        "recovered_with_safe_layout": not valid,
    }
    return (prepared if valid else None), diagnostics


def _attach_mock_ppt_design(ppt_data: dict[str, Any]) -> dict[str, Any]:
    """测试模式也走自由画布渲染，避免只验证安全回退路径。"""
    ppt_data["design"] = {
        "name": "理论之路",
        "concept": "以方向线、章节序号和结论大字表现理论从历史走向实践的教学路径。",
        "mood": "庄重、开放、有阅读节奏",
        "fonts": {"heading": "Microsoft YaHei", "body": "Microsoft YaHei"},
        "palette": {
            "background": "F5F1E8",
            "surface": "FFFFFF",
            "primary": "8F2638",
            "secondary": "1E4E83",
            "accent": "C99732",
            "text": "172033",
            "muted": "667085",
            "inverse": "FFFFFF",
        },
        "agent": "mock-visual-designer",
        "status": "personalized",
        "designed_pages": len(ppt_data.get("slides") or []),
    }
    for index, slide in enumerate(ppt_data.get("slides") or []):
        dark = index in {0, 2, 8}
        background = "primary" if index == 0 else "secondary" if dark else "background"
        foreground = "inverse" if dark else "text"
        title_x = 8 if index % 3 != 1 else 31
        title_w = 72 if index % 3 != 1 else 61
        slide["canvas_background"] = background
        slide["canvas"] = [
            {
                "type": "shape",
                "source": "",
                "style": "body",
                "x": 5,
                "y": 8,
                "w": 2,
                "h": 78,
                "color": "accent",
                "fill": "accent",
                "shape": "rect",
                "align": "left",
                "bold": False,
            },
            {
                "type": "text",
                "source": "page_number",
                "style": "number",
                "x": 84 if index % 3 != 1 else 8,
                "y": 9,
                "w": 9,
                "h": 10,
                "color": "accent",
                "fill": "",
                "shape": "rect",
                "align": "right" if index % 3 != 1 else "left",
                "bold": True,
            },
            {
                "type": "text",
                "source": "title",
                "style": "hero" if index == 0 else "title",
                "x": title_x,
                "y": 22 if index == 0 else 17,
                "w": title_w,
                "h": 24 if index == 0 else 18,
                "color": foreground,
                "fill": "",
                "shape": "rect",
                "align": "left",
                "bold": True,
            },
            {
                "type": "text",
                "source": "takeaway",
                "style": "quote" if index in {0, 2, 9} else "subtitle",
                "x": title_x,
                "y": 53 if index == 0 else 42,
                "w": title_w,
                "h": 18,
                "color": "inverse" if dark else "primary",
                "fill": "",
                "shape": "rect",
                "align": "left",
                "bold": False,
            },
        ]
    return ppt_data


def _canvas_overlap_ratio(first: dict[str, Any], second: dict[str, Any]) -> float:
    left = max(float(first.get("x", 0)), float(second.get("x", 0)))
    top = max(float(first.get("y", 0)), float(second.get("y", 0)))
    right = min(
        float(first.get("x", 0)) + float(first.get("w", 0)),
        float(second.get("x", 0)) + float(second.get("w", 0)),
    )
    bottom = min(
        float(first.get("y", 0)) + float(first.get("h", 0)),
        float(second.get("y", 0)) + float(second.get("h", 0)),
    )
    if right <= left or bottom <= top:
        return 0
    intersection = (right - left) * (bottom - top)
    smaller = min(
        float(first.get("w", 0)) * float(first.get("h", 0)),
        float(second.get("w", 0)) * float(second.get("h", 0)),
    )
    return intersection / smaller if smaller else 0


def _deterministic_ppt_quality(ppt_data: dict[str, Any]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    slides = ppt_data.get("slides") or []
    design = ppt_data.get("design") or {}
    if design.get("status") != "personalized":
        issues.append(
            {
                "slide_index": None,
                "severity": "high",
                "category": "visual",
                "message": "视觉设计 Agent 未完成个性化画布，当前使用安全回退版式。",
                "suggestion": "检查模型连接后重新生成 PPT。",
            }
        )
    for index, slide in enumerate(slides):
        canvas = slide.get("canvas") or []
        if not canvas:
            issues.append(
                {
                    "slide_index": index,
                    "severity": "high",
                    "category": "visual",
                    "message": "本页缺少个性化自由画布。",
                    "suggestion": "重新设计本页视觉构图。",
                }
            )
            continue
        text_elements = [
            item
            for item in canvas
            if (
                item.get("type") == "text"
                and item.get("source") != "page_number"
                and _resolve_ppt_canvas_source(
                    slide,
                    str(item.get("source") or ""),
                    index,
                )
            )
        ]
        if len(text_elements) < 2:
            issues.append(
                {
                    "slide_index": index,
                    "severity": "medium",
                    "category": "density",
                    "message": "本页信息层级过少，可能显得空洞。",
                    "suggestion": "补充一条核心结论或必要的教学要点。",
                }
            )
        for first_index, first in enumerate(text_elements):
            for second in text_elements[first_index + 1 :]:
                if _canvas_overlap_ratio(first, second) > 0.28:
                    issues.append(
                        {
                            "slide_index": index,
                            "severity": "high",
                            "category": "visual",
                            "message": "检测到两个文字区域明显重叠。",
                            "suggestion": "重新调整本页元素位置或减少文字。",
                        }
                    )
                    break
            else:
                continue
            break
        available_sources = {
            f"bullet:{item_index}"
            for item_index, _ in enumerate(slide.get("bullets") or [])
        }
        used_sources = {str(item.get("source") or "") for item in text_elements}
        if available_sources and not available_sources.intersection(used_sources):
            issues.append(
                {
                    "slide_index": index,
                    "severity": "medium",
                    "category": "content",
                    "message": "本页生成了教学要点，但画布没有呈现任何要点。",
                    "suggestion": "选择关键要点呈现在页面上，或压缩到讲者备注。",
                }
            )
    layouts = {str(item.get("layout") or "") for item in slides}
    if "discussion" not in layouts:
        issues.append(
            {
                "slide_index": None,
                "severity": "medium",
                "category": "interaction",
                "message": "整套课件没有明确的课堂参与页面。",
                "suggestion": "结合教学目标增加讨论、判断或小组任务。",
            }
        )
    if "summary" not in layouts:
        issues.append(
            {
                "slide_index": None,
                "severity": "medium",
                "category": "narrative",
                "message": "整套课件缺少对开场问题的总结回应。",
                "suggestion": "增加能够收束理论认识和应用方法的结尾页。",
            }
        )
    penalty = {"high": 14, "medium": 7, "low": 3}
    score = max(0, 100 - sum(penalty.get(item["severity"], 3) for item in issues))
    return {
        "score": score,
        "passed": score >= 80 and not any(item["severity"] == "high" for item in issues),
        "summary": "自动版面与结构检查完成。",
        "issues": issues[:30],
        "reviewer": "ppt-quality-gate-v1",
        "checked_time": _now().isoformat(),
    }


def _merge_ppt_quality(
    deterministic: dict[str, Any],
    model_review: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(model_review, dict):
        return deterministic
    model_issues: list[dict[str, Any]] = []
    for raw in (model_review.get("issues") or [])[:20]:
        if not isinstance(raw, dict):
            continue
        severity = str(raw.get("severity") or "low")
        category = str(raw.get("category") or "content")
        try:
            slide_index = int(raw["slide_index"]) if raw.get("slide_index") is not None else None
        except (TypeError, ValueError):
            slide_index = None
        model_issues.append(
            {
                "slide_index": slide_index,
                "severity": severity if severity in {"high", "medium", "low"} else "low",
                "category": category,
                "message": _fit_ppt_phrase(raw.get("message"), 100),
                "suggestion": _fit_ppt_phrase(raw.get("suggestion"), 120),
            }
        )
    all_issues = [*(deterministic.get("issues") or []), *model_issues]
    try:
        model_score = int(model_review.get("score"))
    except (TypeError, ValueError):
        model_score = deterministic["score"]
    score = max(0, min(100, min(deterministic["score"], model_score)))
    return {
        **deterministic,
        "score": score,
        "passed": score >= 80 and not any(item["severity"] == "high" for item in all_issues),
        "summary": _fit_ppt_phrase(model_review.get("summary"), 160)
        or deterministic["summary"],
        "issues": all_issues[:30],
        "reviewer": "ppt-quality-agent-v1",
    }


def _invoke_streaming_text(
    prompt: ChatPromptTemplate,
    model: ChatOpenAI,
    variables: dict[str, str],
) -> str:
    """优先流式读取；兼容接口空流或中断时自动改用完整响应重试一次。"""
    last_error: Exception | None = None
    for attempt in range(2):
        chunks: list[str] = []
        try:
            for chunk in (prompt | model | StrOutputParser()).stream(variables):
                if chunk:
                    chunks.append(chunk)
            result = clean_model_text("".join(chunks))
            if result:
                return result
            last_error = RuntimeError("流式响应为空")
        except Exception as exc:  # 兼容部分 OpenAI 协议网关的偶发中断
            last_error = exc
        logger.warning(
            "llm_stream_attempt_failed attempt=%s model=%s reason=%s",
            attempt + 1,
            getattr(model, "model_name", "unknown"),
            str(last_error) or type(last_error).__name__,
        )

    # 有些兼容网关会建立 SSE 连接却不下发 token；此时非流式 invoke 更稳定。
    try:
        response = (prompt | model).invoke(variables)
        content = getattr(response, "content", response)
        if isinstance(content, str):
            result = clean_model_text(content)
        elif isinstance(content, list):
            result = clean_model_text("".join(
                str(item.get("text", "")) if isinstance(item, dict) else str(item)
                for item in content
            ))
        else:
            result = clean_model_text(content)
        if result:
            logger.info("llm_stream_fallback_succeeded model=%s", getattr(model, "model_name", "unknown"))
            return result
    except Exception as exc:
        last_error = exc
        logger.warning(
            "llm_non_stream_fallback_failed model=%s reason=%s",
            getattr(model, "model_name", "unknown"),
            str(exc) or type(exc).__name__,
        )

    raise RuntimeError("大模型连续两次未返回有效内容，请稍后重试") from last_error


def _extract_json_object(raw: str, *, error_message: str) -> dict[str, Any]:
    """从模型可能附带说明或 Markdown 代码块的输出中安全提取首个 JSON 对象。"""
    candidate = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", raw.strip(), flags=re.I)
    decoder = json.JSONDecoder()
    for index, character in enumerate(candidate):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(candidate[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise RuntimeError(error_message)


class LessonOutlineGenerator:
    def __init__(self) -> None:
        self.model_name = "mock" if settings.ai_mock_mode else settings.llm_model

    def generate(self, variables: dict[str, str]) -> dict[str, Any]:
        if settings.ai_mock_mode:
            total_minutes = max(45, int(variables["lesson_hours"]) * 45)
            introduction = max(8, round(total_minutes * 0.15))
            lecture = max(20, round(total_minutes * 0.5))
            discussion = total_minutes - introduction - lecture
            return {
                "title": f"{variables['chapter_title']}教学课纲",
                "positioning": "围绕当前教材专题建立理论结构，并通过已确认资料联系时代发展。",
                "objectives": {
                    "knowledge": ["理解专题核心概念、主要观点和论证逻辑"],
                    "ability": ["能够依据教材与权威资料分析现实问题"],
                    "values": ["形成理论联系实际、依据原文作出判断的学习习惯"],
                },
                "key_points": ["专题核心概念及其逻辑关系[资料1]"],
                "difficult_points": ["区分教材基本原理与补充材料中的实践说明"],
                "teaching_flow": [
                    {
                        "stage": "问题导入",
                        "duration_minutes": introduction,
                        "teacher_activity": "提出与专题主旨相关的现实问题，引导学生定位教材依据。",
                        "student_activity": "阅读证据摘要并形成初步判断。",
                        "evidence_refs": ["资料1"],
                    },
                    {
                        "stage": "理论讲授",
                        "duration_minutes": lecture,
                        "teacher_activity": "按照概念、观点和逻辑关系讲解专题内容。",
                        "student_activity": "记录知识结构并标注仍有疑问的概念。",
                        "evidence_refs": ["资料1"],
                    },
                    {
                        "stage": "讨论与总结",
                        "duration_minutes": discussion,
                        "teacher_activity": "组织观点辨析，依据原文归纳结论。",
                        "student_activity": "小组讨论并用资料编号说明依据。",
                        "evidence_refs": ["资料1"],
                    },
                ],
                "discussion_questions": ["本专题的核心观点如何回应当前实践问题？请说明教材依据。"],
                "after_class_task": "整理一张包含核心概念、教材依据和个人疑问的学习卡片。",
                "citation_notes": ["模拟模式仅用于验证流程，正式使用前请逐条核验引用。"],
            }
        if not settings.llm_api_key:
            raise RuntimeError("尚未配置 LLM_API_KEY")
        prompt = ChatPromptTemplate.from_messages(
            [("system", LESSON_PREP_SYSTEM_PROMPT), ("human", LESSON_PREP_USER_PROMPT)]
        )
        model = ChatOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            timeout=settings.llm_timeout_seconds,
            streaming=True,
        )
        raw = _invoke_streaming_text(prompt, model, variables)
        parsed = _extract_json_object(raw, error_message="模型未返回合法的课纲 JSON")
        if not isinstance(parsed, dict) or not parsed.get("title") or not parsed.get("teaching_flow"):
            raise RuntimeError("模型返回的课纲缺少必要字段")
        return parsed


class LessonArtifactGenerator:
    def __init__(self) -> None:
        self.model_name = "mock" if settings.ai_mock_mode else settings.llm_model

    @staticmethod
    def _target_slide_count(variables: dict[str, str]) -> int | None:
        try:
            preferences = json.loads(variables.get("ppt_preferences") or "{}")
            value = preferences.get("slide_count")
            return int(value) if value is not None else None
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    def _personalize_ppt(
        self,
        ppt_data: dict[str, Any],
        variables: dict[str, str],
    ) -> dict[str, Any]:
        slides = ppt_data.get("slides") or []
        if not slides:
            return ppt_data
        design_prompt = ChatPromptTemplate.from_messages(
            [
                ("system", LESSON_PPT_DESIGN_SYSTEM_PROMPT),
                ("human", LESSON_PPT_DESIGN_USER_PROMPT),
            ]
        )
        design_model = ChatOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            temperature=max(settings.llm_temperature, 0.55),
            timeout=max(settings.llm_timeout_seconds, 120),
            streaming=True,
        )
        design_raw = _invoke_streaming_text(
            design_prompt,
            design_model,
            {
                "course_name": variables["course_name"],
                "chapter_title": variables["chapter_title"],
                "ppt_preferences": variables.get("ppt_preferences", "{}"),
                "template_reference": variables.get("template_reference", "{}"),
                "ppt_json": json.dumps(ppt_data, ensure_ascii=False),
            },
        )
        parsed_design = _extract_json_object(
            design_raw,
            error_message="视觉设计 Agent 未返回合法 JSON",
        )
        if not isinstance(parsed_design, dict):
            raise RuntimeError("视觉设计 Agent 返回格式无效")
        design, pages = _sanitize_ppt_design(parsed_design, len(slides))
        try:
            template_reference = json.loads(variables.get("template_reference") or "{}")
        except json.JSONDecodeError:
            template_reference = {}
        template_palette = template_reference.get("palette")
        if isinstance(template_palette, dict) and template_palette:
            design["palette"] = {
                role: _sanitize_hex_color(
                    template_palette.get(role),
                    design["palette"][role],
                )
                for role in PPT_DEFAULT_PALETTE
            }
            design["template_reference"] = {
                "id": template_reference.get("id"),
                "name": template_reference.get("name"),
                "compatibility": template_reference.get("compatibility"),
            }
        template_fonts = template_reference.get("fonts")
        if isinstance(template_fonts, dict):
            design["fonts"] = {
                "heading": _fit_ppt_phrase(
                    template_fonts.get("heading") or design["fonts"]["heading"],
                    80,
                ),
                "body": _fit_ppt_phrase(
                    template_fonts.get("body") or design["fonts"]["body"],
                    80,
                ),
            }
        minimum_pages = max(1, int(len(slides) * 0.7))
        if len(pages) < minimum_pages:
            raise RuntimeError("视觉设计 Agent 返回的有效页面不足")
        accepted_pages: dict[int, list[dict[str, Any]]] = {}
        fallback_pages: list[int] = []
        canvas_diagnostics: dict[str, Any] = {}
        for index, slide in enumerate(slides):
            page = pages.get(index)
            if page is None:
                fallback_pages.append(index)
                continue
            prepared, diagnostics = _prepare_ppt_canvas_for_slide(
                slide,
                page,
                index,
            )
            canvas_diagnostics[str(index)] = diagnostics
            if prepared is None:
                fallback_pages.append(index)
                continue
            accepted_pages[index] = prepared

        design["status"] = (
            "personalized" if len(accepted_pages) == len(slides) else "hybrid"
        )
        design["designed_pages"] = len(accepted_pages)
        design["fallback_pages"] = fallback_pages
        design["canvas_diagnostics"] = canvas_diagnostics
        ppt_data["design"] = design
        for index, slide in enumerate(slides):
            slide.pop("canvas", None)
            slide.pop("canvas_background", None)
            if index in accepted_pages:
                slide["canvas"] = accepted_pages[index]
                slide["canvas_background"] = accepted_pages[index][0]["background"]
                visual_prompt = design.get("visual_prompts", {}).get(str(index))
                if visual_prompt:
                    slide["visual_prompt"] = visual_prompt
        return ppt_data

    def _review_ppt(
        self,
        ppt_data: dict[str, Any],
        variables: dict[str, str],
    ) -> dict[str, Any]:
        deterministic = _deterministic_ppt_quality(ppt_data)
        if settings.ai_mock_mode:
            return deterministic
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", LESSON_PPT_REVIEW_SYSTEM_PROMPT),
                ("human", LESSON_PPT_REVIEW_USER_PROMPT),
            ]
        )
        model = ChatOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            temperature=0.1,
            timeout=max(settings.llm_timeout_seconds, 120),
            streaming=True,
        )
        try:
            raw = _invoke_streaming_text(
                prompt,
                model,
                {
                    "course_name": variables["course_name"],
                    "chapter_title": variables["chapter_title"],
                    "ppt_preferences": variables.get("ppt_preferences", "{}"),
                    "ppt_json": json.dumps(ppt_data, ensure_ascii=False),
                },
            )
            parsed = _extract_json_object(raw, error_message="PPT 质量检查未返回合法 JSON")
            return _merge_ppt_quality(deterministic, parsed)
        except Exception as exc:
            logger.warning("ppt_quality_agent_fallback reason=%s", exc)
            return deterministic

    def revise_slide(
        self,
        *,
        course_name: str,
        chapter_title: str,
        ppt_data: dict[str, Any],
        slide_index: int,
        request: PptSlideRevisionRequest,
        evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        original = ppt_data["slides"][slide_index]
        if settings.ai_mock_mode:
            revised = json.loads(json.dumps(original, ensure_ascii=False))
            if request.mode != "design":
                revised["takeaway"] = _fit_ppt_phrase(request.instruction, 62)
            mock = _attach_mock_ppt_design(
                {"title": ppt_data.get("title"), "slides": [revised]}
            )
            revised["canvas"] = mock["slides"][0]["canvas"]
            revised["canvas_background"] = mock["slides"][0]["canvas_background"]
            return revised

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", LESSON_PPT_REVISION_SYSTEM_PROMPT),
                ("human", LESSON_PPT_REVISION_USER_PROMPT),
            ]
        )
        model = ChatOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            temperature=max(settings.llm_temperature, 0.45),
            timeout=max(settings.llm_timeout_seconds, 120),
            streaming=True,
        )
        evidence_context = "\n\n".join(
            f"[资料{index}] {item.get('source_title') or '课程资料'}\n"
            f"{item.get('position') or ''}\n{item.get('excerpt') or ''}"
            for index, item in enumerate(evidence, start=1)
        )
        raw = _invoke_streaming_text(
            prompt,
            model,
            {
                "course_name": course_name,
                "chapter_title": chapter_title,
                "revision_mode": request.mode,
                "instruction": request.instruction,
                "design_json": json.dumps(ppt_data.get("design") or {}, ensure_ascii=False),
                "slide_json": json.dumps(original, ensure_ascii=False),
                "evidence_context": evidence_context,
            },
        )
        parsed = _extract_json_object(raw, error_message="单页修改 Agent 未返回合法 JSON")
        raw_slide = parsed.get("slide")
        if request.mode == "design":
            raw_slide = json.loads(json.dumps(original, ensure_ascii=False))
        if not isinstance(raw_slide, dict):
            raise RuntimeError("单页修改 Agent 未返回页面内容")
        dummy = {
            "layout": "title",
            "title": "占位",
            "takeaway": "",
            "bullets": [],
        }
        normalized = _sanitize_ppt_visible_content(
            {"title": ppt_data.get("title"), "slides": [dummy, raw_slide]}
        )["slides"]
        if len(normalized) < 2:
            raise RuntimeError("修改后的页面内容无效")
        revised = normalized[1]
        valid_refs = {f"资料{index}" for index in range(1, len(evidence) + 1)}
        revised["evidence_refs"] = [
            item
            for item in revised.get("evidence_refs") or []
            if str(item) in valid_refs
        ]
        design_page = parsed.get("design_page")
        if not isinstance(design_page, dict):
            raise RuntimeError("单页修改 Agent 未返回页面设计")
        design, pages = _sanitize_ppt_design(
            {
                "design": ppt_data.get("design") or {},
                "pages": [{"index": 0, **design_page}],
            },
            1,
        )
        if 0 not in pages:
            raise RuntimeError("修改后的页面设计未通过画布校验")
        prepared, _ = _prepare_ppt_canvas_for_slide(revised, pages[0], slide_index)
        if prepared is None:
            raise RuntimeError("修改后的页面正文覆盖不足，请重新生成页面设计")
        revised["canvas"] = prepared
        revised["canvas_background"] = prepared[0]["background"]
        return revised

    def generate(self, variables: dict[str, str]) -> dict[str, Any]:
        if settings.ai_mock_mode:
            outline = json.loads(variables["outline_json"])
            chapter_title = variables["chapter_title"]
            teaching_flow = outline.get("teaching_flow") or []
            objectives = outline.get("objectives") or {}
            key_points = outline.get("key_points") or ["梳理专题核心概念"]
            difficult_points = outline.get("difficult_points") or ["区分基本原理与实践说明"]
            slides = [
                {
                    "layout": "title",
                    "title": outline.get("title") or f"{chapter_title}教学课件",
                    "takeaway": outline.get("positioning") or "从教材原文出发理解专题主旨",
                    "bullets": [],
                    "speaker_notes": "说明本次课程的学习目标与问题线索。",
                    "evidence_refs": [],
                },
                {
                    "layout": "agenda",
                    "title": "沿着四个问题展开本专题",
                    "takeaway": "从问题出发，逐步形成理论结构",
                    "bullets": ["现实问题是什么", "核心概念是什么", "理论逻辑如何展开", "如何联系实践"],
                    "speaker_notes": "说明本课的学习路径。",
                    "evidence_refs": [],
                },
                {
                    "layout": "question",
                    "title": "为什么必须在新时代继续坚持和发展",
                    "takeaway": outline.get("positioning") or "建立专题的整体认识",
                    "bullets": (objectives.get("knowledge") or [])[:3],
                    "speaker_notes": "用现实问题激活已有认知，引出教材主旨。",
                    "evidence_refs": ["资料1"],
                },
                {
                    "layout": "concept",
                    "title": "核心概念必须放回理论体系中理解",
                    "keyword": "坚持与发展",
                    "takeaway": "方向不能改变，实践不断发展",
                    "bullets": key_points[:4],
                    "speaker_notes": "讲解概念之间的关系，避免孤立记忆。",
                    "evidence_refs": ["资料1"],
                },
                {
                    "layout": "process",
                    "title": "理论认识沿着四层逻辑逐步展开",
                    "takeaway": "从时代方位走向实践要求",
                    "steps": [
                        {"title": "时代方位", "description": "认识新的历史条件"},
                        {"title": "理论主题", "description": "明确坚持和发展的对象"},
                        {"title": "实践路径", "description": "把理论转化为行动"},
                        {"title": "价值目标", "description": "指向民族复兴与人民幸福"},
                    ],
                    "bullets": [],
                    "speaker_notes": "按逻辑顺序串联本专题的重要观点。",
                    "evidence_refs": ["资料1"],
                },
                {
                    "layout": "comparison",
                    "title": "坚持与发展不是彼此割裂的两件事",
                    "takeaway": "在坚持中发展，在发展中坚持",
                    "left": {
                        "title": "坚持",
                        "points": ["守住根本方向", "把握基本原则", "保持理论定力"],
                    },
                    "right": {
                        "title": "发展",
                        "points": ["回应时代问题", "推进实践创新", "丰富理论内涵"],
                    },
                    "bullets": difficult_points[:2],
                    "speaker_notes": "对易混概念进行对照说明。",
                    "evidence_refs": ["资料1"],
                },
                {
                    "layout": "timeline",
                    "title": "理论创新始终与时代实践同向而行",
                    "takeaway": "实践发展不断提出新的理论课题",
                    "timeline": [
                        {"label": "历史起点", "title": "形成道路与制度基础"},
                        {"label": "新的时期", "title": "改革开放推进理论创新"},
                        {"label": "新时代", "title": "回答新的重大时代课题"},
                        {"label": "面向未来", "title": "以新实践丰富理论发展"},
                    ],
                    "bullets": [],
                    "speaker_notes": "联系历史进程理解理论发展的实践基础。",
                    "evidence_refs": ["资料1"],
                },
                {
                    "layout": "content",
                    "title": "教学重点落在理论与实践的统一",
                    "takeaway": teaching_flow[0].get("teacher_activity") if teaching_flow else "用理论分析现实问题",
                    "bullets": [
                        *(objectives.get("ability") or []),
                        *(objectives.get("values") or []),
                        *key_points[:2],
                    ],
                    "speaker_notes": "结合教学目标深化理论联系实际。",
                    "evidence_refs": ["资料1"],
                },
                {
                    "layout": "discussion",
                    "title": "课堂讨论：如何用本专题分析现实问题",
                    "takeaway": "观点表达必须建立在准确理解教材的基础上",
                    "bullets": outline.get("discussion_questions") or ["结合教材说明你的判断"],
                    "steps": [
                        {"title": "独立思考", "description": "形成个人判断"},
                        {"title": "小组辨析", "description": "比较不同观点"},
                        {"title": "原文核验", "description": "回到教材确认依据"},
                    ],
                    "speaker_notes": "组织小组讨论并要求学生核对教材原文。",
                    "evidence_refs": ["资料1"],
                },
                {
                    "layout": "summary",
                    "title": "把本专题沉淀为可迁移的认识框架",
                    "takeaway": "理解核心观点，更要掌握分析问题的方法",
                    "bullets": [
                        *key_points[:3],
                        outline.get("after_class_task") or "完成课后学习任务",
                    ],
                    "speaker_notes": "回顾目标并说明课后任务。",
                    "evidence_refs": ["资料1"],
                },
            ]
            lesson_objectives = [
                *objectives.get("knowledge", []),
                *objectives.get("ability", []),
                *objectives.get("values", []),
            ]
            mock_ppt = _attach_mock_ppt_design(
                _enforce_ppt_slide_count(
                    {
                    "title": outline.get("title") or f"{chapter_title}教学课件",
                    "subtitle": variables["course_name"],
                    "slides": slides,
                    },
                    self._target_slide_count(variables),
                    outline,
                )
            )
            try:
                template_reference = json.loads(variables.get("template_reference") or "{}")
            except json.JSONDecodeError:
                template_reference = {}
            if isinstance(template_reference.get("palette"), dict):
                mock_ppt["design"]["palette"] = {
                    role: _sanitize_hex_color(
                        template_reference["palette"].get(role),
                        mock_ppt["design"]["palette"][role],
                    )
                    for role in PPT_DEFAULT_PALETTE
                }
                mock_ppt["design"]["template_reference"] = {
                    "id": template_reference.get("id"),
                    "name": template_reference.get("name"),
                    "compatibility": template_reference.get("compatibility"),
                }
            if isinstance(template_reference.get("fonts"), dict):
                mock_ppt["design"]["fonts"] = {
                    "heading": _fit_ppt_phrase(
                        template_reference["fonts"].get("heading")
                        or mock_ppt["design"]["fonts"]["heading"],
                        80,
                    ),
                    "body": _fit_ppt_phrase(
                        template_reference["fonts"].get("body")
                        or mock_ppt["design"]["fonts"]["body"],
                        80,
                    ),
                }
            mock_ppt["quality_report"] = self._review_ppt(mock_ppt, variables)
            return {
                "ppt": mock_ppt,
                "lesson_plan": {
                    "title": f"{chapter_title}教学教案",
                    "overview": outline.get("positioning") or "",
                    "objectives": lesson_objectives,
                    "preparation": ["核验教材引用位置", "准备课堂讨论材料"],
                    "procedures": teaching_flow,
                    "assessment": ["观察课堂讨论中的依据使用情况", "检查课后学习卡片"],
                    "homework": outline.get("after_class_task") or "",
                },
                "classroom_activities": [
                    {
                        "title": "教材观点定位与小组辨析",
                        "purpose": "训练学生依据教材原文表达和辨析观点",
                        "duration_minutes": 15,
                        "format": "小组",
                        "instructions": [
                            "阅读教师指定的教材段落并标出关键词",
                            "小组形成一条结论并注明资料编号",
                            "各组交换观点并依据原文提出补充",
                        ],
                        "questions": outline.get("discussion_questions") or [],
                        "evidence_refs": ["资料1"],
                        "evaluation": "结论准确、依据真实、表达清晰",
                    }
                ],
            }
        if not settings.llm_api_key:
            raise RuntimeError("尚未配置 LLM_API_KEY")
        prompt = ChatPromptTemplate.from_messages(
            [("system", LESSON_ARTIFACT_SYSTEM_PROMPT), ("human", LESSON_ARTIFACT_USER_PROMPT)]
        )
        model = ChatOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            timeout=max(settings.llm_timeout_seconds, 120),
            streaming=True,
        )
        raw = _invoke_streaming_text(prompt, model, variables)
        parsed = _extract_json_object(raw, error_message="模型未返回合法的教学成果 JSON")
        if not isinstance(parsed, dict):
            raise RuntimeError("模型返回的教学成果格式无效")
        if not (parsed.get("ppt") or parsed.get("lesson_plan") or parsed.get("classroom_activities")):
            raise RuntimeError("模型返回的教学成果为空")
        ppt_data = parsed.get("ppt")
        if isinstance(ppt_data, dict) and ppt_data.get("slides"):
            ppt_data = _sanitize_ppt_visible_content(ppt_data)
            try:
                outline_data = json.loads(variables.get("outline_json") or "{}")
            except json.JSONDecodeError:
                outline_data = {}
            ppt_data = _enforce_ppt_slide_count(
                ppt_data,
                self._target_slide_count(variables),
                outline_data,
            )
            try:
                parsed["ppt"] = self._personalize_ppt(ppt_data, variables)
            except Exception as exc:
                logger.warning("ppt_visual_design_fallback reason=%s", exc)
                ppt_data["design"] = {
                    "name": "安全版式回退",
                    "concept": "视觉设计 Agent 暂不可用，使用结构化安全版式。",
                    "mood": "庄重、清晰",
                    "palette": PPT_DEFAULT_PALETTE,
                    "agent": "ppt-visual-designer-v1",
                    "status": "fallback",
                    "designed_pages": 0,
                }
                parsed["ppt"] = ppt_data
            parsed["ppt"]["quality_report"] = self._review_ppt(parsed["ppt"], variables)
        return parsed


class AgentService:
    def __init__(self, db: Session, user: User) -> None:
        self.db = db
        self.user = user

    @staticmethod
    def serialize(db: Session, run: AgentRun) -> AgentRunData:
        output_data = json.loads(json.dumps(run.output_data or {}, ensure_ascii=False))
        for artifact in (output_data.get("artifacts") or {}).values():
            if isinstance(artifact, dict):
                artifact.pop("storage_path", None)
        for version in output_data.get("ppt_versions") or []:
            if isinstance(version, dict):
                version.pop("preview", None)
        ppt = ((output_data.get("artifact_bundle") or {}).get("ppt") or {})
        for slide in ppt.get("slides") or []:
            asset = slide.get("visual_asset")
            if isinstance(asset, dict):
                asset.pop("storage_path", None)
                asset.pop("prompt", None)
        steps = db.scalars(
            select(AgentStep).where(AgentStep.run_id == run.id).order_by(AgentStep.step_order)
        ).all()
        return AgentRunData(
            id=run.id,
            created_by=run.created_by,
            agent_type=run.agent_type,
            status=run.status,
            course_id=run.course_id,
            chapter_id=run.chapter_id,
            teaching_class_id=run.teaching_class_id,
            current_step=run.current_step,
            input_data=run.input_data,
            evidence_snapshot=run.evidence_snapshot,
            output_data=output_data,
            model_name=run.model_name,
            prompt_version=run.prompt_version,
            error_message=run.error_message,
            cancel_requested=run.cancel_requested,
            retry_of_run_id=run.retry_of_run_id,
            started_time=run.started_time,
            finished_time=run.finished_time,
            created_time=run.created_time,
            updated_time=run.updated_time,
            steps=[
                AgentStepData(
                    id=item.id,
                    step_key=item.step_key,
                    title=item.title,
                    step_order=item.step_order,
                    status=item.status,
                    output_data=item.output_data,
                    error_message=item.error_message,
                    started_time=item.started_time,
                    finished_time=item.finished_time,
                )
                for item in steps
            ],
        )

    def _get_owned(self, run_id: int) -> AgentRun:
        run = self.db.get(AgentRun, run_id)
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="智能任务不存在")
        if self.user.role != "admin" and run.created_by != self.user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权查看该智能任务")
        return run

    def _validate_context(self, payload: AgentRunCreate) -> tuple[Course, Chapter]:
        course = self.db.get(Course, payload.course_id)
        chapter = self.db.get(Chapter, payload.chapter_id)
        if course is None or chapter is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="课程或专题不存在")
        if chapter.course_id != course.id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="专题不属于当前课程")
        if payload.teaching_class_id is not None:
            teaching_class = self.db.get(TeachingClass, payload.teaching_class_id)
            if teaching_class is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="教学班不存在")
            if self.user.role == "teacher":
                allowed = self.db.scalar(
                    select(TeachingClass.id)
                    .outerjoin(
                        TeachingClassTeacher,
                        TeachingClassTeacher.teaching_class_id == TeachingClass.id,
                    )
                    .where(
                        TeachingClass.id == teaching_class.id,
                        or_(
                            TeachingClass.owner_id == self.user.id,
                            TeachingClassTeacher.user_id == self.user.id,
                        ),
                    )
                )
                if allowed is None:
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权使用该教学班")
        return course, chapter

    def create(self, payload: AgentRunCreate, *, retry_of: int | None = None) -> AgentRunData:
        course, chapter = self._validate_context(payload)
        input_data = payload.input.model_dump()
        run = AgentRun(
            created_by=self.user.id,
            agent_type=payload.agent_type,
            status="running",
            course_id=course.id,
            chapter_id=chapter.id,
            teaching_class_id=payload.teaching_class_id,
            current_step=0,
            input_data=input_data,
            model_name="mock" if settings.ai_mock_mode else settings.llm_model,
            retry_of_run_id=retry_of,
            started_time=_now(),
        )
        self.db.add(run)
        self.db.flush()
        steps: list[AgentStep] = []
        for order, (key, title) in enumerate(STEP_DEFINITIONS):
            step = AgentStep(
                run_id=run.id,
                step_key=key,
                title=title,
                step_order=order,
                status="pending",
            )
            self.db.add(step)
            steps.append(step)
        now = _now()
        steps[0].status = "completed"
        steps[0].started_time = now
        steps[0].finished_time = now
        steps[0].output_data = {
            "course_name": course.name,
            "chapter_title": chapter.title,
            **input_data,
        }
        steps[1].status = "running"
        steps[1].started_time = now
        self.db.flush()
        try:
            prepared = AiService(self.db, user=self.user)._prepare(
                AiAssistRequest(
                    course_id=course.id,
                    chapter_id=chapter.id,
                    learning_stage="preview",
                    task_type="chapter_summary",
                    question="为教师备课构建本专题证据包",
                )
            )
            if isinstance(prepared, AiAssistData):
                raise ValueError(prepared.answer)
            variables, sources, _ = prepared
            run.evidence_snapshot = [item.model_dump(mode="json") for item in sources]
            run.context_snapshot = variables["chapter_content"]
            run.status = "waiting_confirmation"
            run.current_step = 1
            steps[1].status = "completed"
            steps[1].finished_time = _now()
            steps[1].output_data = {"evidence_count": len(sources)}
        except Exception as exc:
            run.status = "failed"
            run.error_message = str(exc)
            run.finished_time = _now()
            steps[1].status = "failed"
            steps[1].error_message = str(exc)
            steps[1].finished_time = _now()
        self.db.commit()
        self.db.refresh(run)
        return self.serialize(self.db, run)

    def get(self, run_id: int) -> AgentRunData:
        return self.serialize(self.db, self._get_owned(run_id))

    def list(self, limit: int = 30) -> list[AgentRunData]:
        query = select(AgentRun).order_by(AgentRun.id.desc()).limit(limit)
        if self.user.role != "admin":
            query = query.where(AgentRun.created_by == self.user.id)
        return [self.serialize(self.db, item) for item in self.db.scalars(query).all()]

    def approve_evidence(self, run_id: int) -> AgentRunData:
        run = self._get_owned(run_id)
        if run.status != "waiting_confirmation":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="当前任务不等待证据确认")
        if not run.evidence_snapshot or not run.context_snapshot:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="证据快照不完整")
        step = self.db.scalar(
            select(AgentStep).where(
                AgentStep.run_id == run.id,
                AgentStep.step_key == "generate_outline",
            )
        )
        if step is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="任务步骤不完整")
        run.status = "queued"
        run.current_step = 2
        step.status = "queued"
        self.db.commit()
        self.db.refresh(run)
        return self.serialize(self.db, run)

    def request_artifacts(self, run_id: int, payload: AgentArtifactRequest) -> AgentRunData:
        run = self._get_owned(run_id)
        if not (run.output_data or {}).get("outline"):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="请先生成并核验课纲")
        if run.status in {"queued", "running"}:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="当前任务仍在执行")
        step = self.db.scalar(
            select(AgentStep).where(
                AgentStep.run_id == run.id,
                AgentStep.step_key == "generate_artifacts",
            )
        )
        if step is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="任务步骤不完整")
        output_types = list(dict.fromkeys(payload.output_types))
        ppt_preferences = (
            payload.ppt_preferences.model_dump()
            if "ppt" in output_types and payload.ppt_preferences is not None
            else {}
        )
        if ppt_preferences and ppt_preferences["min_slides"] > ppt_preferences["max_slides"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="PPT 最少页数不能大于最多页数",
            )
        template_reference = PresentationTemplateService(self.db, self.user).prompt_reference(
            ppt_preferences.get("template_id") if ppt_preferences else None
        )
        if "ppt" in output_types:
            self._archive_ppt_version(run, "重新生成整套 PPT")
        run.status = "queued"
        run.current_step = 3
        run.cancel_requested = False
        run.error_message = None
        run.finished_time = None
        run.prompt_version = "lesson-artifacts-v1"
        input_data = dict(run.input_data or {})
        input_data["artifact_output_types"] = output_types
        input_data["ppt_preferences"] = ppt_preferences
        input_data["ppt_template_reference"] = template_reference
        run.input_data = input_data
        step.status = "queued"
        step.input_data = {
            "output_types": output_types,
            "ppt_preferences": ppt_preferences,
            "template_reference": template_reference,
        }
        step.output_data = {}
        step.error_message = None
        step.started_time = None
        step.finished_time = None
        self.db.commit()
        self.db.refresh(run)
        return self.serialize(self.db, run)

    def artifact_download(self, run_id: int, artifact_key: str) -> tuple[Path, dict[str, Any]]:
        run = self._get_owned(run_id)
        artifact = ((run.output_data or {}).get("artifacts") or {}).get(artifact_key)
        if not isinstance(artifact, dict):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="教学成果不存在")
        try:
            path = PresentationArtifactService(run.id).resolve_download(artifact)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return path, artifact

    @staticmethod
    def _archive_ppt_version(run: AgentRun, reason: str) -> None:
        output_data = dict(run.output_data or {})
        bundle = output_data.get("artifact_bundle") or {}
        ppt_data = bundle.get("ppt") if isinstance(bundle, dict) else None
        if not isinstance(ppt_data, dict) or not ppt_data.get("slides"):
            return
        versions = list(output_data.get("ppt_versions") or [])
        versions.append(
            {
                "version_id": _now().strftime("%Y%m%d%H%M%S%f"),
                "created_time": _now().isoformat(),
                "reason": reason,
                "title": ppt_data.get("title") or "教学 PPT",
                "slide_count": len(ppt_data.get("slides") or []),
                "design_name": (ppt_data.get("design") or {}).get("name"),
                "preview": json.loads(json.dumps(ppt_data, ensure_ascii=False)),
            }
        )
        output_data["ppt_versions"] = versions[-10:]
        run.output_data = output_data

    def _save_updated_ppt(self, run: AgentRun, ppt_data: dict[str, Any]) -> None:
        course = self.db.get(Course, run.course_id)
        chapter = self.db.get(Chapter, run.chapter_id)
        if course is None or chapter is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="课程或专题已不存在")
        artifact = PresentationArtifactService(run.id).render_pptx(
            course_name=course.name,
            chapter_title=chapter.title,
            ppt_data=ppt_data,
            evidence=run.evidence_snapshot or [],
        )
        output_data = dict(run.output_data or {})
        bundle = dict(output_data.get("artifact_bundle") or {})
        artifacts = dict(output_data.get("artifacts") or {})
        bundle["ppt"] = ppt_data
        artifacts["ppt"] = artifact
        output_data["artifact_bundle"] = bundle
        output_data["artifacts"] = artifacts
        run.output_data = output_data

    def revise_ppt_slide(
        self,
        run_id: int,
        slide_index: int,
        request: PptSlideRevisionRequest,
    ) -> AgentRunData:
        run = self._get_owned(run_id)
        if run.status in {"queued", "running"}:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="当前任务仍在执行")
        ppt_data = json.loads(
            json.dumps(
                ((run.output_data or {}).get("artifact_bundle") or {}).get("ppt"),
                ensure_ascii=False,
            )
        )
        if not isinstance(ppt_data, dict) or not ppt_data.get("slides"):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="尚未生成 PPT")
        if not 0 <= slide_index < len(ppt_data["slides"]):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PPT 页面不存在")
        course = self.db.get(Course, run.course_id)
        chapter = self.db.get(Chapter, run.chapter_id)
        if course is None or chapter is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="课程或专题已不存在")
        try:
            revised = LessonArtifactGenerator().revise_slide(
                course_name=course.name,
                chapter_title=chapter.title,
                ppt_data=ppt_data,
                slide_index=slide_index,
                request=request,
                evidence=run.evidence_snapshot or [],
            )
            self._archive_ppt_version(run, f"修改第 {slide_index + 1} 页前")
            ppt_data["slides"][slide_index] = revised
            ppt_data["quality_report"] = LessonArtifactGenerator()._review_ppt(
                ppt_data,
                {
                    "course_name": course.name,
                    "chapter_title": chapter.title,
                    "ppt_preferences": json.dumps(
                        (run.input_data or {}).get("ppt_preferences") or {},
                        ensure_ascii=False,
                    ),
                },
            )
            self._save_updated_ppt(run, ppt_data)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"本页重新生成失败：{exc}",
            ) from exc
        self.db.commit()
        self.db.refresh(run)
        return self.serialize(self.db, run)

    def restore_ppt_version(self, run_id: int, version_id: str) -> AgentRunData:
        run = self._get_owned(run_id)
        if run.status in {"queued", "running"}:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="当前任务仍在执行")
        versions = list((run.output_data or {}).get("ppt_versions") or [])
        target = next(
            (item for item in versions if str(item.get("version_id")) == version_id),
            None,
        )
        if target is None or not isinstance(target.get("preview"), dict):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PPT 历史版本不存在")
        self._archive_ppt_version(run, f"恢复版本 {version_id} 前")
        self._save_updated_ppt(
            run,
            json.loads(json.dumps(target["preview"], ensure_ascii=False)),
        )
        self.db.commit()
        self.db.refresh(run)
        return self.serialize(self.db, run)

    def cancel(self, run_id: int) -> AgentRunData:
        run = self._get_owned(run_id)
        if run.status in {"completed", "failed", "cancelled"}:
            return self.serialize(self.db, run)
        run.cancel_requested = True
        if run.status in {"queued", "waiting_confirmation"}:
            run.status = "cancelled"
            run.finished_time = _now()
        self.db.commit()
        self.db.refresh(run)
        return self.serialize(self.db, run)

    def retry(self, run_id: int) -> AgentRunData:
        previous = self._get_owned(run_id)
        if previous.status not in {"failed", "cancelled"}:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="只有失败或已取消任务可以重试")
        payload = AgentRunCreate(
            agent_type="teacher_lesson_prep",
            course_id=previous.course_id,
            chapter_id=previous.chapter_id,
            teaching_class_id=previous.teaching_class_id,
            input=previous.input_data,
        )
        return self.create(payload, retry_of=previous.id)


def execute_lesson_outline(run_id: int, bind: Engine) -> None:
    """后台生成课纲；使用独立 Session，避免占用请求数据库会话。"""
    with Session(bind=bind, autoflush=False, expire_on_commit=False) as db:
        run = db.get(AgentRun, run_id)
        if run is None or run.status not in {"queued", "running"}:
            return
        step = db.scalar(
            select(AgentStep).where(
                AgentStep.run_id == run.id,
                AgentStep.step_key == "generate_outline",
            )
        )
        if step is None:
            return
        if run.cancel_requested:
            run.status = "cancelled"
            run.finished_time = _now()
            db.commit()
            return
        run.status = "running"
        step.status = "running"
        step.started_time = _now()
        db.commit()
        try:
            course = db.get(Course, run.course_id)
            chapter = db.get(Chapter, run.chapter_id)
            if course is None or chapter is None:
                raise RuntimeError("课程或专题已不存在")
            input_data = run.input_data
            outline = LessonOutlineGenerator().generate(
                {
                    "course_name": course.name,
                    "chapter_title": chapter.title,
                    "lesson_hours": str(input_data.get("lesson_hours", 2)),
                    "student_level": str(input_data.get("student_level", "本科生")),
                    "teaching_goal": str(input_data.get("teaching_goal") or "按教材要求完成本专题教学"),
                    "evidence_context": run.context_snapshot or "",
                }
            )
            db.refresh(run)
            if run.cancel_requested:
                run.status = "cancelled"
                run.finished_time = _now()
                step.status = "cancelled"
            else:
                run.output_data = {"outline": outline}
                run.status = "completed"
                run.current_step = 2
                run.finished_time = _now()
                step.status = "completed"
                step.output_data = {"title": outline.get("title", "课纲草稿")}
                step.finished_time = _now()
                artifact_step = db.scalar(
                    select(AgentStep).where(
                        AgentStep.run_id == run.id,
                        AgentStep.step_key == "generate_artifacts",
                    )
                )
                if artifact_step is not None:
                    artifact_step.status = "pending"
            db.commit()
        except Exception as exc:
            logger.exception("lesson prep agent failed run_id=%s", run_id)
            run.status = "failed"
            run.error_message = str(exc)
            run.finished_time = _now()
            step.status = "failed"
            step.error_message = str(exc)
            step.finished_time = _now()
            db.commit()


def execute_lesson_artifacts(run_id: int, bind: Engine) -> None:
    """后台生成课件、教案与课堂活动，并渲染为可下载文件。"""
    with Session(bind=bind, autoflush=False, expire_on_commit=False) as db:
        run = db.get(AgentRun, run_id)
        if run is None or run.status not in {"queued", "running"}:
            return
        step = db.scalar(
            select(AgentStep).where(
                AgentStep.run_id == run.id,
                AgentStep.step_key == "generate_artifacts",
            )
        )
        if step is None:
            return
        if run.cancel_requested:
            run.status = "cancelled"
            run.finished_time = _now()
            step.status = "cancelled"
            step.finished_time = _now()
            db.commit()
            return
        run.status = "running"
        step.status = "running"
        step.started_time = _now()
        db.commit()
        try:
            course = db.get(Course, run.course_id)
            chapter = db.get(Chapter, run.chapter_id)
            outline = (run.output_data or {}).get("outline")
            if course is None or chapter is None or not isinstance(outline, dict):
                raise RuntimeError("课程、专题或课纲已不存在")
            requested = list(
                dict.fromkeys((run.input_data or {}).get("artifact_output_types") or [])
            )
            if not requested:
                raise RuntimeError("未选择需要生成的教学成果")
            evidence_context = "\n\n".join(
                f"[资料{index}] {item.get('source_title') or '课程资料'}\n"
                f"{item.get('position') or ''}\n{item.get('excerpt') or ''}"
                for index, item in enumerate(run.evidence_snapshot or [], start=1)
            )
            generated = LessonArtifactGenerator().generate(
                {
                    "course_name": course.name,
                    "chapter_title": chapter.title,
                    "lesson_hours": str((run.input_data or {}).get("lesson_hours", 2)),
                    "student_level": str((run.input_data or {}).get("student_level", "本科生")),
                    "teaching_goal": str(
                        (run.input_data or {}).get("teaching_goal")
                        or "按已确认课纲完成本专题教学"
                    ),
                    "output_types": "、".join(requested),
                    "outline_json": json.dumps(outline, ensure_ascii=False),
                    "evidence_context": evidence_context,
                    "ppt_preferences": json.dumps(
                        (run.input_data or {}).get("ppt_preferences") or {},
                        ensure_ascii=False,
                    ),
                    "template_reference": json.dumps(
                        (run.input_data or {}).get("ppt_template_reference") or {},
                        ensure_ascii=False,
                    ),
                }
            )
            renderer = PresentationArtifactService(run.id)
            artifacts: dict[str, Any] = {}
            if "ppt" in requested:
                ppt_data = generated.get("ppt")
                if not isinstance(ppt_data, dict) or not ppt_data.get("slides"):
                    raise RuntimeError("模型没有返回可用的 PPT 结构")
                ppt_data = _sanitize_ppt_visible_content(ppt_data)
                preferences = (run.input_data or {}).get("ppt_preferences") or {}
                if bool(preferences.get("include_visuals")):
                    ppt_data = PptMultimodalService(run.id).enhance(ppt_data)
                generated["ppt"] = ppt_data
                artifacts["ppt"] = renderer.render_pptx(
                    course_name=course.name,
                    chapter_title=chapter.title,
                    ppt_data=ppt_data,
                    evidence=run.evidence_snapshot or [],
                )
            if "lesson_plan" in requested:
                lesson_plan = generated.get("lesson_plan")
                if not isinstance(lesson_plan, dict):
                    raise RuntimeError("模型没有返回可用的教案结构")
                artifacts["lesson_plan"] = renderer.render_lesson_plan(
                    course_name=course.name,
                    chapter_title=chapter.title,
                    lesson_plan=lesson_plan,
                    evidence=run.evidence_snapshot or [],
                )
            if "classroom_activities" in requested:
                activities = generated.get("classroom_activities")
                if not isinstance(activities, list) or not activities:
                    raise RuntimeError("模型没有返回可用的课堂活动")
                artifacts["classroom_activities"] = renderer.render_activity_guide(
                    course_name=course.name,
                    chapter_title=chapter.title,
                    activities=activities,
                    evidence=run.evidence_snapshot or [],
                )
            db.refresh(run)
            if run.cancel_requested:
                run.status = "cancelled"
                run.finished_time = _now()
                step.status = "cancelled"
            else:
                # 成果是可独立重试的。重新生成 PPT、教案或课堂活动时，
                # 只替换本次请求的类型，保留同一任务中已经成功的其它成果，
                # 避免用户为了补一份教案而丢失已经核验过的 PPT。
                output_data = dict(run.output_data or {})
                existing_bundle = dict(output_data.get("artifact_bundle") or {})
                existing_bundle.update({key: value for key, value in generated.items() if key in requested})
                existing_artifacts = dict(output_data.get("artifacts") or {})
                existing_artifacts.update(artifacts)
                output_data["artifact_bundle"] = existing_bundle
                output_data["artifacts"] = existing_artifacts
                run.output_data = output_data
                run.status = "completed"
                run.current_step = 3
                run.finished_time = _now()
                step.status = "completed"
                step.output_data = {
                    "output_types": requested,
                    "artifact_count": len(artifacts),
                }
                step.finished_time = _now()
            db.commit()
        except Exception as exc:
            logger.exception("lesson artifact agent failed run_id=%s", run_id)
            step.status = "failed"
            step.error_message = str(exc)
            step.finished_time = _now()
            # 成果是课纲后的可选步骤。课纲已存在时，不应因一次 PPT/教案生成
            # 失败而抹掉前序成功状态；保留可用课纲并允许教师只重试该成果。
            if isinstance((run.output_data or {}).get("outline"), dict):
                run.status = "completed"
                run.current_step = max(run.current_step or 0, 2)
                run.error_message = None
            else:
                run.status = "failed"
                run.error_message = str(exc)
                run.finished_time = _now()
            db.commit()


def recover_agent_runs(bind: Engine) -> int:
    """进程重启后将失去执行器的任务转为可重试失败状态。"""
    with Session(bind=bind, autoflush=False, expire_on_commit=False) as db:
        runs = db.scalars(
            select(AgentRun).where(AgentRun.status.in_(["queued", "running"]))
        ).all()
        if not runs:
            return 0
        for run in runs:
            run.status = "failed"
            run.error_message = "服务重启导致后台任务中断，请点击重新执行"
            run.finished_time = _now()
            step = db.scalar(
                select(AgentStep)
                .where(
                    AgentStep.run_id == run.id,
                    AgentStep.status.in_(["queued", "running"]),
                )
                .order_by(AgentStep.step_order)
            )
            if step is not None:
                step.status = "failed"
                step.error_message = run.error_message
                step.finished_time = _now()
        db.commit()
        return len(runs)

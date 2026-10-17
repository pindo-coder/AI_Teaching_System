"""Closed SVG vocabulary. Model output is data, never executable code.

The content plan is authoritative: designers may position/wrap text but may not
silently drop a point or invent a different visible claim.
"""
from __future__ import annotations

import math
import re
import unicodedata
from xml.etree import ElementTree as ET

from app.schemas.presentation import PptPage

SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)
MAX_SVG_BYTES = 80_000
FONT_FAMILY = "Noto Sans CJK SC"
ALLOWED_TAGS = {"svg", "g", "rect", "circle", "ellipse", "line", "path", "polygon", "polyline", "text", "tspan", "image"}
ALLOWED_ATTRIBUTES = {
    "id", "x", "y", "dx", "dy", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry",
    "width", "height", "viewBox", "d", "points", "fill", "stroke", "stroke-width", "opacity",
    "fill-opacity", "stroke-opacity", "stroke-linecap", "stroke-linejoin", "stroke-dasharray",
    "font-family", "font-size", "font-weight", "text-anchor", "dominant-baseline", "lang",
    "preserveAspectRatio", "letter-spacing",
}


class SvgValidationError(ValueError):
    pass


def _number(value: str | None, default: float = 0) -> float:
    try:
        result = float(value) if value is not None else default
    except (TypeError, ValueError):
        raise SvgValidationError("坐标和字号必须使用有限数字") from None
    if not math.isfinite(result) or abs(result) > 100_000:
        raise SvgValidationError("坐标和字号超出允许范围")
    return result


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _svg_source(raw: str) -> str:
    raw = re.sub(r"^\s*```(?:svg|xml)?\s*|\s*```\s*$", "", raw.strip(), flags=re.I)
    if len(raw.encode()) > MAX_SVG_BYTES:
        raise SvgValidationError("SVG 超过大小限制")
    # XML comments are inert and are routinely emitted by designers. Strip
    # only well-formed comments; keep rejecting declarations, entities and PI.
    raw = re.sub(r"<!--(?:[^-]|-(?!-))*-->", "", raw)
    if re.search(r"<!|<\?", raw):
        raise SvgValidationError("SVG 包含不允许的 XML 声明")
    return raw


def bind_plan_text(raw: str, page: PptPage) -> str:
    """The application owns copy; the model owns geometry, never final wording.

    Fill existing named text frames, retaining their line positions. All copy
    is inserted, with any remaining text on the final line. The normal bounds
    validator then rejects overflow; this function never clips to capacity.
    Unknown or missing frames still fail the closed validator.
    """
    raw = _svg_source(raw)
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise SvgValidationError("SVG XML 不完整") from exc
    values = {"title": page.title, "takeaway": page.takeaway,
              **{f"bullet-{i}": value for i, value in enumerate(page.bullets)}}
    labels = {_compact(value): f"label-{i}" for i, value in enumerate(page.diagram_labels)}
    for node in root.iter(f"{{{SVG_NS}}}text"):
        key = node.get("id", "")
        # Repair naming only for an exact approved label. Unknown wording is
        # never promoted to the content plan, even if its ID looks plausible.
        if not key or re.fullmatch(r"(?:node|step|diagram|label)-\d+", key):
            approved = labels.get(_compact("".join(node.itertext())))
            if approved:
                node.set("id", approved)
        if node.get("id") not in values:
            continue
        value = values[node.get("id")]
        if _compact("".join(node.itertext())) == _compact(value):
            continue
        spans = list(node)
        if not spans:
            node.text = value
        elif all(child.tag == f"{{{SVG_NS}}}tspan" and not list(child) for child in spans):
            chunks = ([node] if (node.text or "").strip() else []) + spans
            cursor = 0
            for index, chunk in enumerate(chunks):
                capacity = len(chunk.text or "")
                chunk.text = value[cursor:] if index == len(chunks)-1 else value[cursor:cursor+capacity]
                cursor += capacity
                if chunk is not node:
                    chunk.tail = None
    return ET.tostring(root, encoding="unicode")


def validate_svg(raw: str, page: PptPage, *, include_visual: bool = False) -> str:
    raw = _svg_source(raw)
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise SvgValidationError("SVG XML 不完整") from exc
    if root.tag != f"{{{SVG_NS}}}svg" or root.get("viewBox") != "0 0 1280 720":
        raise SvgValidationError("SVG 必须使用命名空间和 1280×720 画布")
    nodes = list(root.iter())
    if len(nodes) > 250:
        raise SvgValidationError("页面元素超过 250 个")
    expected = {"title": page.title, "takeaway": page.takeaway}
    expected.update({f"bullet-{i}": text for i, text in enumerate(page.bullets)})
    required = set(expected)
    expected.update({f"label-{i}": value for i, value in enumerate(page.diagram_labels)})
    found: dict[str, str] = {}
    images = 0
    image_boxes = []
    text_boxes: list[tuple[str, float, float, float, float]] = []
    parent_of = {child: parent for parent in nodes for child in parent}
    for element in nodes:
        if not element.tag.startswith(f"{{{SVG_NS}}}"):
            raise SvgValidationError("页面包含其他 XML 命名空间")
        tag = element.tag.rsplit("}", 1)[-1]
        if tag not in ALLOWED_TAGS:
            raise SvgValidationError(f"不支持的 SVG 元素：{tag}")
        if tag == "svg" and element is not root:
            raise SvgValidationError("不允许嵌套 SVG 改变文字坐标系")
        for key, value in element.attrib.items():
            if key not in ALLOWED_ATTRIBUTES:
                raise SvgValidationError(f"不支持的 SVG 属性：{key}")
            if len(value) > 12_000 or re.search(r"url\s*\(|javascript:|data:|https?:|file:", value, re.I):
                raise SvgValidationError("SVG 不允许外部引用或可执行内容")
            if key in {"x", "y", "dx", "dy", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry", "width", "height", "stroke-width", "opacity", "fill-opacity", "stroke-opacity", "letter-spacing"}:
                number = _number(value)
                if key in {"width", "height", "r", "rx", "ry", "stroke-width"} and number < 0:
                    raise SvgValidationError("图形尺寸不能为负数")
        if tag == "tspan":
            if list(element) or parent_of.get(element) is None or parent_of[element].tag != f"{{{SVG_NS}}}text":
                raise SvgValidationError("只允许 text 的直属 tspan 换行")
            element.set("font-family", FONT_FAMILY)
        if tag == "image":
            images += 1
            if not include_visual or images > 1 or element.get("id") != "visual-asset":
                raise SvgValidationError("配图只能使用经授权的 visual-asset 槽位")
            x, y, w, h = (_number(element.get(k)) for k in ("x", "y", "width", "height"))
            if not (32 <= x < 1248 and 40 <= y < 660 and w > 0 and h > 0 and x+w <= 1248 and y+h <= 660):
                raise SvgValidationError("图片槽位越界")
            image_boxes.append((x, y, w, h))
        if tag != "text":
            continue
        if any(child.tag != f"{{{SVG_NS}}}tspan" for child in element):
            raise SvgValidationError("文字只能包含直属 tspan")
        key = element.get("id", "")
        text = "".join(element.itertext())
        number = re.fullmatch(r"num-(\d+)", key)
        if number and int(number[1]) < len(page.bullets):
            ordinal = int(number[1]) + 1
            if _compact(text) in {str(ordinal), str(ordinal).zfill(2)}:
                expected[key] = text
        if key not in expected:
            raise SvgValidationError(f"未知图解标签 {key or '(缺少ID)'}：只能使用 diagram_labels 内原文及 label-N 标识；不允许新增文字")
        if key in found:
            raise SvgValidationError(f"文本标识 {key} 重复，每个标题、要点、标签只允许一个 text")
        if _compact(text) != _compact(expected[key]):
            raise SvgValidationError(f"文本 {key} 与已确认内容不一致")
        found[key] = text
        ancestors = []
        current = element
        while current in parent_of:
            current = parent_of[current]
            ancestors.append(current)
        inherited = {}
        for ancestor in reversed(ancestors):
            inherited.update(ancestor.attrib)
        inherited.update(element.attrib)
        font = _number(inherited.get("font-size"), 28)
        if not 24 <= font <= 64:
            raise SvgValidationError(f"{key} 的字号必须为 24–64 像素")
        x, y = _number(element.get("x")), _number(element.get("y"))
        spans = list(element)
        lines = spans if spans else [element]
        for line in lines:
            if line is not element:
                x = _number(line.get("x"), x)
                y = _number(line.get("y"), y) + _number(line.get("dy"))
            line_font = _number(line.get("font-size"), font)
            if line_font < 24 or line_font > 64:
                raise SvgValidationError(f"{key} 存在过小/过大字号")
            chars = "".join(line.itertext())
            width = sum(1 if unicodedata.east_asian_width(c) in {"W", "F"} else .56 for c in chars) * line_font
            anchor = line.get("text-anchor", inherited.get("text-anchor", "start"))
            left = x - (width if anchor == "end" else width / 2 if anchor == "middle" else 0)
            if left < 28 or left + width > 1252 or y - line_font < 24 or y > 668:
                raise SvgValidationError(f"{key} 存在文字越界或换行不足")
            if _number(inherited.get("opacity"), 1) < .5 or inherited.get("fill") in {"none", "transparent"}:
                raise SvgValidationError(f"{key} 不可隐藏正文")
            text_boxes.append((key, left, y-line_font, width, line_font * 1.12))
        element.set("font-family", FONT_FAMILY)
    if not required.issubset(found):
        raise SvgValidationError("页面遗漏内容：" + "、".join(sorted(expected.keys() - found.keys())))
    for index, (key, x, y, w, h) in enumerate(text_boxes):
        for ox, oy, ow, oh in image_boxes:
            if min(x+w, ox+ow)-max(x, ox) > 5 and min(y+h, oy+oh)-max(y, oy) > 5:
                raise SvgValidationError(f"图片槽位遮挡正文：{key}")
        for other, ox, oy, ow, oh in text_boxes[:index]:
            if min(x+w, ox+ow)-max(x, ox) > 5 and min(y+h, oy+oh)-max(y, oy) > 5:
                raise SvgValidationError(f"文本区域重叠：{other} 与 {key}")
    root.set("font-family", FONT_FAMILY)
    root.set("lang", "zh-CN")
    # This label is application-owned, not generated teaching content.
    label = ET.SubElement(root, f"{{{SVG_NS}}}text", {
        "x": "1248", "y": "700", "font-size": "14", "text-anchor": "end",
        "font-family": FONT_FAMILY, "fill": "#687080", "id": "ai-disclosure",
    })
    label.text = "AI 生成内容 · 请教师核验后使用"
    return ET.tostring(root, encoding="unicode")


def without_disclosure(svg: str) -> str:
    root = ET.fromstring(svg)
    for child in list(root):
        if child.get("id") == "ai-disclosure":
            root.remove(child)
    return ET.tostring(root, encoding="unicode")

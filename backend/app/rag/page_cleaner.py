import math
import re
from collections import Counter
from dataclasses import dataclass


HEADER_RATIO = 0.12
FOOTER_RATIO = 0.10
_TERMINAL_PUNCTUATION = "。！？；：.!?;:」』】）\"]'"
_PAGE_NUMBER_RE = re.compile(
    r"^\s*(?:[-—–·•]\s*)?(?:第\s*)?(?:\d{1,4}|[ivxlcdm]{1,12})(?:\s*页)?(?:\s*[-—–·•])?\s*$",
    re.IGNORECASE,
)
_HEADING_RE = re.compile(
    r"^\s*(?:第[一二三四五六七八九十百零〇0-9]+[章节篇部]|"
    r"[一二三四五六七八九十百零〇]+、|学习要点|目录|前言|附录|参考文献)"
)


@dataclass
class CleanablePage:
    pdf_page: int
    raw_text: str
    text: str
    width: float | None
    height: float | None
    text_blocks: list[dict]


def _compact(value: str) -> str:
    return "".join((value or "").split())


def _repeat_key(value: str) -> str:
    compact = _compact(value).lower()
    compact = re.sub(r"\d+", "<n>", compact)
    compact = re.sub(r"[ivxlcdm]+", "<r>", compact)
    return compact


def _margin(block: dict, height: float | None) -> str | None:
    declared_region = block.get("region")
    if declared_region in {"header", "footer"}:
        return declared_region
    if not height:
        return None
    bbox = block.get("bbox") or []
    if len(bbox) != 4:
        return None
    top, bottom = float(bbox[1]), float(bbox[3])
    if bottom <= height * HEADER_RATIO:
        return "header"
    if top >= height * (1 - FOOTER_RATIO):
        return "footer"
    return None


def _join_lines(value: str) -> str:
    lines = [" ".join(line.split()).strip() for line in (value or "").splitlines() if line.strip()]
    if not lines:
        return ""
    output = lines[0]
    for line in lines[1:]:
        if not output:
            output = line
        elif output[-1].isascii() and output[-1].isalnum() and line[0].isascii() and line[0].isalnum():
            output += " " + line
        else:
            output += line
    return output


def render_clean_text(blocks: list[dict]) -> str:
    paragraphs: list[str] = []
    for block in blocks:
        if block.get("excluded"):
            continue
        text = _join_lines(str(block.get("text") or ""))
        if text:
            if paragraphs and block.get("line_break"):
                paragraphs[-1] += "\n" + text
            else:
                paragraphs.append(text)
    return "\n\n".join(paragraphs).strip()


def clean_document_pages(pages: list[CleanablePage]) -> list[CleanablePage]:
    """Classify page-edge noise while preserving every original text block."""
    candidates: list[tuple[int, str, str]] = []
    for page_index, page in enumerate(pages):
        for block in page.text_blocks:
            margin = _margin(block, page.height)
            key = _repeat_key(str(block.get("text") or ""))
            if margin and key:
                candidates.append((page_index, margin, key))

    counts = Counter((margin, key) for _, margin, key in candidates)
    required_repeats = max(3, math.ceil(len(pages) * 0.15))
    for page_index, page in enumerate(pages):
        normalized_blocks = []
        for index, source in enumerate(page.text_blocks):
            block = dict(source)
            block.setdefault("id", f"p{page.pdf_page}-b{index}")
            block.setdefault("excluded", False)
            block.setdefault("exclusion_reason", None)
            block.setdefault("manual_override", None)
            margin = _margin(block, page.height)
            text = str(block.get("text") or "")
            key = _repeat_key(text)
            if block.get("manual_override") == "include":
                block["excluded"] = False
                block["exclusion_reason"] = None
            elif block.get("manual_override") == "exclude":
                block["excluded"] = True
                block["exclusion_reason"] = "manual"
            elif margin and _PAGE_NUMBER_RE.fullmatch(_compact(text)):
                block["excluded"] = True
                block["exclusion_reason"] = "page_number"
            elif margin and key and counts[(margin, key)] >= required_repeats:
                block["excluded"] = True
                block["exclusion_reason"] = f"repeated_{margin}"
            elif (
                margin == "header"
                and page_index > 0
                and len(_compact(text)) <= 120
                and _HEADING_RE.match(text)
            ):
                # A chapter/section title repeated on every subsequent page is
                # page furniture, even when OCR varies its spacing or digits so
                # much that the repeated-key rule cannot match it.
                block["excluded"] = True
                block["exclusion_reason"] = "repeated_header"
            normalized_blocks.append(block)
        page.text_blocks = normalized_blocks
        if normalized_blocks:
            page.text = render_clean_text(normalized_blocks)
    return pages


def is_page_continuation(previous: str, following: str) -> bool:
    previous = previous.rstrip()
    following = following.lstrip()
    if not previous or not following:
        return False
    first_paragraph = re.split(r"\n\s*\n", following, maxsplit=1)[0].strip()
    if not first_paragraph or (len(first_paragraph) <= 80 and _HEADING_RE.match(first_paragraph)):
        return False
    return previous[-1] not in _TERMINAL_PUNCTUATION


def join_page_texts(page_texts: list[str]) -> str:
    output = ""
    for text in (item.strip() for item in page_texts if item and item.strip()):
        if not output:
            output = text
        elif is_page_continuation(output, text):
            output += text
        else:
            output += "\n\n" + text
    return output.strip()

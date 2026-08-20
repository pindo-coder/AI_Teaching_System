from io import BytesIO
from pathlib import Path
from dataclasses import dataclass
import re

from pypdf import PdfReader

from app.rag.page_cleaner import CleanablePage, clean_document_pages

try:
    import fitz
except ImportError:  # Production installs PyMuPDF; pypdf remains a compatible fallback.
    fitz = None


SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md", ".markdown"}


@dataclass
class ExtractedPage:
    pdf_page: int
    raw_text: str
    text: str
    width: float | None = None
    height: float | None = None
    text_blocks: list[dict] | None = None


def _fitz_pages(content: bytes) -> list[ExtractedPage]:
    document = fitz.open(stream=content, filetype="pdf")
    pages = []
    try:
        for page_number, page in enumerate(document, start=1):
            blocks = []
            for index, item in enumerate(page.get_text("blocks", sort=True)):
                if len(item) < 7 or int(item[6]) != 0:
                    continue
                text = str(item[4] or "").strip()
                if not text:
                    continue
                blocks.append({
                    "id": f"p{page_number}-b{index}", "text": text,
                    "bbox": [round(float(value), 2) for value in item[:4]],
                    "excluded": False, "exclusion_reason": None, "manual_override": None,
                })
            raw_text = "\n\n".join(str(block["text"]) for block in blocks).strip()
            pages.append(ExtractedPage(
                pdf_page=page_number, raw_text=raw_text, text=raw_text,
                width=float(page.rect.width), height=float(page.rect.height), text_blocks=blocks,
            ))
    finally:
        document.close()
    return pages


def _pypdf_pages(content: bytes) -> list[ExtractedPage]:
    reader = PdfReader(BytesIO(content))
    pages = []
    for page_number, page in enumerate(reader.pages, start=1):
        extracted = "\n".join(
            line.rstrip() for line in (page.extract_text() or "").splitlines() if line.strip()
        ).strip()
        height = float(page.mediabox.height)
        lines = [line.strip() for line in extracted.splitlines() if line.strip()]
        blocks = [{
            "id": f"p{page_number}-b{index}", "text": value,
            # pypdf does not provide reliable block geometry across OCR PDFs.
            # Region hints let the text-level cleaner apply safe batch rules.
            "region": (
                "header" if index == 0 else
                ("footer" if re.fullmatch(
                    r"\s*(?:[-—–·•]\s*)?(?:第\s*)?(?:\d{1,4}|[ivxlcdm]{1,12})(?:\s*页)?(?:\s*[-—–·•])?\s*",
                    value, re.IGNORECASE,
                ) else None)
            ),
            "line_break": index > 0,
            "bbox": None,
            "excluded": False, "exclusion_reason": None, "manual_override": None,
        } for index, value in enumerate(lines)]
        raw_text = extracted
        pages.append(ExtractedPage(
            pdf_page=page_number, raw_text=raw_text, text=raw_text,
            width=float(page.mediabox.width), height=height, text_blocks=blocks,
        ))
    return pages


def extract_pages(filename: str, content: bytes) -> list[ExtractedPage]:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError("仅支持 PDF、TXT、Markdown 文件")
    if suffix == ".pdf":
        pages = _fitz_pages(content) if fitz is not None else _pypdf_pages(content)
        if not any(page.text for page in pages):
            raise ValueError("未能从文件中提取文本；扫描版 PDF 暂不支持，请先进行 OCR")
        return clean_document_pages(pages)
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("gb18030")
    normalized = "\n".join(line.rstrip() for line in text.splitlines()).strip()
    if not normalized:
        raise ValueError("文件没有可提取的文本内容")
    return [ExtractedPage(pdf_page=1, raw_text=normalized, text=normalized, text_blocks=[])]


def extract_text(filename: str, content: bytes) -> str:
    return "\n\n".join(page.text for page in extract_pages(filename, content) if page.text).strip()

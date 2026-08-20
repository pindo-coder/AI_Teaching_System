from io import BytesIO
from pathlib import Path
from dataclasses import dataclass

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
        fragments = []

        def visit(text, _cm, tm, _font, font_size):
            value = str(text or "").strip()
            if value:
                x, y = float(tm[4]), float(tm[5])
                fragments.append((x, y, float(font_size or 0), value))

        page.extract_text(visitor_text=visit)
        height = float(page.mediabox.height)
        fragments.sort(key=lambda item: (-item[1], item[0]))
        blocks = [{
            "id": f"p{page_number}-b{index}", "text": value,
            "bbox": [round(x, 2), round(height - y - size, 2), round(x, 2), round(height - y, 2)],
            "excluded": False, "exclusion_reason": None, "manual_override": None,
        } for index, (x, y, size, value) in enumerate(fragments)]
        raw_text = "\n\n".join(str(block["text"]) for block in blocks).strip()
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

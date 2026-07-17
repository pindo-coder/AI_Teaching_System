from io import BytesIO
from pathlib import Path
from dataclasses import dataclass

from pypdf import PdfReader


SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md", ".markdown"}


@dataclass
class ExtractedPage:
    pdf_page: int
    text: str
    width: float | None = None
    height: float | None = None


def extract_pages(filename: str, content: bytes) -> list[ExtractedPage]:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError("仅支持 PDF、TXT、Markdown 文件")
    if suffix == ".pdf":
        reader = PdfReader(BytesIO(content))
        pages = []
        for index, page in enumerate(reader.pages, start=1):
            text = "\n".join(line.rstrip() for line in (page.extract_text() or "").splitlines()).strip()
            pages.append(ExtractedPage(pdf_page=index, text=text,
                                       width=float(page.mediabox.width), height=float(page.mediabox.height)))
        if not any(page.text for page in pages):
            raise ValueError("未能从文件中提取文本；扫描版 PDF 暂不支持，请先进行 OCR")
        return pages
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("gb18030")
    normalized = "\n".join(line.rstrip() for line in text.splitlines()).strip()
    if not normalized:
        raise ValueError("文件没有可提取的文本内容")
    return [ExtractedPage(pdf_page=1, text=normalized)]


def extract_text(filename: str, content: bytes) -> str:
    return "\n\n".join(page.text for page in extract_pages(filename, content) if page.text).strip()

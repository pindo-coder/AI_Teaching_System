from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import settings


def split_text(text: str) -> list[str]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.text_chunk_size,
        chunk_overlap=settings.text_chunk_overlap,
        separators=["\n\n", "\n", "。", "；", "，", " ", ""],
    )
    return [chunk.strip() for chunk in splitter.split_text(text) if chunk.strip()]


def split_pages(pages) -> list[dict[str, object]]:
    """页内切分，保留 PDF 页边界；不会把无关的相邻页面机械合并。"""
    output: list[dict[str, object]] = []
    for page in pages:
        for paragraph_index, chunk in enumerate(split_text(page.text), start=1):
            output.append({
                "content": chunk,
                "pdf_page_start": page.pdf_page,
                "pdf_page_end": page.pdf_page,
                "paragraph_index": paragraph_index,
                "start_anchor": chunk[:120],
                "end_anchor": chunk[-120:],
            })
    return output

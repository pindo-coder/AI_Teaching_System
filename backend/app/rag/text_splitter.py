from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import settings
from app.rag.page_cleaner import is_page_continuation


def split_text(text: str) -> list[str]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.text_chunk_size,
        chunk_overlap=settings.text_chunk_overlap,
        separators=["\n\n", "\n", "。", "；", "，", " ", ""],
    )
    return [chunk.strip() for chunk in splitter.split_text(text) if chunk.strip()]


def split_pages(pages) -> list[dict[str, object]]:
    """Split logical paragraphs and retain the physical page span of continuations."""
    paragraphs: list[dict[str, object]] = []
    for page in pages:
        parts = [item.strip() for item in str(page.text or "").split("\n\n") if item.strip()]
        for index, part in enumerate(parts):
            if index == 0 and paragraphs and is_page_continuation(str(paragraphs[-1]["content"]), part):
                paragraphs[-1]["content"] = str(paragraphs[-1]["content"]) + part
                paragraphs[-1]["pdf_page_end"] = page.pdf_page
            else:
                paragraphs.append({
                    "content": part,
                    "pdf_page_start": page.pdf_page,
                    "pdf_page_end": page.pdf_page,
                })

    # OCR PDFs often expose every visual line or text box as a separate
    # paragraph. Feeding those fragments directly into the Embedding service
    # produced almost one vector per line (9,000 vectors for a 367-page book).
    # Pack adjacent short fragments from the same physical page up to the
    # configured chunk size. Real long paragraphs and cross-page continuations
    # keep their original page spans and are still split by split_text below.
    packed: list[dict[str, object]] = []
    for paragraph in paragraphs:
        content = str(paragraph["content"])
        previous = packed[-1] if packed else None
        same_page_span = previous is not None and (
            previous["pdf_page_start"] == paragraph["pdf_page_start"]
            and previous["pdf_page_end"] == paragraph["pdf_page_end"]
        )
        combined_size = len(str(previous["content"])) + 2 + len(content) if previous else len(content)
        if same_page_span and combined_size <= settings.text_chunk_size:
            previous["content"] = str(previous["content"]) + "\n\n" + content
        else:
            packed.append(dict(paragraph))

    output: list[dict[str, object]] = []
    page_paragraph_indexes: dict[int, int] = {}
    for paragraph in packed:
        start_page = int(paragraph["pdf_page_start"])
        page_paragraph_indexes[start_page] = page_paragraph_indexes.get(start_page, 0) + 1
        for chunk in split_text(str(paragraph["content"])):
            output.append({
                "content": chunk,
                "pdf_page_start": start_page,
                "pdf_page_end": int(paragraph["pdf_page_end"]),
                "paragraph_index": page_paragraph_indexes[start_page],
                "start_anchor": chunk[:120],
                "end_anchor": chunk[-120:],
            })
    return output

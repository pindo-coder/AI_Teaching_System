from types import SimpleNamespace
from io import BytesIO

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.rag import document_loader
from app.rag.document_loader import extract_pages
from app.rag.page_cleaner import CleanablePage, clean_document_pages, join_page_texts
from app.rag.text_splitter import split_pages


def make_page(number: int, body: str) -> CleanablePage:
    blocks = [
        {"id": f"p{number}-header", "text": "第一节 全面建设社会主义现代化国家", "bbox": [80, 30, 500, 50]},
        {"id": f"p{number}-number", "text": str(136 + number), "bbox": [280, 55, 310, 75]},
        {"id": f"p{number}-body", "text": body, "bbox": [80, 150, 520, 650]},
    ]
    raw_text = "\n\n".join(item["text"] for item in blocks)
    return CleanablePage(
        pdf_page=number, raw_text=raw_text, text=raw_text,
        width=600, height=800, text_blocks=blocks,
    )


def test_clean_document_pages_removes_repeated_margins_but_keeps_body_numbers() -> None:
    pages = [make_page(index, f"正文包含现代化2035目标，第{index}页内容") for index in range(1, 5)]

    clean_document_pages(pages)

    assert all("第一节" not in page.text for page in pages)
    assert all(str(136 + page.pdf_page) not in page.text for page in pages)
    assert all("2035" in page.text for page in pages)
    assert pages[0].text_blocks[0]["exclusion_reason"] == "repeated_header"
    assert pages[0].text_blocks[1]["exclusion_reason"] == "page_number"


def test_manual_include_wins_over_automatic_header_detection() -> None:
    pages = [make_page(index, f"正文{index}") for index in range(1, 5)]
    pages[0].text_blocks[0]["manual_override"] = "include"

    clean_document_pages(pages)

    assert "第一节" in pages[0].text
    assert pages[0].text_blocks[0]["excluded"] is False
    assert "第一节" not in pages[1].text


def test_pages_without_layout_blocks_keep_their_text() -> None:
    page = CleanablePage(
        pdf_page=1, raw_text="Markdown 正文", text="Markdown 正文",
        width=None, height=None, text_blocks=[],
    )

    clean_document_pages([page])

    assert page.text == "Markdown 正文"


def test_cross_page_continuation_is_joined_and_keeps_page_span() -> None:
    pages = [
        SimpleNamespace(pdf_page=136, text="教育具有基础性、战略性支撑"),
        SimpleNamespace(pdf_page=137, text="作用，要坚持教育优先发展。\n\n第二段正文。"),
    ]

    assert join_page_texts([page.text for page in pages]).startswith("教育具有基础性、战略性支撑作用")
    chunks = split_pages(pages)
    assert chunks[0]["content"].startswith("教育具有基础性、战略性支撑作用")
    assert chunks[0]["pdf_page_start"] == 136
    assert chunks[0]["pdf_page_end"] == 137


def test_cross_page_heading_is_not_joined() -> None:
    text = join_page_texts(["上一节正文没有句号", "第二节 新的发展阶段\n\n本节正文。"])

    assert "没有句号\n\n第二节" in text


def test_ocr_short_blocks_are_packed_before_embedding() -> None:
    fragments = [f"第{index}行是 OCR 提取出的连续教材正文。" for index in range(120)]
    page = SimpleNamespace(pdf_page=1, text="\n\n".join(fragments))

    chunks = split_pages([page])

    assert len(chunks) < 10
    merged = "".join(str(chunk["content"]) for chunk in chunks)
    assert all(fragment in merged for fragment in fragments)
    assert all(chunk["pdf_page_start"] == 1 for chunk in chunks)
    assert all(chunk["pdf_page_end"] == 1 for chunk in chunks)


def _simple_pdf(page_lines: list[list[str]]) -> bytes:
    writer = PdfWriter()
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    font_ref = writer._add_object(font)
    for lines in page_lines:
        page = writer.add_blank_page(width=600, height=800)
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref}),
        })
        operations = ["BT /F1 12 Tf 50 750 Td"]
        for index, line in enumerate(lines):
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            if index:
                operations.append("0 -40 Td")
            operations.append(f"({escaped}) Tj")
        operations.append("ET")
        stream = DecodedStreamObject()
        stream.set_data(" ".join(operations).encode("latin-1"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pypdf_fallback_batch_removes_repeated_headers_and_page_numbers(monkeypatch) -> None:
    monkeypatch.setattr(document_loader, "fitz", None)
    content = _simple_pdf([
        ["Section 1 Modernization", str(136 + index), f"Body continuation page {index}"]
        for index in range(1, 5)
    ])

    pages = extract_pages("textbook.pdf", content)

    assert all("Section 1" not in page.text for page in pages)
    assert all(str(136 + page.pdf_page) not in page.text for page in pages)
    assert all("Body continuation" in page.text for page in pages)

from app.services.chapter_extractor import extract_chapters


def test_extracts_chapter_sections() -> None:
    chapters = extract_chapters("导论\n第一章 新时代\n本章正文\n第二章 伟大复兴\n本章正文")
    assert [title for title, _ in chapters] == ["导论与教材导读", "第一章 新时代", "第二章 伟大复兴"]
    assert "本章正文" in chapters[1][1]


def test_falls_back_to_full_text() -> None:
    chapters = extract_chapters("没有明显章节标题的教材内容")
    assert chapters == [("教材全文", "没有明显章节标题的教材内容")]

"""从教材文本中提取章节标题和正文，作为导入时的 MVP 自动专题生成器。"""

import re


HEADING_PATTERNS = (
    re.compile(r"^\s*(第\s*[一二三四五六七八九十百千万零〇0-9]+\s*[章节篇部部分].*)\s*$"),
    re.compile(r"^\s*(专题\s*[一二三四五六七八九十百千万零〇0-9]+.*)\s*$"),
    re.compile(r"^\s*(Chapter\s+[0-9]+\s*[:：].*)\s*$", re.IGNORECASE),
)


def extract_chapters(text: str) -> list[tuple[str, str]]:
    lines = [line.strip() for line in text.splitlines()]
    headings: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        if not line or len(line) > 160:
            continue
        for pattern in HEADING_PATTERNS:
            match = pattern.match(line)
            if match:
                headings.append((index, match.group(1).strip()))
                break
    if not headings:
        return [("教材全文", text.strip())]

    chapters: list[tuple[str, str]] = []
    if headings[0][0] > 0:
        preface = "\n".join(lines[: headings[0][0]]).strip()
        if preface:
            chapters.append(("导论与教材导读", preface))
    for position, (start, title) in enumerate(headings):
        end = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
        content = "\n".join(lines[start + 1 : end]).strip()
        chapters.append((title, content or "本专题内容已建立，后续可继续补充。"))
    return chapters

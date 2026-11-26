from __future__ import annotations

import re
from typing import TYPE_CHECKING, Iterable

from sqlalchemy import or_, select

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.models.agent_run import AgentRun
    from app.models.authority_discovery import PolicyChange


_EVIDENCE_REF_RE = re.compile(r"资料([1-9][0-9]*)")


def _resolve_evidence_index(ref: object, total: int) -> int | None:
    if not isinstance(ref, str):
        return None
    match = _EVIDENCE_REF_RE.fullmatch(ref)
    if match is None or len(match.group(1)) > len(str(total)):
        return None
    number = int(match.group(1))
    return number - 1 if number <= total else None


def _source_matches_change(source: dict, change: "PolicyChange") -> bool:
    # A source already carrying the change's NEW excerpt is the updated
    # evidence, even when it shares the old URL/document: not an old match.
    if isinstance(source, dict):
        excerpt = (source.get("excerpt") or "").strip()
        new_excerpt = (getattr(change, "new_excerpt", None) or "").strip()
        old_excerpt = (getattr(change, "old_excerpt", None) or "").strip()
        if excerpt and excerpt == new_excerpt and excerpt != old_excerpt:
            return False
    old_document_id = getattr(change, "old_document_id", None)
    source_document_id = source.get("document_id") if isinstance(source, dict) else None

    if old_document_id is not None and source_document_id is not None:
        return old_document_id == source_document_id

    old_source_url = getattr(change, "old_source_url", None)
    source_url = source.get("source_url") if isinstance(source, dict) else None
    if not old_source_url or not source_url:
        return False
    return old_source_url == source_url


def _change_in_scope(change: "PolicyChange", course_id, chapter_id) -> bool:
    if course_id is None or chapter_id is None:
        return False
    if getattr(change, "review_status", None) != "confirmed":
        return False
    if getattr(change, "kb_sync_status", None) != "synced":
        return False
    affected_courses = getattr(change, "affected_course_ids", None) or []
    affected_chapters = getattr(change, "affected_chapter_ids", None) or []
    return course_id in affected_courses and chapter_id in affected_chapters


def _page_sources(page: dict, evidence: list) -> Iterable[dict]:
    refs = page.get("evidence_refs")
    if not isinstance(refs, list):
        return
    for ref in refs:
        index = _resolve_evidence_index(ref, len(evidence))
        if index is not None:
            source = evidence[index]
            if isinstance(source, dict) and (source.get("document_id") or source.get("source_url")):
                yield source


def _page_impacts(page: dict, slide_index: int, sources: list[dict], changes: list) -> list[dict]:
    matched: list = []
    seen: set = set()
    for source in sources:
        for change in changes:
            change_id = getattr(change, "id", None)
            if change_id in seen:
                continue
            if _source_matches_change(source, change):
                matched.append(change)
                seen.add(change_id)

    return [
        {
            "slide_index": slide_index,
            "slide_number": slide_index + 1,
            "slide_title": page.get("title"),
            "change_id": getattr(change, "id", None),
            "old_excerpt": getattr(change, "old_excerpt", None),
            "new_excerpt": getattr(change, "new_excerpt", None),
            "old_source_url": getattr(change, "old_source_url", None),
            "new_source_url": getattr(change, "new_source_url", None),
        }
        for change in matched
    ]


def analyze_courseware_impact(
    run: "AgentRun", changes: Iterable["PolicyChange"]
) -> dict:
    output = getattr(run, "output_data", None) or {}
    bundle = output.get("artifact_bundle") if isinstance(output, dict) else None
    ppt = bundle.get("ppt") if isinstance(bundle, dict) else None
    slides = ppt.get("slides") if isinstance(ppt, dict) else None
    revision_id = ppt.get("revision_id") if isinstance(ppt, dict) else None

    if not isinstance(slides, list) or not slides:
        return {"revision_id": revision_id, "status": "unavailable", "impacts": []}

    evidence = getattr(run, "evidence_snapshot", None) or []
    if not isinstance(evidence, list):
        evidence = []
    course_id = getattr(run, "course_id", None)
    chapter_id = getattr(run, "chapter_id", None)

    scoped_changes = [
        change for change in changes if _change_in_scope(change, course_id, chapter_id)
    ]

    has_valid_ref = False
    impacts: list[dict] = []
    for slide_index, page in enumerate(slides):
        if not isinstance(page, dict):
            continue
        sources = list(_page_sources(page, evidence))
        if sources:
            has_valid_ref = True
            impacts.extend(_page_impacts(page, slide_index, sources, scoped_changes))

    if not has_valid_ref:
        return {"revision_id": revision_id, "status": "unavailable", "impacts": []}

    return {"revision_id": revision_id, "status": "ready", "impacts": impacts}


def load_courseware_impact_changes(db: "Session", run: "AgentRun") -> list["PolicyChange"]:
    """Load only confirmed, synced evidence that the run actually cites."""
    from app.models.authority_discovery import PolicyChange

    evidence = run.evidence_snapshot
    if not isinstance(evidence, list):
        return []
    document_ids = set()
    source_urls = set()
    for source in evidence:
        if not isinstance(source, dict):
            continue
        document_id = source.get("document_id")
        source_url = source.get("source_url")
        if type(document_id) is int and document_id > 0:
            document_ids.add(document_id)
        if isinstance(source_url, str) and source_url:
            source_urls.add(source_url)
    if not document_ids and not source_urls:
        return []

    return list(
        db.scalars(
            select(PolicyChange)
            .where(
                PolicyChange.review_status == "confirmed",
                PolicyChange.kb_sync_status == "synced",
                or_(
                    PolicyChange.old_document_id.in_(document_ids),
                    PolicyChange.old_source_url.in_(source_urls),
                ),
            )
            .order_by(PolicyChange.id.desc())
        ).all()
    )


def analyze_run_courseware_impact(db: "Session", run: "AgentRun") -> dict:
    return analyze_courseware_impact(run, load_courseware_impact_changes(db, run))


def _slide_page(run: "AgentRun", slide_index: int):
    output = getattr(run, "output_data", None) or {}
    bundle = output.get("artifact_bundle") if isinstance(output, dict) else None
    ppt = bundle.get("ppt") if isinstance(bundle, dict) else None
    slides = ppt.get("slides") if isinstance(ppt, dict) else None
    if not isinstance(slides, list) or not 0 <= slide_index < len(slides):
        return None
    return slides[slide_index]


def _slide_text(page) -> str:
    if not isinstance(page, dict):
        return ""
    parts = []
    if page.get("title"):
        parts.append(f"标题：{page['title']}")
    if page.get("takeaway"):
        parts.append(f"结论：{page['takeaway']}")
    bullets = page.get("bullets")
    if isinstance(bullets, list):
        parts.extend(f"要点：{item}" for item in bullets if isinstance(item, str) and item.strip())
    return "\n".join(parts)


def _offline_draft(impact: dict) -> str:
    return (
        "【离线演示】本稿为离线流程演示，不代表已完成课件修改，也未写入数据库或课件。\n"
        f"第 {impact.get('slide_number')} 页《{impact.get('slide_title') or '当前页'}》"
        "涉及一条已确认的资料变更。\n"
        f"原表述（待核验）：{impact.get('old_excerpt') or ''}\n"
        f"现表述（待核验）：{impact.get('new_excerpt') or ''}\n"
        "请教师对照服务器返回的来源链接和已核验原文逐条核对后，再自行修改课件。"
    )


_IMPACT_DRAFT_SYSTEM_PROMPT = """你是高校思政课备课助手，正在生成供教师核验的课件修改草案。
只能依据服务器提供的当前页可见文本和已核验的旧、新原文，不得补充外部事实。
不得编造政策名称、日期、数字、人物讲话、链接、引文或资料编号；来源链接与原文由服务器结构化返回。
输出中文纯文本草案，不要输出 JSON、Markdown 链接，也不要声称已经修改或发布课件。
草案仅供教师核验，必须提醒教师逐条核对原文后自行修改课件。"""

_IMPACT_DRAFT_USER_PROMPT = """当前页：第 {slide_number} 页《{slide_title}》
当前页可见文本：
{slide_text}

已核验的旧原文（课件当前依据）：
{old_excerpt}

已核验的新原文（更新后的依据）：
{new_excerpt}

请给出该页需要调整的内容草案，控制在 200 字以内，说明建议替换或补充的表述，并明确这是待教师核验的草稿。"""


def build_courseware_impact_draft(
    db: "Session",
    run: "AgentRun",
    impact: dict,
    *,
    user_id: int | None = None,
) -> str:
    from app.core.config import settings

    if settings.ai_mock_mode:
        return _offline_draft(impact)

    from langchain_core.prompts import ChatPromptTemplate

    from app.services.agent_service import _invoke_non_streaming_text
    from app.services.ai_operation_service import AiProviderConfigService, build_chat_model

    runtime = AiProviderConfigService.resolve(db)
    if not runtime.api_key:
        return _offline_draft(impact)

    page = _slide_page(run, int(impact.get("slide_index") or 0))
    variables = {
        "slide_number": str(impact.get("slide_number") or ""),
        "slide_title": str(impact.get("slide_title") or "当前页"),
        "slide_text": _slide_text(page) or "当前页没有可提取的可见文本。",
        "old_excerpt": str(impact.get("old_excerpt") or ""),
        "new_excerpt": str(impact.get("new_excerpt") or ""),
    }
    model, _ = build_chat_model(
        feature="courseware_impact_draft",
        db=db,
        user_id=user_id,
        temperature=0.2,
        timeout=60,
        max_tokens=1200,
        streaming=False,
    )
    prompt = ChatPromptTemplate.from_messages(
        [("system", _IMPACT_DRAFT_SYSTEM_PROMPT), ("human", _IMPACT_DRAFT_USER_PROMPT)]
    )
    return _invoke_non_streaming_text(prompt, model, variables).strip()


def draft_courseware_impact(
    db: "Session",
    run: "AgentRun",
    *,
    change_id: int,
    slide_index: int,
    expected_revision_id: str,
    user_id: int | None = None,
) -> dict:
    from fastapi import HTTPException

    result = analyze_run_courseware_impact(db, run)
    if result.get("status") == "unavailable":
        raise HTTPException(status_code=404, detail="当前课件没有可核验的资料依据")
    if result.get("revision_id") != expected_revision_id:
        raise HTTPException(status_code=409, detail="课件版本已变化，请刷新后重试")
    impact = next(
        (
            item
            for item in result.get("impacts") or []
            if item.get("change_id") == change_id and item.get("slide_index") == slide_index
        ),
        None,
    )
    if impact is None:
        raise HTTPException(status_code=404, detail="未找到该变更在当前课件页面中的影响")
    return {
        "record": result,
        "draft_text": build_courseware_impact_draft(db, run, impact, user_id=user_id),
        "needs_teacher_review": True,
    }

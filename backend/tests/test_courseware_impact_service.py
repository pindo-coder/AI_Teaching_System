from types import SimpleNamespace

from app.services.courseware_impact_service import analyze_courseware_impact


def _source(document_id=None, source_url=None):
    return {"document_id": document_id, "source_url": source_url}


def _change(**overrides):
    data = {
        "id": 1,
        "review_status": "confirmed",
        "kb_sync_status": "synced",
        "affected_course_ids": [10],
        "affected_chapter_ids": [100],
        "old_document_id": 501,
        "old_source_url": "https://old.example.com/policy",
        "old_excerpt": "通知自发布之日起3个工作日内反馈。",
        "new_excerpt": "通知自发布之日起5个工作日内反馈。",
        "new_source_url": "https://new.example.com/policy",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _run(slides, evidence, course_id=10, chapter_id=100, revision_id="rev-1"):
    return SimpleNamespace(
        course_id=course_id,
        chapter_id=chapter_id,
        evidence_snapshot=evidence,
        output_data={
            "artifact_bundle": {
                "ppt": {"revision_id": revision_id, "slides": slides}
            }
        },
    )


def test_hits_only_the_matching_slide_for_workday_change():
    slides = [
        {"title": "办理流程", "evidence_refs": ["资料1"]},
        {"title": "无关内容", "evidence_refs": ["资料2"]},
    ]
    evidence = [_source(document_id=501), _source(document_id=999)]
    run = _run(slides, evidence)

    result = analyze_courseware_impact(run, [_change()])

    assert result["status"] == "ready"
    assert result["revision_id"] == "rev-1"
    assert len(result["impacts"]) == 1
    impact = result["impacts"][0]
    assert impact["slide_index"] == 0
    assert impact["slide_number"] == 1
    assert impact["slide_title"] == "办理流程"
    assert impact["change_id"] == 1
    assert impact["old_excerpt"] == "通知自发布之日起3个工作日内反馈。"
    assert impact["new_excerpt"] == "通知自发布之日起5个工作日内反馈。"
    assert impact["old_source_url"] == "https://old.example.com/policy"
    assert impact["new_source_url"] == "https://new.example.com/policy"


def test_pending_change_is_ignored():
    slides = [{"title": "办理流程", "evidence_refs": ["资料1"]}]
    evidence = [_source(document_id=501)]
    run = _run(slides, evidence)

    result = analyze_courseware_impact(run, [_change(review_status="pending")])

    assert result["status"] == "ready"
    assert result["impacts"] == []


def test_unsynced_change_is_ignored():
    slides = [{"title": "办理流程", "evidence_refs": ["资料1"]}]
    evidence = [_source(document_id=501)]
    run = _run(slides, evidence)

    result = analyze_courseware_impact(run, [_change(kb_sync_status="pending")])

    assert result["status"] == "ready"
    assert result["impacts"] == []


def test_change_out_of_chapter_scope_is_ignored():
    slides = [{"title": "办理流程", "evidence_refs": ["资料1"]}]
    evidence = [_source(document_id=501)]
    run = _run(slides, evidence, chapter_id=200)

    result = analyze_courseware_impact(run, [_change(affected_chapter_ids=[100])])

    assert result["status"] == "ready"
    assert result["impacts"] == []


def test_legacy_ppt_without_evidence_refs_is_unavailable():
    slides = [{"title": "办理流程", "evidence_refs": []}]
    run = _run(slides, [_source(document_id=501)])

    result = analyze_courseware_impact(run, [_change()])

    assert result["status"] == "unavailable"
    assert result["revision_id"] == "rev-1"
    assert result["impacts"] == []


def test_invalid_evidence_reference_is_unavailable():
    slides = [{"title": "办理流程", "evidence_refs": ["资料999"]}]
    run = _run(slides, [_source(document_id=501)])

    result = analyze_courseware_impact(run, [_change()])

    assert result["status"] == "unavailable"
    assert result["impacts"] == []


def test_refs_without_a_verifiable_source_are_unavailable():
    slides = [
        {"title": "旧格式引用", "evidence_refs": 1},
        {"title": "缺少依据标识", "evidence_refs": ["资料1"]},
    ]
    run = _run(slides, [_source()])

    assert analyze_courseware_impact(run, [_change()])["status"] == "unavailable"


def test_missing_ppt_is_unavailable():
    run = SimpleNamespace(
        course_id=10,
        chapter_id=100,
        evidence_snapshot=[_source(document_id=501)],
        output_data={},
    )

    result = analyze_courseware_impact(run, [_change()])

    assert result["status"] == "unavailable"
    assert result["revision_id"] is None
    assert result["impacts"] == []


def test_matches_by_source_url_when_document_id_missing():
    slides = [{"title": "办理流程", "evidence_refs": ["资料1"]}]
    evidence = [_source(document_id=None, source_url="https://old.example.com/policy")]
    run = _run(slides, evidence)

    result = analyze_courseware_impact(
        run, [_change(old_document_id=None)]
    )

    assert result["status"] == "ready"
    assert len(result["impacts"]) == 1
    assert result["impacts"][0]["slide_number"] == 1


def test_deduplicates_same_change_on_same_slide():
    slides = [{"title": "办理流程", "evidence_refs": ["资料1", "资料2"]}]
    evidence = [_source(document_id=501), _source(document_id=501)]
    run = _run(slides, evidence)

    result = analyze_courseware_impact(run, [_change()])

    assert len(result["impacts"]) == 1

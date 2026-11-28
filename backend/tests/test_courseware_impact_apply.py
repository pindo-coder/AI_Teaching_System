from copy import deepcopy

from app.models.agent_run import AgentRun
from app.schemas.presentation import PptPage
from app.services import ppt_workflow_service as workflow
from app.services.ppt_native_service import PptNativeService
from app.services.ppt_svg_service import validate_svg
from tests.test_courseware_impact_api import _context, _headers

DESIGN = {"text": "162033", "background": "FFFFFF"}


def _page(title, bullet, ref="资料1"):
    return PptPage(layout="content", title=title, takeaway="按通知要求及时反馈", bullets=[bullet],
                   speaker_notes="讲稿", evidence_refs=[ref]).model_dump()


def _seed(db, run):
    pages = [_page("办理流程", "自发布之日起3个工作日内反馈"), _page("无关页", "其他内容")]
    for item in pages:
        item["svg"] = validate_svg(workflow.PptWorkflowService._fixture_svg(PptPage(**{
            k: v for k, v in item.items() if k in PptPage.model_fields}), DESIGN),
            PptPage(**{k: v for k, v in item.items() if k in PptPage.model_fields}))
    run.evidence_snapshot = [*run.evidence_snapshot, {
        "source_type": "policy", "source_title": "其他", "course_id": run.course_id,
        "chapter_id": run.chapter_id, "excerpt": "x", "source_url": "https://other.example.com"}]
    pages[1]["evidence_refs"] = ["资料2"]
    run.output_data = {
        "artifacts": {"ppt": {"storage_path": "old.pptx", "revision_id": "rev-current"}},
        "artifact_bundle": {"ppt": {
            "revision_id": "rev-current", "title": "课件", "pipeline_version": "ppt-master-svg-v2",
            "preferences": {"slide_count": 6, "include_interaction": False},
            "design": DESIGN, "slides": pages}}}
    run.current_step = 3
    db.commit()


def _body(change, **over):
    return {"change_id": change.id, "slide_index": 0, "expected_revision_id": "rev-current",
            "title": "办理流程", "takeaway": "按通知要求及时反馈",
            "bullets": ["自发布之日起5个工作日内反馈"], "confirmed": True, **over}


def _patch(monkeypatch):
    monkeypatch.setattr(workflow, "check_runtime", lambda: {})

    def export(self, data, evidence):
        data = deepcopy(data)
        data["revision_id"] = "rev-new"
        return {"kind": "ppt", "storage_path": "new.pptx", "revision_id": "rev-new"}, data
    monkeypatch.setattr(PptNativeService, "export", export)


def test_apply_creates_new_revision_and_keeps_other_page(client, db, monkeypatch):
    _patch(monkeypatch)
    teacher, _, run, change = _context(db)
    _seed(db, run)
    other_before = deepcopy(run.output_data["artifact_bundle"]["ppt"]["slides"][1])
    response = client.post(f"/api/v1/agent/runs/{run.id}/courseware-impact/apply",
                           headers=_headers(teacher), json=_body(change))
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    ppt = data["output_data"]["artifact_bundle"]["ppt"]
    assert ppt["revision_id"] == "rev-new"
    assert ppt["slides"][0]["bullets"] == ["自发布之日起5个工作日内反馈"]
    assert ppt["slides"][0]["evidence_refs"] == ["资料3"]  # old ref swapped for appended new source
    assert data["evidence_snapshot"][0]["source_url"] == "https://old.example.com/policy"
    assert data["evidence_snapshot"][2]["source_url"] == "https://new.example.com/policy"
    assert data["output_data"]["ppt_versions"][-1]["revision_id"] == "rev-current"
    db.expire_all()
    saved = db.get(AgentRun, run.id).output_data["artifact_bundle"]["ppt"]["slides"][1]
    assert saved == other_before


def test_apply_rejects_stale_revision_and_non_owner_and_unconfirmed(client, db, monkeypatch):
    _patch(monkeypatch)
    teacher, stranger, run, change = _context(db)
    _seed(db, run)
    url = f"/api/v1/agent/runs/{run.id}/courseware-impact/apply"
    assert client.post(url, headers=_headers(teacher),
                       json=_body(change, expected_revision_id="old")).status_code == 409
    assert client.post(url, headers=_headers(stranger), json=_body(change)).status_code == 403
    assert client.post(url, headers=_headers(teacher),
                       json=_body(change, confirmed=False)).status_code == 422
    db.expire_all()
    assert db.get(AgentRun, run.id).output_data["artifact_bundle"]["ppt"]["revision_id"] == "rev-current"


def test_same_url_update_appends_new_evidence_and_page_no_longer_hit(client, db, monkeypatch):
    _patch(monkeypatch)
    teacher, _, run, change = _context(db)
    change.new_source_url = change.old_source_url  # same address, no document_id anywhere
    db.commit()
    _seed(db, run)
    base = f"/api/v1/agent/runs/{run.id}/courseware-impact"
    assert [i["slide_index"] for i in client.get(base, headers=_headers(teacher)).json()["data"]["record"]["impacts"]] == [0]
    response = client.post(f"{base}/apply", headers=_headers(teacher), json=_body(change))
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    evidence = data["evidence_snapshot"]
    assert len(evidence) == 3 and evidence[0]["excerpt"] == "通知自发布之日起3个工作日内反馈。"
    assert evidence[2]["excerpt"] == "通知自发布之日起5个工作日内反馈。"
    ppt = data["output_data"]["artifact_bundle"]["ppt"]
    assert ppt["slides"][0]["evidence_refs"] == ["资料3"]
    assert ppt["slides"][1]["evidence_refs"] == ["资料2"]
    record = client.get(base, headers=_headers(teacher)).json()["data"]["record"]
    assert record["impacts"] == []

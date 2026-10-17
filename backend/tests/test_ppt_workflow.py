from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest
from sqlalchemy.dialects import mysql
from sqlalchemy import select
from fastapi import HTTPException

from app.core.config import settings
from app.models.agent_run import AgentRun, AgentStep
from app.schemas.agent import AgentArtifactRequest, PptPreferences, PptSlideRevisionRequest
from app.schemas.presentation import PptPage
from app.services.ppt_native_service import safe_artifact_path
from app.services.ppt_svg_service import SvgValidationError, validate_svg, without_disclosure
from app.services.ppt_workflow_service import PptWorkflowService
from app.services.agent_service import AgentService
from app.models.user import User


def page():
    return PptPage(layout="concept", title="全过程人民民主", takeaway="理解民主参与的不同形式",
        bullets=["结合社区协商分析具体实践"], speaker_notes="依据公开测试材料讲解。", evidence_refs=["资料1"])


@pytest.mark.parametrize('provided,expected', [
    (None, None), ('', None), ('   ', None),
    ('  民主专题公开课  ', '民主专题公开课'),
    ('民主专题公开课.PPTX', '民主专题公开课'),
    ('民主专题\n公开课', '民主专题 公开课'),
    ('课' * 60, '课' * 60),
])
def test_custom_ppt_title_is_optional_and_normalized(provided, expected):
    assert PptPreferences(title=provided).title == expected


@pytest.mark.parametrize('provided', ['课' * 61, '标题\x00', '标题[资料1]', 42])
def test_custom_ppt_title_rejects_invalid_or_overlong_names(provided):
    with pytest.raises(ValueError):
        PptPreferences(title=provided)


def test_custom_title_controls_cover_and_deck_name_without_changing_style(monkeypatch):
    service = PptWorkflowService(None, None, 1)
    variables = {'chapter_title': '全过程人民民主', 'course_name': '思政', 'outline_json': '{}', 'image_budget': '0'}
    preferences = PptPreferences(title='全过程人民民主公开课', slide_count=6)
    data = service._plan(variables, [{}], preferences)
    assert data['title'] == data['slides'][0]['title'] == preferences.title
    assert data['design']['name'] != preferences.title

    # Validate the real planner boundary even if a provider returns its own name.
    data['title'] = data['slides'][0]['title'] = '模型自行命名'
    data['design'].update(topic_keywords=['全过程人民民主'], visual_motif='社区围坐协商', image_style='暖色教学插图')
    for item in data['slides']:
        item['visual_brief'] = {'kind': 'none', 'purpose': '通过本页文字理解教学概念', 'content_anchors': [item['takeaway']]}
    others = [PptPage.model_validate(item).model_dump() for item in data['slides'][1:]]
    monkeypatch.setattr(settings, 'ai_mock_mode', False)
    captured = []
    def provider(system, payload, **kwargs):
        captured.append(payload['preferences']['title'])
        return json.dumps(data)
    monkeypatch.setattr(service, '_call', provider)
    result = service._plan(variables, [{}], preferences)
    assert captured == [preferences.title]
    assert result['title'] == result['slides'][0]['title'] == preferences.title
    assert result['slides'][1:] == others
    assert result['design']['name'] == data['design']['name']


def svg():
    return PptWorkflowService._fixture_svg(page(), {"text": "162033", "background": "FFFFFF"})


def test_svg_complete_native_text_contract():
    value = validate_svg(svg(), page())
    assert "ai-disclosure" in value
    assert "Noto Sans CJK SC" in value
    assert "ai-disclosure" not in without_disclosure(value)


def test_svg_discards_inert_comments_without_allowing_declarations():
    from app.services.ppt_svg_service import bind_plan_text
    commented = svg().replace("</svg>", "<!-- 标题与配图位置 --> </svg>")
    result = validate_svg(bind_plan_text(commented, page()), page())
    assert "<!--" not in result
    with pytest.raises(SvgValidationError):
        validate_svg(commented.replace("</svg>", '<!DOCTYPE svg></svg>'), page())
    with pytest.raises(SvgValidationError):
        validate_svg(commented.replace("</svg>", '<!-- invalid -- comment --></svg>'), page())


def test_svg_accepts_only_derived_numeric_labels():
    label = '<text id="num-0" x="1100" y="610" font-size="24">01</text>'
    validate_svg(svg().replace("</svg>", label + "</svg>"), page())
    with pytest.raises(SvgValidationError):
        validate_svg(svg().replace("</svg>", label.replace(">01<", ">99<") + "</svg>"), page())


@pytest.mark.parametrize("identifier", ['id="step-0"', 'id="node-0"', ''])
def test_only_grounded_diagram_labels_are_normalized(identifier):
    from app.services.ppt_svg_service import bind_plan_text
    content = page().model_copy(update={"diagram_labels": ["社区协商"]})
    raw = svg().replace("</svg>", f'<text {identifier} x="1000" y="500" font-size="26">社区协商</text></svg>')
    result = validate_svg(bind_plan_text(raw, content), content)
    assert 'id="label-0"' in result
    with pytest.raises(SvgValidationError, match="未知图解标签"):
        validate_svg(bind_plan_text(raw.replace("社区协商</text>", "未经确认的观点</text>"), content), content)


def test_diagram_labels_cannot_add_or_duplicate_claims():
    from pydantic import ValidationError
    data = page().model_dump()
    with pytest.raises(ValidationError, match="逐字来自"):
        PptPage.model_validate({**data, "diagram_labels": ["没有依据的标签"]})
    with pytest.raises(ValidationError, match="不能重复"):
        PptPage.model_validate({**data, "diagram_labels": ["社区协商", "社区协商"]})


def test_authoritative_copy_is_bound_without_cutting():
    from app.services.ppt_svg_service import bind_plan_text
    changed = svg().replace("结合社区协商分析具体实践", "模型擅自扩写的正文")
    fixed = bind_plan_text(changed, page())
    assert "模型擅自扩写" not in fixed
    assert "结合社区协商分析具体实践" in fixed
    validate_svg(fixed, page())


def test_pinned_skill_is_present_and_actual_baseline_is_loaded():
    from app.services.ppt_skill_service import skill_contract
    metadata, baseline = skill_contract()
    assert metadata["name"] == "ppt-master"
    assert metadata["commit"] == "8070d3df1f6f54b5fb60a9ae66e79c664f050212"
    assert "Shared Aesthetic Baseline" in baseline
    assert "Containers" in baseline


def test_ppt_call_collects_stream_before_parsing_and_closes_it(monkeypatch):
    from types import SimpleNamespace
    import app.services.ppt_workflow_service as workflow_module
    closed = []
    class Model:
        def stream(self, messages):
            try:
                for value in ['<thi', 'nk>private</think>', '{"title":', '"主题"}']:
                    yield SimpleNamespace(content=value)
            finally:
                closed.append(True)
    monkeypatch.setattr(workflow_module, "build_chat_model",
        lambda **kwargs: (Model(), SimpleNamespace(streaming_enabled=True)))
    result = PptWorkflowService(None, None, 1)._call("test", {}, feature="ppt_plan")
    assert result == '{"title":"主题"}'
    assert closed == [True]


def test_topic_theme_and_requested_image_budget_are_validated(monkeypatch):
    service = PptWorkflowService(None, None, 1)
    variables = {"chapter_title": "全过程人民民主", "course_name": "思政", "outline_json": "{}", "image_budget": "2"}
    preferences = PptPreferences(slide_count=6, include_visuals=True)
    fixture = service._plan(variables, [{}], preferences)
    fixture["design"].update(topic_keywords=["全过程人民民主", "协商民主", "有效参与"],
        visual_motif="围坐协商与意见汇聚", image_style="暖色纪实教学插画")
    fixture["slides"][2]["visual_prompt"] = "大学生与社区居民围坐交流"
    fixture["slides"][3]["visual_prompt"] = "社区公共空间共同讨论方案"
    for i, item in enumerate(fixture["slides"]):
        item["visual_brief"] = {"kind": "illustration" if item.get("visual_prompt") else "none",
            "purpose": "通过本页文字帮助理解概念", "content_anchors": [item["takeaway"]],
            "scene_family": f"场景{i}", "key_elements": ["居民", "记录本"], "difference": f"本页使用独立场景{i}"}
    monkeypatch.setattr(settings, "ai_mock_mode", False)
    monkeypatch.setattr(service, "_call", lambda *args, **kwargs: json.dumps(fixture))
    result = service._plan(variables, [{}], preferences)
    assert result["design"]["visual_motif"] == "围坐协商与意见汇聚"
    fixture["slides"][3]["visual_prompt"] = ""
    fixture["slides"][3]["visual_brief"]["kind"] = "none"
    assert len(service._plan(variables, [{}], preferences)["slides"]) == 6  # budget is a ceiling, not a quota
    fixture["slides"][2]["visual_brief"] = None
    with pytest.raises(RuntimeError, match="教学意图"):
        service._plan(variables, [{}], preferences)


def test_image_slot_cannot_cover_authoritative_text():
    overlap = '<image id="visual-asset" x="40" y="250" width="600" height="160"/>'
    with pytest.raises(SvgValidationError, match="遮挡正文"):
        validate_svg(svg().replace("</svg>", overlap+"</svg>"), page(), include_visual=True)


@pytest.mark.parametrize("frame", ["roundRect", "circle"])
def test_generated_picture_is_embedded_in_editable_pptx(tmp_path, monkeypatch, frame):
    from PIL import Image
    from zipfile import ZipFile
    from app.services.ppt_native_service import PptNativeService
    monkeypatch.setattr(settings, "generated_artifact_directory", str(tmp_path))
    image = tmp_path / "illustration.png"
    Image.new("RGB", (640, 360), "#C76B3C").save(image)
    service = PptWorkflowService(None, None, 42)
    data = service._plan({"chapter_title": "全过程人民民主", "course_name": "思政", "outline_json": "{}"}, [{}],
                         PptPreferences(title="民主专题公开课" if frame == "roundRect" else None, slide_count=6))
    data["design"]["image_frame_shape"] = frame
    for item in data["slides"]:
        item["svg"] = validate_svg(service._fixture_svg(PptPage.model_validate(item), data["design"]), PptPage.model_validate(item))
    item = data["slides"][2]
    width = 260 if frame == "circle" else 380
    raw = without_disclosure(item["svg"]).replace("</svg>", f'<image id="visual-asset" x="800" y="270" width="{width}" height="260"/></svg>')
    content = PptPage.model_validate({key: value for key, value in item.items() if key in PptPage.model_fields})
    item["svg"] = validate_svg(raw, content, include_visual=True)
    item["visual_asset"] = {"storage_path": "illustration.png", "media_type": "image/png", "model": "unit-test"}
    artifact, rendered = PptNativeService(42).export(data, [{}])
    if frame == "roundRect":
        assert artifact['title'] == rendered['title'] == rendered['slides'][0]['title'] == '民主专题公开课'
        assert artifact['file_name'] == '民主专题公开课.pptx'
    with ZipFile(tmp_path / artifact["storage_path"]) as package:
        assert b"p:pic" in package.read("ppt/slides/slide3.xml")
        geometry = "ellipse" if frame == "circle" else frame
        assert f'prst="{geometry}"'.encode() in package.read("ppt/slides/slide3.xml")
        from xml.etree import ElementTree as ET
        namespaces = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main", "a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
        slide_xml = ET.fromstring(package.read("ppt/slides/slide3.xml"))
        crop = slide_xml.find(".//p:pic/p:blipFill/a:srcRect", namespaces)
        assert crop is not None and any(int(value) > 0 for value in crop.attrib.values())
        assert any(name.startswith("ppt/media/") for name in package.namelist())
    assert rendered["slides"][2]["preview_path"]


@pytest.mark.parametrize("bad", [
    lambda s: s.replace("</svg>", '<script>alert(1)</script></svg>'),
    lambda s: s.replace("<svg ", '<svg onload="attack()" '),
    lambda s: '<!DOCTYPE svg [<!ENTITY x "attack">]>' + s,
    lambda s: s.replace("</svg>", '<image href="http://127.0.0.1/private" /></svg>'),
    lambda s: s.replace("结合社区协商分析具体实践", "删除了正文"),
    lambda s: s.replace('y="310"', 'y="210"'),
    lambda s: s.replace('y="310"', 'y="710"'),
    lambda s: s.replace('x="64"', 'x="NaN"'),
    lambda s: s.replace('font-size="26"', 'font-size="8"'),
    lambda s: s.replace('<text id="bullet-0"', '<text opacity="0" id="bullet-0"'),
])
def test_svg_rejects_unsafe_incomplete_or_unreadable_page(bad):
    with pytest.raises(SvgValidationError):
        validate_svg(bad(svg()), page())


def test_page_repair_is_bounded_and_does_not_pad_or_truncate(monkeypatch):
    monkeypatch.setattr(settings, "ai_mock_mode", False)
    service = PptWorkflowService(None, None, 1)
    calls = []
    def respond(*args, **kwargs):
        calls.append(1)
        return svg().replace('id="bullet-0"', 'id="lost-content"')
    monkeypatch.setattr(service, "_call", respond)
    with pytest.raises(RuntimeError, match="第 1 页"):
        service._design_page(page().model_dump(), {}, PptPreferences(), 0, [page().model_dump()])
    assert len(calls) == settings.ppt_page_repair_attempts + 1


def test_plan_rejects_wrong_count_and_fabricated_citation(monkeypatch):
    service = PptWorkflowService(None, None, 1)
    variables = {"chapter_title": "民主", "course_name": "思政", "outline_json": "{}"}
    fixture = service._plan(variables, [{}], PptPreferences(slide_count=6))
    fixture["slides"][2]["evidence_refs"] = ["资料999"]
    monkeypatch.setattr(settings, "ai_mock_mode", False)
    monkeypatch.setattr(service, "_call", lambda *args, **kwargs: json.dumps(fixture))
    with pytest.raises(RuntimeError, match="无效资料编号"):
        service._plan(variables, [{}], PptPreferences(slide_count=6))
    fixture["slides"].pop()
    with pytest.raises(RuntimeError):
        service._plan(variables, [{}], PptPreferences(slide_count=6))


def test_visual_revision_preserves_content_and_other_pages(monkeypatch):
    from app.services.ppt_native_service import PptNativeService
    pages = [page().model_dump() for _ in range(6)]
    for item in pages:
        item["svg"] = validate_svg(svg(), page())
    original = {"title": "测试", "pipeline_version": "ppt-master-svg-v2", "preferences": PptPreferences(slide_count=6).model_dump(),
        "design": {"text": "162033", "background": "FFFFFF"}, "slides": pages}
    before = deepcopy(original)
    monkeypatch.setattr(PptNativeService, "export", lambda self, data, evidence: ({"kind": "ppt"}, data))
    _, revised = PptWorkflowService(None, None, 1).revise(original, 2,
        PptSlideRevisionRequest(instruction="保留内容，增加留白", mode="design"), [{}])
    assert original == before
    for index in range(6):
        if index != 2:
            assert revised["slides"][index] == original["slides"][index]
    assert {k: v for k, v in revised["slides"][2].items() if k != "svg"} == {k: v for k, v in pages[2].items() if k != "svg"}


def test_artifact_path_rejects_traversal(tmp_path, monkeypatch):
    root = tmp_path / "private"
    root.mkdir()
    external = tmp_path / "outside.png"
    external.write_bytes(b"test")
    monkeypatch.setattr(settings, "generated_artifact_directory", str(root))
    with pytest.raises(FileNotFoundError):
        safe_artifact_path("../outside.png")


def test_revision_json_predicate_compiles_for_mysql():
    expression = AgentRun.output_data["artifact_bundle"]["ppt"]["revision_id"].as_string() == "revision"
    sql = str(select(AgentRun.id).where(expression).compile(dialect=mysql.dialect()))
    assert "JSON_EXTRACT" in sql


def _owned_run(db):
    user = User(username="ppt-version-owner", password_hash="test-only", role="teacher", approval_status="approved")
    db.add(user)
    db.flush()
    run = AgentRun(created_by=user.id, agent_type="teacher_lesson_prep", status="completed", current_step=3,
        input_data={}, evidence_snapshot=[], output_data={"artifacts": {"ppt": {"storage_path": "current.pptx"}},
            "artifact_bundle": {"ppt": {"title": "当前课件", "slides": [page().model_dump()]}}})
    db.add(run)
    db.commit()
    return user, run


@pytest.mark.parametrize('started,finished', [
    ('2026-10-17T10:44:28.039797', '2026-10-17T10:52:20.240603'),
    ('2026-10-17T10:44:28+08:00', '2026-10-17T10:52:20+08:00'),
    ('2026-10-17T02:44:28Z', None),
])
def test_attempt_protocol_timestamps_have_offsets_without_rewriting_history(db, started, finished):
    _, run = _owned_run(db)
    run.output_data = {**run.output_data, 'artifact_attempt': {
        'id': 'clock-test', 'status': 'running', 'started_time': started, 'finished_time': finished,
    }}
    db.commit()
    before = deepcopy(run.output_data)
    result = AgentService.serialize(db, run).output_data['artifact_attempt']
    for key, original in [('started_time', started), ('finished_time', finished)]:
        if original is None:
            assert result[key] is None
            continue
        parsed = datetime.fromisoformat(original.replace('Z', '+00:00'))
        expected = parsed.astimezone() if parsed.tzinfo is None else parsed
        public = datetime.fromisoformat(result[key])
        assert public.tzinfo is not None and public == expected
    db.refresh(run)
    assert run.output_data == before


def test_new_artifact_attempt_stores_explicit_time_offset(db):
    user, run = _owned_run(db)
    run.output_data = {**run.output_data, 'outline': {'title': '计时协议测试'}}
    db.add(AgentStep(run_id=run.id, step_key='generate_artifacts', title='生成成果',
                     step_order=3, status='pending', input_data={}, output_data={}))
    db.commit()
    AgentService(db, user).request_artifacts(run.id, AgentArtifactRequest(output_types=['lesson_plan']))
    db.refresh(run)
    stored = datetime.fromisoformat(run.output_data['artifact_attempt']['started_time'])
    assert stored.tzinfo is not None
    assert abs((datetime.now(timezone.utc) - stored).total_seconds()) < 5


def test_stale_update_cannot_overwrite_current_artifact(db):
    user, run = _owned_run(db)
    run.output_data = {"artifacts": {"ppt": {"storage_path": "stale-new.pptx"}}}
    with pytest.raises(HTTPException) as error:
        AgentService(db, user)._commit_artifact_mutation(run, "not-the-current-version.pptx")
    assert error.value.status_code == 409
    db.refresh(run)
    assert run.output_data["artifacts"]["ppt"]["storage_path"] == "current.pptx"


@pytest.mark.parametrize("artifact,status", [({}, 409), ({"storage_path": "missing.pptx"}, 404)])
def test_unrestorable_version_keeps_current_result(db, artifact, status):
    user, run = _owned_run(db)
    run.output_data = {**run.output_data, "ppt_versions": [{"version_id": "previous", "preview": {"title": "旧课件"}, "artifact": artifact}]}
    db.commit()
    with pytest.raises(HTTPException) as error:
        AgentService(db, user).restore_ppt_version(run.id, "previous")
    assert error.value.status_code == status
    db.refresh(run)
    assert run.output_data["artifact_bundle"]["ppt"]["title"] == "当前课件"


def _versioned_run(db):
    user, run = _owned_run(db)
    root = Path(settings.generated_artifact_directory)
    root.mkdir(parents=True, exist_ok=True)
    for name, data in {"current.pptx": b"current deck", "old.pptx": b"old deck", "old.png": b"old page"}.items():
        (root / name).write_bytes(data)
    output = deepcopy(run.output_data)
    output["artifact_bundle"]["ppt"]["revision_id"] = "current-revision"
    output["ppt_versions"] = [{
        "version_id": "old", "created_time": "2026-10-16T12:00:00+08:00", "reason": "修改第 1 页前",
        "slide_count": 1, "title": "历史课件", "design_name": "民主协商",
        "artifact": {"storage_path": "old.pptx", "file_name": "历史课件.pptx", "kind": "ppt",
                     "generated_time": "2026-10-15T12:00:00+08:00"},
        "preview": {"title": "历史课件", "revision_id": "old-revision", "slides": [
            {**page().model_dump(), "preview_path": "old.png", "svg": "private SVG",
             "visual_asset": {"storage_path": "private.png", "prompt": "教师可编辑的画面描述"}},
        ]},
    }]
    run.output_data = output
    db.commit()
    return user, run, root


def test_history_detail_preview_download_are_read_only_and_sanitized(db):
    user, run, root = _versioned_run(db)
    before, updated_time = deepcopy(run.output_data), run.updated_time
    service = AgentService(db, user)
    detail = service.ppt_version(run.id, "old")
    assert detail["restorable"] and not detail["is_current"]
    assert detail["ppt"]["revision_id"] == "old-revision"
    assert detail["generated_time"] == "2026-10-15T12:00:00+08:00"
    assert detail["ppt"]["slides"][0]["preview_available"]
    serialized = json.dumps(detail)
    assert "storage_path" not in serialized and "preview_path" not in serialized and "private SVG" not in serialized
    assert service.ppt_preview(run.id, 0, "old") == root / "old.png"
    path, artifact = service.artifact_download(run.id, "ppt", "old")
    assert path.read_bytes() == b"old deck" and artifact["file_name"] == "历史课件.pptx"
    db.refresh(run)
    assert run.output_data == before and run.updated_time == updated_time


def test_history_restore_switches_file_and_content_and_can_switch_back(db):
    user, run, _ = _versioned_run(db)
    service = AgentService(db, user)
    result = service.restore_ppt_version(run.id, "old", "current-revision")
    assert result.output_data["artifact_bundle"]["ppt"]["revision_id"] == "old-revision"
    assert run.output_data["artifacts"]["ppt"]["storage_path"] == "old.pptx"
    saved = next(v for v in run.output_data["ppt_versions"] if v["artifact"]["storage_path"] == "current.pptx")
    again = service.restore_ppt_version(run.id, saved["version_id"], "old-revision")
    assert again.output_data["artifact_bundle"]["ppt"]["revision_id"] == "current-revision"
    assert run.output_data["artifacts"]["ppt"]["storage_path"] == "current.pptx"


def test_history_restore_rejects_stale_expected_revision_without_changes(db):
    user, run, _ = _versioned_run(db)
    before = deepcopy(run.output_data)
    with pytest.raises(HTTPException) as error:
        AgentService(db, user).restore_ppt_version(run.id, "old", "stale-revision")
    assert error.value.status_code == 409
    db.refresh(run)
    assert run.output_data == before


def test_current_preview_and_download_reject_wrong_revision(db):
    user, run, _ = _versioned_run(db)
    service = AgentService(db, user)
    for request in (
        lambda: service.ppt_preview(run.id, 0, expected_revision="stale"),
        lambda: service.artifact_download(run.id, "ppt", expected_revision="stale"),
    ):
        with pytest.raises(HTTPException) as error:
            request()
        assert error.value.status_code == 409


def test_version_list_deduplicates_files_and_reports_missing_snapshots(db):
    user, run, _ = _versioned_run(db)
    versions = deepcopy(run.output_data["ppt_versions"])
    duplicate = {**deepcopy(versions[0]), "version_id": "duplicate"}
    current = {**deepcopy(versions[0]), "version_id": "current", "artifact": {"storage_path": "current.pptx"}}
    missing = {**deepcopy(versions[0]), "version_id": "missing", "artifact": {"storage_path": "missing.pptx"}}
    content = {**deepcopy(versions[0]), "version_id": "content-only", "artifact": {}}
    run.output_data = {**run.output_data, "ppt_versions": [*versions, duplicate, current, missing, content]}
    db.commit()
    listed = AgentService.serialize(db, run).output_data["ppt_versions"]
    assert [item["version_id"] for item in listed] == ["duplicate", "current", "missing", "content-only"]
    assert listed[1]["is_current"]
    assert not listed[2]["restorable"] and "不存在" in listed[2]["unavailable_reason"]
    assert not listed[3]["restorable"] and "快照" in listed[3]["unavailable_reason"]
    assert len(run.output_data["ppt_versions"]) == 5  # Read view never rewrites stored history.
    assert AgentService(db, user).ppt_version(run.id, "content-only")["ppt"]["title"] == "历史课件"


def test_repeated_restore_is_noop_and_archive_preserves_unique_revisions(db):
    user, run, _ = _versioned_run(db)
    service = AgentService(db, user)
    service.restore_ppt_version(run.id, "old")
    before = deepcopy(run.output_data)
    service.restore_ppt_version(run.id, "old", "old-revision")
    assert run.output_data == before
    AgentService._archive_ppt_version(run, "切换前自动保存")
    paths = [v["artifact"]["storage_path"] for v in run.output_data["ppt_versions"]]
    assert len(paths) == len(set(paths))


@pytest.mark.parametrize("route", [
    "ppt/versions/old", "ppt/slides/0/preview?version_id=old", "artifacts/ppt/download?version_id=old",
])
def test_history_endpoints_reject_other_teacher(client, db, route):
    from app.core.security import create_access_token
    _, run, _ = _versioned_run(db)
    other = User(username="not-the-owner", password_hash="test-only", role="teacher", approval_status="approved")
    db.add(other)
    db.commit()
    response = client.get(f"/api/v1/agent/runs/{run.id}/{route}",
                          headers={"Authorization": f"Bearer {create_access_token(str(other.id))}"})
    assert response.status_code == 403


def test_history_http_selection_and_download_use_requested_snapshot(client, db):
    from app.core.security import create_access_token
    user, run, _ = _versioned_run(db)
    headers = {"Authorization": f"Bearer {create_access_token(str(user.id))}"}
    base = f"/api/v1/agent/runs/{run.id}"
    assert client.get(base + "/ppt/versions/old", headers=headers).json()["data"]["ppt"]["title"] == "历史课件"
    assert client.get(base + "/ppt/slides/0/preview?version_id=old", headers=headers).content == b"old page"
    assert client.get(base + "/artifacts/ppt/download?version_id=old", headers=headers).content == b"old deck"
    conflict = client.post(base + "/ppt/versions/restore", headers=headers,
                           json={"version_id": "old", "expected_revision": "stale"})
    assert conflict.status_code == 409
    assert client.get(base, headers=headers).json()["data"]["output_data"]["artifact_bundle"]["ppt"]["revision_id"] == "current-revision"
    restored = client.post(base + "/ppt/versions/restore", headers=headers,
                           json={"version_id": "old", "expected_revision": "current-revision"})
    assert restored.status_code == 200
    output = restored.json()["data"]["output_data"]
    assert output["artifact_bundle"]["ppt"]["revision_id"] == "old-revision"
    assert client.get(base + "/artifacts/ppt/download?expected_revision=old-revision", headers=headers).content == b"old deck"
    original = next(item for item in output["ppt_versions"] if item["revision_id"] == "current-revision")
    switched_back = client.post(base + "/ppt/versions/restore", headers=headers,
                                json={"version_id": original["version_id"], "expected_revision": "old-revision"})
    assert switched_back.status_code == 200
    assert switched_back.json()["data"]["output_data"]["artifact_bundle"]["ppt"]["revision_id"] == "current-revision"


def test_cancel_at_page_boundary_releases_presentation_gate():
    from app.services.ppt_workflow_service import _PPT_JOB_GATE, PptWorkflowCancelled
    def cancelled(*args):
        raise PptWorkflowCancelled("test cancellation")
    workflow = PptWorkflowService(None, None, 1, progress=cancelled)
    with pytest.raises(PptWorkflowCancelled):
        workflow.generate({"outline_json": "{}", "course_name": "思政", "chapter_title": "民主", "ppt_preferences": '{"slide_count":6}'}, [{}])
    assert _PPT_JOB_GATE.acquire(blocking=False)
    _PPT_JOB_GATE.release()


def test_failed_page_resume_reuses_only_matching_run_and_inputs(tmp_path, monkeypatch):
    from app.services.ppt_native_service import PptNativeService
    monkeypatch.setattr(settings, "generated_artifact_directory", str(tmp_path))
    monkeypatch.setattr(PptNativeService, "export", lambda self, data, evidence: ({"kind": "ppt"}, data))
    variables = {"outline_json": "{}", "course_name": "思政", "chapter_title": "民主", "ppt_preferences": '{"slide_count":6,"include_visuals":false}'}
    designed = []
    original = PptWorkflowService._design_page
    def fail_once(self, content, design, preferences, index, roster, **kwargs):
        designed.append(index)
        if index == 3:
            raise RuntimeError("page failed")
        return original(self, content, design, preferences, index, roster, **kwargs)
    monkeypatch.setattr(PptWorkflowService, "_design_page", fail_once)
    with pytest.raises(RuntimeError, match="page failed"):
        PptWorkflowService(None, 1, 42).generate(variables, [{}])
    designed.clear()
    def record(self, content, design, preferences, index, roster, **kwargs):
        designed.append(index)
        return original(self, content, design, preferences, index, roster, **kwargs)
    monkeypatch.setattr(PptWorkflowService, "_design_page", record)
    artifact, data = PptWorkflowService(None, 1, 42).generate(variables, [{}], resume=True)
    assert designed == [3, 4, 5]
    assert data["resume_info"]["reused_pages"] == 3
    # A different source snapshot or a different owner cannot reuse the pages.
    for user, sources in [(1, [{"excerpt": "changed source"}]), (2, [{}])]:
        designed.clear()
        _, data = PptWorkflowService(None, user, 42).generate(variables, sources, resume=True)
        assert designed == list(range(6))
        assert data["resume_info"]["resumed"] is False


def test_export_retry_reuses_all_pages_without_model_calls(tmp_path, monkeypatch):
    from app.services.ppt_native_service import PptNativeService
    monkeypatch.setattr(settings, "generated_artifact_directory", str(tmp_path))
    variables = {"outline_json": "{}", "course_name": "思政", "chapter_title": "民主", "ppt_preferences": '{"slide_count":6}'}
    def fail_export(*args):
        raise RuntimeError("office unavailable")
    monkeypatch.setattr(PptNativeService, "export", fail_export)
    with pytest.raises(RuntimeError, match="office unavailable"):
        PptWorkflowService(None, 1, 42).generate(variables, [{}])
    def no_new_calls(*args, **kwargs):
        raise AssertionError("must not call text model for an export retry")
    monkeypatch.setattr(PptWorkflowService, "_plan", no_new_calls)
    monkeypatch.setattr(PptWorkflowService, "_design_page", no_new_calls)
    monkeypatch.setattr(PptNativeService, "export", lambda self, data, evidence: ({"kind": "ppt"}, data))
    _, data = PptWorkflowService(None, 1, 42).generate(variables, [{}], resume=True)
    assert data["resume_info"]["reused_pages"] == 6


def test_page_four_regression_accepts_approved_five_democracy_labels():
    from app.services.ppt_svg_service import bind_plan_text
    content = PptPage(layout="process", title="五个环节相互衔接", takeaway="理解民主参与的完整过程",
        bullets=["民主选举、民主协商、民主决策相互衔接", "民主管理、民主监督共同构成完整过程"],
        diagram_labels=["民主选举", "民主协商", "民主决策", "民主管理", "民主监督"], speaker_notes="依据已确认材料。")
    raw = PptWorkflowService._fixture_svg(content, {"text": "162033", "background": "FFFFFF"})
    labels = ''.join(f'<text id="step-{i}" x="900" y="{270+i*64}" font-size="26">{label}</text>'
        for i, label in enumerate(content.diagram_labels))
    result = validate_svg(bind_plan_text(raw.replace('</svg>', labels+'</svg>'), content), content)
    assert all(f'id="label-{i}"' in result for i in range(5))


def test_picture_frame_removes_conflicting_decorative_ring_but_keeps_text():
    from xml.etree import ElementTree as ET
    from app.services.ppt_native_service import apply_picture_frame
    from app.services.ppt_svg_service import SVG_NS
    root = ET.fromstring(svg().replace('</svg>', '<circle id="old-frame" cx="990" cy="400" r="210"/>'
        '<image id="visual-asset" x="800" y="270" width="380" height="260"/></svg>'))
    slot = root.find(f'.//{{{SVG_NS}}}image')
    assert apply_picture_frame(root, slot, {"image_frame_shape": "roundRect"}) == "roundRect"
    assert not any(node.get('id') == 'old-frame' for node in root.iter())
    assert root.find(f'.//{{{SVG_NS}}}text').get('id') == 'title'


def visual_brief(**values):
    return {"kind": "illustration", "purpose": "用社区意见记录场景帮助理解社区协商",
        "content_anchors": ["社区协商"], "scene_family": "意见记录", "key_elements": ["记录本", "居民递交意见卡"],
        "difference": "聚焦意见记录而不是另一张围桌讨论", **values}


def test_visual_brief_is_grounded_and_chooses_correct_carrier():
    from pydantic import ValidationError
    data = {**page().model_dump(), "visual_prompt": "居民向社区工作者递交意见卡，工作者记录意见", "visual_brief": visual_brief()}
    assert PptPage.model_validate(data).visual_brief.kind == "illustration"
    for brief in [visual_brief(content_anchors=["未在正文中的概念"]), visual_brief(key_elements=[]), visual_brief(kind="diagram")]:
        with pytest.raises(ValidationError):
            PptPage.model_validate({**data, "visual_brief": brief})
    diagram = {**data, "visual_prompt": "", "diagram_labels": ["社区协商", "具体实践"],
        "visual_brief": visual_brief(kind="diagram")}
    assert PptPage.model_validate(diagram).visual_brief.kind == "diagram"


def test_effective_image_prompt_contains_teaching_intent_without_painted_frame():
    from app.services.ppt_multimodal_service import PptMultimodalService
    text = PptMultimodalService._safe_prompt({"visual_prompt": "圆角矩形构图，居民递交意见卡", "visual_brief": visual_brief()},
        {"image_style": "圆角矩形构图，水彩插画", "image_frame_shape": "circle"})
    assert "社区协商" in text and "居民递交意见卡" in text and "本页教学意图" in text
    assert "圆角矩形构图" not in text and "不绘制边框" in text


@pytest.mark.parametrize("raw,status", [
    ('{"passed":true,"reason":"可见居民交意见卡和工作者记录","matched_elements":["递交意见卡","记录本"],"missing_elements":[]}', "passed"),
    ('{"passed":true,"reason":"缺少主要对象","matched_elements":["居民"],"missing_elements":["记录本"]}', "rejected"),
    ('{"passed":false,"reason":"只是一张风景图","matched_elements":[],"missing_elements":["居民"]}', "rejected"),
    ('{"passed":"true","reason":"错误布尔类型"}', "unreviewed"),
    ('not json', "unreviewed"),
])
def test_semantic_review_never_promotes_unknown_to_pass(monkeypatch, raw, status):
    from app.services.ppt_multimodal_service import PptMultimodalService
    from app.services.multimodal_provider import VisionProvider
    monkeypatch.setattr(VisionProvider, "available", property(lambda self: True))
    monkeypatch.setattr(VisionProvider, "generate", lambda *args, **kwargs: raw)
    monkeypatch.setattr("app.services.ppt_native_service.safe_artifact_path", lambda value: Path(value))
    result = PptMultimodalService(1)._review_asset({"storage_path": "private.png"}, {**page().model_dump(), "visual_brief": visual_brief()})
    assert result["status"] == status


def _image_run(db):
    user, run = _owned_run(db)
    ppt = {"title": "当前课件", "revision_id": "initial", "pipeline_version": "ppt-master-svg-v2",
        "slides": [{**page().model_dump(), "svg": svg().replace("</svg>", '<image id="visual-asset" x="800" y="270" width="380" height="260"/></svg>'),
            "visual_prompt": "居民向社区工作者递交意见卡"}]}
    run.output_data = {**run.output_data, "artifact_bundle": {"ppt": ppt}}
    db.commit()
    return user, run


def test_image_queue_is_owned_revision_bound_and_hides_private_path(db):
    from app.schemas.agent import PptImageRevisionRequest
    user, run = _image_run(db)
    service = AgentService(db, user)
    with pytest.raises(HTTPException) as error:
        service.request_ppt_image_revision(run.id, 0, PptImageRevisionRequest(prompt="居民向社区工作者递交意见卡", expected_revision="stale"))
    assert error.value.status_code == 409
    response = service.request_ppt_image_revision(run.id, 0, PptImageRevisionRequest(prompt="居民向社区工作者递交意见卡", expected_revision="initial"))
    assert response.status == "queued"
    assert "previous_path" not in response.output_data["ppt_image_job"]
    assert response.output_data["artifacts"]["ppt"].get("storage_path") is None
    with pytest.raises(HTTPException):
        service.request_ppt_image_revision(run.id, 0, PptImageRevisionRequest(prompt="居民向社区工作者递交意见卡", expected_revision="initial"))
    other = User(username="another-teacher", password_hash="test", role="teacher", approval_status="approved")
    db.add(other)
    db.commit()
    with pytest.raises(HTTPException) as error:
        AgentService(db, other).get(run.id)
    assert error.value.status_code == 403


@pytest.mark.parametrize("failure", [True, False])
def test_image_worker_keeps_old_result_on_failure_and_versions_success(db, monkeypatch, failure):
    from app.schemas.agent import PptImageRevisionRequest
    from app.services.agent_service import execute_ppt_image_revision
    user, run = _image_run(db)
    original = deepcopy(run.output_data)
    service = AgentService(db, user)
    response = service.request_ppt_image_revision(run.id, 0, PptImageRevisionRequest(prompt="居民向社区工作者递交意见卡", expected_revision="initial"))
    def regenerate(self, original, index, prompt, evidence):
        if failure:
            raise RuntimeError("配图语义复核未通过")
        return {"storage_path": "new.pptx", "kind": "ppt"}, {**original, "revision_id": "new-revision"}
    monkeypatch.setattr(PptWorkflowService, "regenerate_image", regenerate)
    execute_ppt_image_revision(run.id, response.output_data["ppt_image_job"]["id"], db.get_bind())
    db.refresh(run)
    assert run.status == "completed"
    if failure:
        assert run.output_data["artifacts"] == original["artifacts"]
        assert run.output_data["artifact_bundle"] == original["artifact_bundle"]
        assert run.output_data["ppt_image_job"]["status"] == "failed"
    else:
        assert run.output_data["artifacts"]["ppt"]["storage_path"] == "new.pptx"
        assert run.output_data["ppt_versions"][-1]["artifact"]["storage_path"] == "current.pptx"
        assert run.output_data["ppt_image_job"]["status"] == "completed"


def test_image_only_regeneration_preserves_all_svg_and_other_assets(monkeypatch):
    from app.services.ppt_native_service import PptNativeService
    from app.services.ppt_multimodal_service import PptMultimodalService
    pages = [{**page().model_dump(), "svg": svg(), "visual_asset": {"storage_path": f"old-{i}.png"}} for i in range(6)]
    pages[2]["svg"] = svg().replace("</svg>", '<image id="visual-asset" x="800" y="270" width="380" height="260"/></svg>')
    original = {"design": {}, "slides": pages}
    before = deepcopy(original)
    def enhanced(self, data, **kwargs):
        assert len(data["slides"]) == 1 and "visual_asset" not in data["slides"][0]
        data["slides"][0]["visual_asset"] = {"storage_path": "new.png", "review": {"status": "passed"}}
        return data
    monkeypatch.setattr(PptMultimodalService, "enhance_svg", enhanced)
    monkeypatch.setattr(PptNativeService, "export", lambda self, data, evidence: ({"kind": "ppt"}, data))
    _, updated = PptWorkflowService(None, None, 1).regenerate_image(original, 2, "只画居民递交意见卡和工作人员记录", [])
    assert original == before
    for i in range(6):
        assert updated["slides"][i]["svg"] == original["slides"][i]["svg"]
        if i != 2:
            assert updated["slides"][i] == original["slides"][i]
    assert updated["slides"][2]["visual_asset"]["storage_path"] == "new.png"


def test_image_job_predicates_compile_for_mysql():
    query = select(AgentRun.id).where(AgentRun.output_data["ppt_image_job"]["id"].as_string() == "job")
    assert "JSON_EXTRACT" in str(query.compile(dialect=mysql.dialect()))


def test_image_endpoint_enqueues_and_requires_teacher(client, db, monkeypatch):
    from app.core.security import create_access_token
    user, run = _image_run(db)
    monkeypatch.setattr("app.api.v1.endpoints.agents.execute_ppt_image_revision", lambda *args: None)
    payload = {"prompt": "居民向社区工作者递交意见卡", "expected_revision": "initial"}
    url = f"/api/v1/agent/runs/{run.id}/ppt/slides/0/image"
    assert client.post(url, json=payload).status_code == 401
    student = User(username="image-test-student", role="student", password_hash="test", approval_status="approved")
    db.add(student)
    db.commit()
    assert client.post(url, json=payload, headers={"Authorization": f"Bearer {create_access_token(str(student.id))}"}).status_code == 403
    response = client.post(url, json=payload, headers={"Authorization": f"Bearer {create_access_token(str(user.id))}"})
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "queued"
    assert "previous_path" not in response.json()["data"]["output_data"]["ppt_image_job"]


def test_image_restart_and_queued_cancel_preserve_old_artifact(db):
    from app.schemas.agent import PptImageRevisionRequest
    from app.services.agent_service import recover_agent_runs, execute_ppt_image_revision
    user, run = _image_run(db)
    service = AgentService(db, user)
    request = PptImageRevisionRequest(prompt="居民向社区工作者递交意见卡", expected_revision="initial")
    response = service.request_ppt_image_revision(run.id, 0, request)
    service.cancel(run.id)
    execute_ppt_image_revision(run.id, response.output_data["ppt_image_job"]["id"], db.get_bind())
    db.refresh(run)
    assert run.status == "cancelled" and run.output_data["artifacts"]["ppt"]["storage_path"] == "current.pptx"
    assert run.output_data["ppt_image_job"]["status"] == "cancelled"
    service.request_ppt_image_revision(run.id, 0, request)
    recover_agent_runs(db.get_bind())
    db.refresh(run)
    assert run.status == "completed" and run.output_data["artifacts"]["ppt"]["storage_path"] == "current.pptx"
    assert run.output_data["ppt_image_job"]["status"] == "failed"


def test_whitespace_image_prompt_is_rejected():
    from pydantic import ValidationError
    from app.schemas.agent import PptImageRevisionRequest
    with pytest.raises(ValidationError):
        PptImageRevisionRequest(prompt=" " * 20, expected_revision="initial")

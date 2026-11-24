"""Deterministic fault injection, not paid model/API acceptance tests."""
from copy import deepcopy
import json
from types import SimpleNamespace

from PIL import Image
import pytest

from app.core.config import settings
from app.models.ai_operation import AiProviderConfig
from app.schemas.agent import PptPreferences
from app.schemas.presentation import PptPage
from app.services.ai_operation_service import encrypt_api_key
from app.services.ppt_checkpoint_service import PptCheckpointStore, digest
from app.services.ppt_multimodal_service import IMAGE_PROMPT_VERSION, PptMultimodalService
from app.services.ppt_native_service import PptNativeService
from app.services.ppt_skill_service import skill_contract
from app.services.ppt_svg_service import validate_svg
from app.services.ppt_workflow_service import PLAN_PROMPT, SVG_PROMPT, PptWorkflowService
import app.services.ppt_workflow_service as workflow_module


@pytest.fixture
def setup_images(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "generated_artifact_directory", str(tmp_path))
    monkeypatch.setattr(settings, "ppt_multimodal_api_key", "old-image-key")
    monkeypatch.setattr(settings, "ppt_multimodal_enabled", True)
    monkeypatch.setattr(settings, "ppt_multimodal_max_images", 2)
    monkeypatch.setattr(settings, "ppt_multimodal_model", "wan-test")
    monkeypatch.setattr(settings, "ppt_multimodal_base_url", "https://dashscope.aliyuncs.com/api/v1")
    monkeypatch.setattr(workflow_module, "check_runtime", lambda: {})
    monkeypatch.setattr(PptNativeService, "export", lambda self, data, evidence: ({"kind": "ppt"}, deepcopy(data)))
    variables = {"outline_json": "{}", "course_name": "思政", "chapter_title": "民主",
                 "ppt_preferences": '{"slide_count":6,"include_visuals":true}'}
    service = PptWorkflowService(None, 1, 42)
    data = service._plan(variables, [{}], PptPreferences(slide_count=6))
    for index in (1, 3):
        data["slides"][index]["visual_prompt"] = f"公开合成教学场景{index}"
    data.update(pipeline_version="ppt-master-svg-v2", skill=skill_contract()[0],
                preferences=PptPreferences(slide_count=6).model_dump())
    calls = SimpleNamespace(plan=0, design=[], image=[], fail=True)

    def plan(self, *args):
        calls.plan += 1
        return deepcopy(data)

    def design(self, content, theme, preferences, index, roster, **kwargs):
        calls.design.append(index)
        page = PptPage.model_validate({key: value for key, value in content.items() if key in PptPage.model_fields})
        value = self._fixture_svg(page, theme)
        if page.visual_prompt:
            value = value.replace("</svg>", '<image id="visual-asset" x="900" y="270" width="280" height="260"/></svg>')
        return validate_svg(value, page, include_visual=bool(page.visual_prompt))

    def image(self, slide, theme, index):
        calls.image.append((index, self.api_key))
        if calls.fail and index == 3:
            raise RuntimeError("injected image authorization failure")
        path = self.asset_dir / f"paid-{index}-{len(calls.image)}.png"
        Image.new("RGB", (32, 32), "white").save(path)
        return {"storage_path": str(path.relative_to(tmp_path)), "review": {"status": "passed"}}

    monkeypatch.setattr(PptWorkflowService, "_plan", plan)
    monkeypatch.setattr(PptWorkflowService, "_design_page", design)
    monkeypatch.setattr(PptMultimodalService, "_generate_one", image)
    return SimpleNamespace(variables=variables, data=data, calls=calls, root=tmp_path,
                           design=design, monkeypatch=monkeypatch)


@pytest.mark.parametrize("change", ["image_key", "vision_key", "image_model"])
def test_resume_after_image_config_change_reuses_every_svg_and_paid_image(setup_images, change):
    context = setup_images
    _, before = PptWorkflowService(None, 1, 42).generate(context.variables, [{}])
    assert before["multimodal"]["generated_count"] == 1
    assert before["multimodal"]["missing_count"] == 1
    paid = deepcopy(before["slides"][1]["visual_asset"])
    context.calls.fail = False
    context.calls.image.clear()
    field = {"image_key": "ppt_multimodal_api_key", "vision_key": "ai_vision_api_key", "image_model": "ppt_multimodal_model"}[change]
    context.monkeypatch.setattr(settings, field, "new-configuration")
    _, after = PptWorkflowService(None, 1, 42).generate(context.variables, [{}], resume=True)
    assert context.calls.plan == 1
    assert context.calls.design == list(range(6))  # no new text/SVG calls
    assert [index for index, key in context.calls.image] == [3]
    assert after["slides"][1]["visual_asset"] == paid
    assert [item["svg"] for item in after["slides"]] == [item["svg"] for item in before["slides"]]
    assert after["resume_info"] == {"resumed": True, "requested": True, "legacy_imported": False,
        "reused_pages": 6, "reused_images": 1, "generated_images": 1, "pending_images": 0}
    assert after["multimodal"]["requested_count"] == after["multimodal"]["generated_count"] == 2
    assert after["multimodal"]["reused_count"] == after["multimodal"]["newly_generated_count"] == 1


def test_configuration_recovery_keeps_plan_slots_and_does_not_report_false_success(setup_images):
    context = setup_images
    context.monkeypatch.setattr(settings, "ppt_multimodal_enabled", False)
    _, before = PptWorkflowService(None, 1, 42).generate(context.variables, [{}])
    assert before["multimodal"]["requested_count"] == 2
    assert before["multimodal"]["generated_count"] == 0
    assert context.calls.image == []
    state_path = next(context.root.glob("42/ppt_jobs/*/*/state.json"))
    assert json.loads(state_path.read_text())["status"] == "partial"
    context.monkeypatch.setattr(settings, "ppt_multimodal_enabled", True)
    context.calls.fail = False
    _, after = PptWorkflowService(None, 1, 42).generate(context.variables, [{}], resume=True)
    assert context.calls.plan == 1 and context.calls.design == list(range(6))
    assert [index for index, _ in context.calls.image] == [1, 3]
    assert after["resume_info"]["reused_pages"] == 6


def test_only_missing_or_damaged_images_are_requested(setup_images):
    context = setup_images
    _, before = PptWorkflowService(None, 1, 42).generate(context.variables, [{}])
    path = context.root / before["slides"][1]["visual_asset"]["storage_path"]
    path.write_bytes(b"damaged image")
    context.calls.fail = False
    context.calls.image.clear()
    _, after = PptWorkflowService(None, 1, 42).generate(context.variables, [{}], resume=True)
    assert [index for index, _ in context.calls.image] == [1, 3]
    assert context.calls.plan == 1 and context.calls.design == list(range(6))
    assert after["resume_info"]["reused_images"] == 0


def test_export_failure_after_all_images_succeeded_never_regenerates_paid_images(setup_images):
    context = setup_images
    context.calls.fail = False
    def unavailable(*args):
        raise RuntimeError("export unavailable")
    context.monkeypatch.setattr(PptNativeService, "export", unavailable)
    with pytest.raises(RuntimeError, match="export unavailable"):
        PptWorkflowService(None, 1, 42).generate(context.variables, [{}])
    context.calls.image.clear()
    context.monkeypatch.setattr(settings, "ppt_multimodal_api_key", "rotated-image-key")
    context.monkeypatch.setattr(PptNativeService, "export", lambda self, data, evidence: ({"kind": "ppt"}, data))
    _, result = PptWorkflowService(None, 1, 42).generate(context.variables, [{}], resume=True)
    assert context.calls.image == []
    assert result["resume_info"]["reused_images"] == 2
    assert result["resume_info"]["pending_images"] == 0
    assert context.calls.plan == 1 and context.calls.design == list(range(6))


def test_paid_image_is_checkpointed_before_cancellation(setup_images):
    from app.services.ppt_workflow_service import PptWorkflowCancelled
    context = setup_images
    context.calls.fail = False
    workflow = None
    def cancel_after_image(stage, *args):
        if stage == "illustrating" and workflow.resume_info["generated_images"] == 1:
            raise PptWorkflowCancelled("stop after one paid image")
    workflow = PptWorkflowService(None, 1, 42, progress=cancel_after_image)
    with pytest.raises(PptWorkflowCancelled):
        workflow.generate(context.variables, [{}])
    context.calls.image.clear()
    _, result = PptWorkflowService(None, 1, 42).generate(context.variables, [{}], resume=True)
    assert [index for index, _ in context.calls.image] == [3]
    assert result["resume_info"]["reused_images"] == 1


def test_explicit_fresh_generation_still_regenerates_instead_of_reusing(setup_images):
    context = setup_images
    PptWorkflowService(None, 1, 42).generate(context.variables, [{}])
    context.calls.image.clear()
    _, result = PptWorkflowService(None, 1, 42).generate(context.variables, [{}], resume=False)
    assert context.calls.plan == 2
    assert context.calls.design == list(range(6)) * 2
    assert [index for index, _ in context.calls.image] == [1, 3]
    assert not result["resume_info"]["resumed"]


@pytest.mark.parametrize("change", [None, "owner", "evidence", "preferences", "missing_history"])
def test_legacy_v4_migration_after_key_rotation_requires_exact_content_proof(setup_images, db, change):
    context = setup_images
    image_base = "https://dashscope.aliyuncs.com/api/v1"
    vision_base = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    for capability, model, base, old, new in [
        ("image_generation", "wan-test", image_base, "legacy-image-key", "new-image-key"),
        ("vision", "qwen-vl-test", vision_base, "legacy-review-key", "new-review-key"),
    ]:
        for key, active in [(old, False), (new, True)]:
            if not active and change == "missing_history":
                continue
            db.add(AiProviderConfig(capability=capability, model_name=model, base_url=base,
                api_key_encrypted=encrypt_api_key(key), enabled=True, is_active=active))
    db.commit()
    metadata = skill_contract()[0]
    signature = {"version": 4, "user": 1, "mock": True,
        "input": {**context.variables, "image_budget": "2"}, "evidence": [{}], "skill": metadata,
        "models": [], "prompts": digest([PLAN_PROMPT, SVG_PROMPT]),
        "image": {"prompt_version": IMAGE_PROMPT_VERSION, "model": "wan-test", "base": image_base,
            "key_hash": digest("legacy-image-key"), "review_enabled": settings.ppt_image_review_enabled,
            "review": [True, "qwen-vl-test", vision_base, digest("legacy-review-key")]}}
    old = PptCheckpointStore(42, signature, resume=False)
    data = deepcopy(context.data)
    preferences = PptPreferences(slide_count=6)
    for index, content in enumerate(data["slides"]):
        content["svg"] = context.design(PptWorkflowService(None, 1, 42), content, data["design"], preferences, index, data["slides"])
    Image.new("RGB", (32, 32), "white").save(context.root / "legacy-paid.png")
    data["slides"][1]["visual_asset"] = {"storage_path": "legacy-paid.png", "review": {"status": "passed"}}
    old.save(status="partial", data=data)
    original = (old.directory / "state.json").read_bytes()
    variables = deepcopy(context.variables)
    if change == "preferences":
        variables["ppt_preferences"] = '{"slide_count":6,"include_visuals":true,"visual_style":"youthful"}'
    _, result = PptWorkflowService(db, 2 if change == "owner" else 1, 42).generate(
        variables, [{"excerpt": "different source"}] if change == "evidence" else [{}], resume=True)
    assert result["resume_info"]["legacy_imported"] is (change is None)
    assert result["resume_info"]["reused_pages"] == (6 if change is None else 0)
    assert context.calls.plan == (0 if change is None else 1)
    if change is None:
        assert result["resume_info"]["reused_images"] == 1
        assert [index for index, _ in context.calls.image] == [3]
    assert (old.directory / "state.json").read_bytes() == original
    for path in context.root.glob("42/ppt_jobs/*/*/state.json"):
        assert all(key not in path.read_text() for key in ("legacy-image-key", "new-image-key", "legacy-review-key", "new-review-key"))

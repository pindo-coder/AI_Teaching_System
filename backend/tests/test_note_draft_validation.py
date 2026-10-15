"""Schema/repair regression tests; live DeepSeek acceptance is run separately."""
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.models.agent_execution import AgentExecution
from app.models.chapter import Chapter
from app.models.course import Course
from app.models.learning_task import LearningEvent
from app.models.user import User
from app.schemas.ai import AiAssistData, AiSource
from app.services.ai_service import AiService, LangChainGenerator
from app.services.planning_agent import PlanningAgent


def output(gaps=8, body="可保存的补充正文，重要观点应核对教材[资料1]。"):
    return json.dumps({"gaps": [f"具体缺口{index}" for index in range(gaps)], "draft_content": body}, ensure_ascii=False)


def test_eight_diagnosis_items_do_not_discard_valid_body():
    generated, issues = PlanningAgent._parse_note_draft(output(), 1)
    assert issues == []
    assert len(generated.gaps) == 8
    assert generated.gaps[-1] == "具体缺口7"
    assert generated.draft_content.endswith("[资料1]。")


@pytest.mark.parametrize("answer,expected", [
    ("PRIVATE_NOTE_SENTINEL", "response:invalid_json_object"),
    ('{"gaps":["PRIVATE_NOTE_SENTINEL"]}', "draft_content:missing"),
    ('{"gaps":["缺口"],"draft_content":["PRIVATE_NOTE_SENTINEL"]}', "draft_content:string_type"),
    ('{"gaps":["  "],"draft_content":"正文[资料1]"}', "gaps.0:string_too_short"),
    (output(33), "gaps:too_long"),
    (output(body="没有引用"), "draft_content.citations:missing"),
    (output(body="错误引用[资料2]"), "draft_content.citations:out_of_range"),
    (output(body="错误引用[资料0]"), "draft_content.citations:out_of_range"),
])
def test_invalid_shape_and_citations_produce_redacted_field_codes(answer, expected):
    generated, issues = PlanningAgent._parse_note_draft(answer, 1)
    assert generated is None
    assert expected in issues
    assert "PRIVATE_NOTE_SENTINEL" not in repr(issues)


def test_fenced_json_and_whitespace_are_supported_without_dropping_items():
    answer = '```json\n{"gaps":["  缺口  "],"draft_content":"  正文[资料1]  "}\n```'
    generated, issues = PlanningAgent._parse_note_draft(answer, 1)
    assert not issues
    assert generated.gaps == ["缺口"]
    assert generated.draft_content == "正文[资料1]"


def test_json_repair_reuses_exact_sources_and_does_not_mutate_original_variables():
    calls = []

    def invoke(variables):
        calls.append(dict(variables))
        return output(2)

    generator = LangChainGenerator.__new__(LangChainGenerator)
    generator.json_output = True
    original = {"chapter_content": "[资料1] 固定教材正文", "question": "完善测试笔记"}
    generator._last_json_variables = dict(original)
    generator.chain = SimpleNamespace(invoke=invoke)
    generator.repair_json("待纠正输出", ["draft_content:string_type"])
    assert len(calls) == 1
    assert calls[0]["chapter_content"] == original["chapter_content"]
    assert calls[0]["question"].startswith(original["question"])
    assert "draft_content:string_type" in calls[0]["question"]
    assert original["question"] == "完善测试笔记"


@pytest.mark.parametrize("repair_succeeds", [True, False])
def test_note_generation_corrects_once_and_never_records_failed_ai_evidence(client, db, monkeypatch, caplog, repair_succeeds):
    user = User(username="note_shape_student", password_hash=hash_password("test-pass-123"), role="student")
    course = Course(name="格式回归测试教材", description="测试")
    db.add_all([user, course]); db.flush()
    chapter = Chapter(course_id=course.id, title="理论联系实际", content="学习需要核对教材依据。", sort_order=1)
    db.add(chapter); db.commit()
    headers = {"Authorization": "Bearer " + create_access_token(str(user.id))}
    counters = {"assist": 0, "repair": 0}

    class CorrectionGenerator:
        def __init__(self, *args, **kwargs):
            assert kwargs["json_output"] is True

        def repair_json(self, answer, issues):
            counters["repair"] += 1
            assert "draft_content:string_type" in issues
            return output() if repair_succeeds else output(body="仍是错误引用[资料999]")

    def assist(self, payload, **kwargs):
        counters["assist"] += 1
        return AiAssistData(answer='{"gaps":["缺口"],"draft_content":["PRIVATE_NOTE_SENTINEL"]}',
            grounded=True, model="unit-test-only", sources=[AiSource(source_type="chapter_content",
                source_title="测试教材", course_id=course.id, chapter_id=chapter.id, excerpt="核对教材依据")])

    monkeypatch.setattr(settings, "ai_mock_mode", False)
    monkeypatch.setattr("app.services.ai_service.LangChainGenerator", CorrectionGenerator)
    monkeypatch.setattr(AiService, "assist", assist)
    response = client.post("/api/v1/ai/workspace/agent/stream", headers=headers,
        json={"course_id": course.id, "chapter_id": chapter.id, "role": "student", "question": "完善笔记"})
    assert response.status_code == 200
    assert counters == {"assist": 1, "repair": 1}
    execution = db.scalar(select(AgentExecution))
    assert execution.status == ("waiting_user_action" if repair_succeeds else "failed")
    assert db.scalar(select(func.count()).select_from(LearningEvent).where(
        LearningEvent.user_id == user.id, LearningEvent.event_type == "ai_assist_used")) == int(repair_succeeds)
    assert "PRIVATE_NOTE_SENTINEL" not in caplog.text
    assert "draft_content:string_type" in caplog.text
    if not repair_succeeds:
        failed = next(item for item in execution.tool_results if item["tool"] == "draft_note_improvement")
        assert failed["data"]["validation_issues"] == ["draft_content.citations:out_of_range"]
        assert not failed["retryable"]

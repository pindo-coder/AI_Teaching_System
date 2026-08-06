from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.models.chapter import Chapter
from app.models.citation import DocumentOutlineNode, DocumentPage
from app.models.course import Course
from app.models.knowledge_document import KnowledgeDocument
from app.models.user import User
from app.models.agent_execution import AgentExecution
from app.api.v1.endpoints.ai import _agent_intent
from app.services.agent_context_service import AgentContextService
from app.services.planning_agent import PlanningAgent
from app.services.ai_service import LangChainGenerator
from app.services.llm_compat import clean_model_text


def prepare_context(db: Session, *, content: str | None = "理想信念是精神之钙。") -> tuple[dict[str, str], int, int]:
    user = User(username="ai_student", password_hash=hash_password("secure-pass-123"), role="student")
    course = Course(name="思想道德与法治", description="测试课程")
    db.add_all([user, course])
    db.flush()
    chapter = Chapter(course_id=course.id, title="坚定理想信念", content=content, sort_order=1)
    db.add(chapter)
    db.commit()
    db.refresh(user)
    db.refresh(course)
    db.refresh(chapter)
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}, course.id, chapter.id


def test_custom_model_prompt_echo_is_removed() -> None:
    raw = "system\n你是高校思政课教师。\nuser\n请总结本章。\nassistant\n这是清理后的正式回答。"
    assert clean_model_text(raw) == "这是清理后的正式回答。"


def test_non_sse_compatible_model_falls_back_to_invoke() -> None:
    class NonStreamingChain:
        def __init__(self) -> None:
            self.stream_calls = 0
            self.invoke_calls = 0

        def stream(self, _variables):
            self.stream_calls += 1
            raise ValueError("No generation chunks were returned")
            yield ""  # pragma: no cover

        def invoke(self, _variables):
            self.invoke_calls += 1
            return "system\n规则\nuser\n问题\nassistant\n兼容模式回答成功。"

    chain = NonStreamingChain()
    generator = LangChainGenerator.__new__(LangChainGenerator)
    generator.chain = chain
    generator.stream_key = ("https://model.test/v1", "custom-model-test")

    assert "".join(generator.stream({})) == "兼容模式回答成功。"
    assert "".join(generator.stream({})) == "兼容模式回答成功。"
    assert chain.stream_calls == 1
    assert chain.invoke_calls == 2


def test_ai_assist_uses_course_context_in_mock_mode(client: TestClient, db: Session) -> None:
    headers, course_id, chapter_id = prepare_context(db)
    response = client.post(
        "/api/v1/ai/assist",
        headers=headers,
        json={
            "course_id": course_id,
            "chapter_id": chapter_id,
            "learning_stage": "preview",
            "task_type": "chapter_summary",
            "question": "帮我总结本章重点",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["grounded"] is True
    assert data["model"] == "mock"
    assert "坚定理想信念" in data["answer"]
    assert len(data["sources"]) == 1


def test_chapter_content_source_includes_clickable_pdf_location(client: TestClient, db: Session) -> None:
    headers, course_id, chapter_id = prepare_context(db)
    document = KnowledgeDocument(
        source_title="测试教材", source_type="pdf", original_filename="测试教材.pdf",
        stored_path="/tmp/test-textbook.pdf", course_id=course_id, chapter_id=None,
        vector_collection="test", source_role="primary", access_policy="full_preview",
            calibration_status="published", status="ready", chunk_count=0,
    )
    db.add(document); db.flush()
    db.add_all([
        DocumentPage(document_id=document.id, pdf_page=12, printed_page_label="3", text="章节正文", text_blocks=[]),
        DocumentPage(document_id=document.id, pdf_page=14, printed_page_label="5", text="章节正文", text_blocks=[]),
        DocumentOutlineNode(
            document_id=document.id, chapter_id=chapter_id, node_type="chapter", title="坚定理想信念",
            sort_order=1, pdf_page_start=12, pdf_page_end=14, retrieval_enabled=True,
            calibration_status="auto",
        ),
    ]); db.commit()

    response = client.post(
        "/api/v1/ai/assist", headers=headers,
        json={"course_id": course_id, "chapter_id": chapter_id, "learning_stage": "preview",
              "task_type": "chapter_summary", "question": "帮我总结本章重点"},
    )
    source = response.json()["data"]["sources"][0]
    assert source["document_id"] == document.id
    assert source["pdf_page_start"] == 12
    assert source["pdf_page_end"] == 14
    assert source["printed_page_start"] == "3"
    assert source["position"] == "教材第 3—5 页"


def test_ai_assist_refuses_when_chapter_has_no_content(client: TestClient, db: Session) -> None:
    headers, course_id, chapter_id = prepare_context(db, content=None)
    response = client.post(
        "/api/v1/ai/assist",
        headers=headers,
        json={
            "course_id": course_id,
            "chapter_id": chapter_id,
            "learning_stage": "review",
            "task_type": "review_outline",
            "question": "生成复习提纲",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["grounded"] is False
    assert response.json()["data"]["sources"] == []


def test_ai_assist_streams_sse_chunks(client: TestClient, db: Session) -> None:
    headers, course_id, chapter_id = prepare_context(db)
    response = client.post(
        "/api/v1/ai/assist/stream",
        headers=headers,
        json={
            "course_id": course_id,
            "chapter_id": chapter_id,
            "learning_stage": "preview",
            "task_type": "preview_questions",
            "question": "生成预习问题",
        },
    )
    assert response.status_code == 200
    assert "event: chunk" in response.text
    assert "event: sources" in response.text
    assert "event: done" in response.text


def test_workspace_assistant_is_available_without_context(client: TestClient, db: Session) -> None:
    headers, _, _ = prepare_context(db)
    response = client.post(
        "/api/v1/ai/workspace/stream",
        headers=headers,
        json={"mode": "agent", "role": "admin", "question": "帮我检查资料"},
    )

    assert response.status_code == 200
    assert "event: meta" in response.text
    assert '"role": "student"' in response.text
    assert "请先选择课程专题" in response.text


def test_teacher_natural_language_learning_task_routes_to_assignment_setup() -> None:
    assert (
        _agent_intent("请为当前教材专题设计一项课后学习任务。", "teacher")
        == "assignment_setup"
    )


def test_workspace_assistant_uses_selected_mode_and_role(client: TestClient, db: Session) -> None:
    headers, course_id, chapter_id = prepare_context(db)
    response = client.post(
        "/api/v1/ai/workspace/stream",
        headers=headers,
        json={
            "mode": "agent",
            "role": "teacher",
            "course_id": course_id,
            "chapter_id": chapter_id,
            "question": "请规划一份课堂互动",
        },
    )

    assert response.status_code == 200
    assert '"mode": "agent"' in response.text
    assert '"role": "student"' in response.text
    assert "当前章节" in response.text or "坚定理想信念" in response.text


def test_workspace_context_keeps_explicit_page_course_and_chapter(client: TestClient, db: Session) -> None:
    headers, course_id, chapter_id = prepare_context(db)
    response = client.post(
        "/api/v1/ai/workspace/context",
        headers=headers,
        json={
            "course_id": course_id,
            "chapter_id": chapter_id,
            "learning_stage": "review",
            "page_name": "learning-stage",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["course_id"] == course_id
    assert data["chapter_id"] == chapter_id
    assert data["source"] == "page"
    assert data["confidence"] == "high"


def test_workspace_context_lists_course_center_material_without_teaching_class(client: TestClient, db: Session) -> None:
    headers, course_id, _ = prepare_context(db)
    response = client.post(
        "/api/v1/ai/workspace/context",
        headers=headers,
        json={"learning_stage": "preview", "page_name": "courses"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["course_id"] == course_id
    assert any(item["course_id"] == course_id for item in data["candidates"])


def test_workspace_agent_creates_traceable_lesson_prep_draft(client: TestClient, db: Session) -> None:
    teacher = User(username="ai_teacher", password_hash=hash_password("secure-pass-123"), role="teacher")
    course = Course(name="习近平新时代中国特色社会主义思想概论", description="测试教材")
    db.add_all([teacher, course]); db.flush()
    chapter = Chapter(course_id=course.id, title="新时代坚持和发展中国特色社会主义", content="坚持和发展中国特色社会主义是当代中国发展进步的根本方向。", sort_order=1)
    db.add(chapter); db.commit()
    headers = {"Authorization": f"Bearer {create_access_token(str(teacher.id))}"}

    response = client.post(
        "/api/v1/ai/workspace/agent/stream",
        headers=headers,
        json={
            "role": "teacher",
            "course_id": course.id,
            "chapter_id": chapter.id,
            "learning_stage": "preview",
            "page_name": "lesson-prep",
            "question": "请生成本专题的课纲和PPT备课草稿",
        },
    )

    assert response.status_code == 200
    assert "event: context" in response.text
    assert "event: plan" in response.text
    assert "event: action" in response.text
    assert "确认资料并生成课纲" in response.text
    execution = db.scalar(select(AgentExecution).order_by(AgentExecution.id.desc()))
    assert execution is not None
    assert execution.status == "waiting_confirmation"
    assert execution.result["blocking_actions"][0]["kind"] == "approve_evidence"

    run_id = execution.result["blocking_actions"][0]["run_id"]
    confirmed_run = client.post(
        f"/api/v1/agent/runs/{run_id}/confirm",
        headers=headers,
        json={"action": "approve_evidence"},
    )
    assert confirmed_run.status_code == 200

    resolved = client.post(
        f"/api/v1/ai/workspace/agent/executions/{execution.id}/resolve",
        headers=headers,
        json={"resolution": "confirmed", "note": "教师已确认证据范围"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["data"]["status"] == "completed"
    assert resolved.json()["data"]["result"]["confirmation"]["resolution"] == "confirmed"


def test_workspace_agent_persists_execution_and_supports_retry(client: TestClient, db: Session) -> None:
    headers, course_id, chapter_id = prepare_context(db)
    response = client.post(
        "/api/v1/ai/workspace/agent/stream",
        headers=headers,
        json={
            "role": "student",
            "course_id": course_id,
            "chapter_id": chapter_id,
            "learning_stage": "preview",
            "question": "请根据当前专题制定学习计划",
        },
    )
    assert response.status_code == 200
    assert "event: execution" in response.text
    execution = db.scalar(select(AgentExecution).order_by(AgentExecution.id.desc()))
    assert execution is not None
    assert execution.status == "completed"
    assert execution.plan["tools"]
    assert execution.tool_results
    assert execution.result["summary"]

    history = client.get("/api/v1/ai/workspace/agent/executions", headers=headers)
    assert history.status_code == 200
    assert history.json()["data"][0]["id"] == execution.id

    retried = client.post(f"/api/v1/ai/workspace/agent/executions/{execution.id}/retry", headers=headers)
    assert retried.status_code == 200
    assert retried.json()["data"]["retry_of_execution_id"] == execution.id


def test_workspace_agent_templates_follow_authenticated_role(client: TestClient, db: Session) -> None:
    headers, _, _ = prepare_context(db)
    response = client.get("/api/v1/ai/workspace/agent/templates", headers=headers)
    assert response.status_code == 200
    templates = response.json()["data"]
    assert any(item["key"] == "study_plan" for item in templates)
    assert all(item["key"] != "lesson_ppt" for item in templates)


def test_planning_agent_selects_tools_for_teacher_assignment_draft(client: TestClient, db: Session) -> None:
    teacher = User(username="planner_teacher", password_hash=hash_password("secure-pass-123"), role="teacher")
    course = Course(name="规划器测试教材", description="测试教材")
    db.add_all([teacher, course]); db.flush()
    chapter = Chapter(course_id=course.id, title="理论联系实际", content="理论联系实际是学习思政课的重要方法。", sort_order=1)
    db.add(chapter); db.commit()
    headers = {"Authorization": f"Bearer {create_access_token(str(teacher.id))}"}
    response = client.post(
        "/api/v1/ai/workspace/agent/stream",
        headers=headers,
        json={
            "role": "teacher",
            "course_id": course.id,
            "chapter_id": chapter.id,
            "learning_stage": "review",
            "question": "请为当前专题设计一项课后学习任务",
        },
    )
    assert response.status_code == 200
    assert "自主任务执行计划" in response.text
    assert '"name": "inspect_context"' in response.text
    assert '"name": "draft_assignment"' in response.text
    assert "课后学习任务草案" in response.text
    assert "进入教学任务设置" in response.text


def test_planning_agent_reuses_existing_outline_for_artifact_generation(client: TestClient, db: Session) -> None:
    teacher = User(username="artifact_planner", password_hash=hash_password("secure-pass-123"), role="teacher")
    course = Course(name="成果工具测试教材", description="测试教材")
    db.add_all([teacher, course]); db.flush()
    chapter = Chapter(course_id=course.id, title="中国式现代化", content="中国式现代化体现了社会主义现代化建设的方向。", sort_order=1)
    db.add(chapter); db.commit()
    headers = {"Authorization": f"Bearer {create_access_token(str(teacher.id))}"}
    run = client.post(
        "/api/v1/agent/runs",
        headers=headers,
        json={"agent_type": "teacher_lesson_prep", "course_id": course.id, "chapter_id": chapter.id, "input": {}},
    ).json()["data"]
    client.post(f"/api/v1/agent/runs/{run['id']}/confirm", headers=headers, json={"action": "approve_evidence"})
    response = client.post(
        "/api/v1/ai/workspace/agent/stream",
        headers=headers,
        json={"role": "teacher", "course_id": course.id, "chapter_id": chapter.id, "question": "请生成PPT"},
    )
    assert response.status_code == 200
    assert '"name": "generate_ppt"' in response.text
    assert '"kind": "generate_artifacts"' in response.text
    assert '"output_types": ["ppt"]' in response.text


def test_planning_agent_reads_student_state_and_returns_next_step(client: TestClient, db: Session) -> None:
    headers, course_id, chapter_id = prepare_context(db)
    response = client.post(
        "/api/v1/ai/workspace/agent/stream",
        headers=headers,
        json={
            "role": "student",
            "course_id": course_id,
            "chapter_id": chapter_id,
            "learning_stage": "preview",
            "question": "请告诉我我的学习状态和还要做什么",
        },
    )

    assert response.status_code == 200
    assert '"name": "inspect_learning_state"' in response.text
    assert "任务点" in response.text
    assert "计划执行完成" in response.text


def test_planning_agent_without_context_offers_context_selection(client: TestClient, db: Session) -> None:
    user = User(username="planner_no_context", password_hash=hash_password("secure-pass-123"), role="student")
    db.add(user)
    db.commit()
    headers = {"Authorization": f"Bearer {create_access_token(str(user.id))}"}
    response = client.post(
        "/api/v1/ai/workspace/agent/stream",
        headers=headers,
        json={"role": "student", "question": "请查找教材依据"},
    )

    assert response.status_code == 200
    assert "当前尚未锁定具体教材专题" in response.text
    assert '"kind": "select_context"' in response.text
    assert '"href": "/courses"' in response.text
    assert "选择教材专题" in response.text


def test_planning_agent_uses_fast_path_for_explicit_teaching_goal(db: Session, monkeypatch) -> None:
    teacher = User(username="planner_fast_path", password_hash=hash_password("secure-pass-123"), role="teacher")
    course = Course(name="快速规划测试教材", description="测试教材")
    db.add_all([teacher, course])
    db.flush()
    chapter = Chapter(course_id=course.id, title="理论学习方法", content="理论联系实际是学习思政课的重要方法。", sort_order=1)
    db.add(chapter)
    db.commit()
    context = AgentContextService(db, teacher).resolve(course_id=course.id, chapter_id=chapter.id, page_name="lesson-prep")
    planner = PlanningAgent(db, teacher)

    def should_not_call_llm(*_args, **_kwargs):
        raise AssertionError("明确教学目标不应先等待大模型规划")

    monkeypatch.setattr(planner, "_llm_plan", should_not_call_llm)
    calls = planner.plan("请为当前教材专题设计一项课后学习任务", "teacher", context)

    assert [call.name for call in calls] == ["inspect_context", "draft_assignment"]

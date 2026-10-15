"""Acceptance contracts for multi-deliverable teaching workflows."""

from datetime import timedelta, timezone
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.core.security import create_access_token, hash_password
from app.core.time import utc_now
from app.models.agent_execution import AgentExecution
from app.models.course import Course
from app.models.chapter import Chapter
from app.models.review_practice import ReviewPractice
from app.models.teacher_assignment import TeacherAssignment
from app.models.user import User
from app.models.learning_task import LearningEvent
from app.models.study_note import StudyNote
from app.schemas.ai import AiWorkspaceContextData
from app.schemas.assignment import AssignmentCreate
from app.services.agent_execution_service import AgentExecutionService
from app.services.assignment_service import AssignmentService
from app.services.study_service import StudyService
from app.services.planning_agent import PlanningAgent, ToolCall


def context(db, role="student"):
    user = User(username="goal_" + role, password_hash=hash_password("test-pass-123"), role=role)
    course = Course(name="目标验收教材", description="测试")
    db.add_all([user, course]); db.flush()
    chapter = Chapter(course_id=course.id, title="理论与实践", sort_order=1,
                      content="理论联系实际是重要的学习方法。应当理解理论内涵，用可核验的事实形成分析。")
    db.add(chapter); db.commit()
    return user, course, chapter, {"Authorization": "Bearer " + create_access_token(str(user.id))}


def run(client, headers, course, chapter, question, role="student"):
    response = client.post("/api/v1/ai/workspace/agent/stream", headers=headers, json={
        "course_id": course.id, "chapter_id": chapter.id, "role": role,
        "learning_stage": "review", "question": question,
    })
    assert response.status_code == 200
    return response


def test_note_and_sources_are_delivered_then_completed_only_after_real_save(client, db):
    user, course, chapter, headers = context(db)
    client.put(f"/api/v1/study/notes/{chapter.id}", headers=headers, json={"content": "<p>我的已有理解。</p>"})
    response = run(client, headers, course, chapter, "请完善笔记并补充教材原文引用")
    execution = db.scalar(select(AgentExecution).order_by(AgentExecution.id.desc()))
    assert execution.status == "waiting_user_action"
    draft = next(item for item in execution.tool_results if item["tool"] == "draft_note_improvement")
    assert draft["data"]["draft_content"]
    assert draft["data"]["sources"][0]["chapter_id"] == chapter.id
    assert execution.result["goals"][0]["status"] == "draft_ready"
    assert "event: sources\ndata: [{" in response.text
    assert db.scalar(select(func.count()).select_from(LearningEvent).where(
        LearningEvent.user_id == user.id, LearningEvent.event_type == "ai_assist_used")) == 1
    unchanged = client.put(f"/api/v1/study/notes/{chapter.id}", headers=headers, json={
        "content": "<p>我的已有理解。</p>", "agent_execution_id": execution.id,
    })
    assert unchanged.status_code == 400
    assert client.get(f"/api/v1/ai/workspace/agent/executions/{execution.id}", headers=headers).json()["data"]["status"] == "waiting_user_action"
    saved = client.put(f"/api/v1/study/notes/{chapter.id}", headers=headers, json={
        "content": "<p>我的已有理解。</p><p>补充：理论联系实际，需要核对教材依据。</p>", "agent_execution_id": execution.id,
    })
    assert saved.status_code == 200
    data = client.get(f"/api/v1/ai/workspace/agent/executions/{execution.id}", headers=headers).json()["data"]
    assert data["status"] == "completed"
    assert data["result"]["goals"][0]["resource_id"] == saved.json()["data"]["id"]
    assert data["result"]["actions"] == []
    assert "草稿尚未保存" not in data["result"]["summary"]
    assert "实际保存内容以笔记空间为准" in data["result"]["summary"]
    duplicate = client.put(f"/api/v1/study/notes/{chapter.id}", headers=headers, json={
        "content": "不应重复追加", "agent_execution_id": execution.id,
    })
    assert duplicate.status_code == 409
    assert client.get(f"/api/v1/study/notes/{chapter.id}", headers=headers).json()["data"]["content"] == saved.json()["data"]["content"]
    assert db.scalar(select(func.count()).select_from(LearningEvent).where(
        LearningEvent.user_id == user.id, LearningEvent.event_type == "note_saved")) == 2


def test_goal_verification_catches_omitted_deliverable(client, db, monkeypatch):
    _, course, chapter, headers = context(db)
    monkeypatch.setattr(PlanningAgent, "plan", lambda *args: [ToolCall("inspect_context", "确认范围")])
    run(client, headers, course, chapter, "请完善笔记并补充教材引用")
    execution = db.scalar(select(AgentExecution))
    assert execution.status == "failed"
    assert execution.result["verified"] is False
    assert execution.result["goals"][0]["status"] == "unmet"


def test_assignment_and_rubric_share_handoff_and_publish_record(client, db):
    _, course, chapter, headers = context(db, "teacher")
    response = run(client, headers, course, chapter, "请生成课后任务并配评分量规", "teacher")
    execution = db.scalar(select(AgentExecution))
    assert execution.status == "waiting_user_action"
    assert {goal["key"] for goal in execution.result["goals"]} == {"goal_assignment", "goal_rubric"}
    actions = execution.result["actions"]
    assert len(actions) == 1
    assert actions[0]["draft"] and actions[0]["rubric"]
    assert response.text.count("event: action\n") == 1
    payload = {**actions[0]["draft"], "due_time": (utc_now() + timedelta(days=2)).isoformat() + "Z",
               "agent_execution_id": execution.id}
    rejected = client.post("/api/v1/assignments", headers=headers, json=payload)
    assert rejected.status_code == 400
    assert db.scalar(select(func.count()).select_from(TeacherAssignment)) == 0
    payload["rubric"] = actions[0]["rubric"]
    created = client.post("/api/v1/assignments", headers=headers, json=payload)
    assert created.status_code == 201
    data = client.get(f"/api/v1/ai/workspace/agent/executions/{execution.id}", headers=headers).json()["data"]
    assert data["status"] == "completed"
    assert all(goal["status"] == "completed" for goal in data["result"]["goals"])
    assert all(goal["resource_id"] == created.json()["data"]["id"] for goal in data["result"]["goals"])


def test_plan_uses_answered_incorrect_practice_and_real_stage(client, db):
    user, course, chapter, headers = context(db)
    db.add_all([
        ReviewPractice(user_id=user.id, course_id=course.id, chapter_id=chapter.id,
                       question="为什么理论必须联系实际？", choices=[], answer_index=0,
                       is_correct=False, answered_at=utc_now()),
        ReviewPractice(user_id=user.id, course_id=course.id, chapter_id=chapter.id,
                       question="尚未作答的题", choices=[], answer_index=0),
    ])
    db.commit()
    run(client, headers, course, chapter, "根据我的进度安排复习计划")
    execution = db.scalar(select(AgentExecution))
    data = next(item["data"] for item in execution.tool_results if item["tool"] == "draft_study_plan")
    assert data["incorrect_count"] == 1
    assert data["steps"][0]["basis"] == "incorrect_practice"
    assert "为什么理论必须联系实际" in data["steps"][0]["title"]
    assert any("/review" in item["href"] for item in data["steps"] if item["basis"] == "task_points")
    assert execution.status == "completed"


def test_note_handoff_cannot_be_claimed_by_another_user_or_chapter(client, db):
    _, course, chapter, headers = context(db)
    run(client, headers, course, chapter, "请完善笔记")
    execution = db.scalar(select(AgentExecution))
    other = User(username="other_goal_student", password_hash=hash_password("test-pass-123"), role="student")
    second_chapter = Chapter(course_id=course.id, title="另一章", content="正文", sort_order=2)
    db.add_all([other, second_chapter]); db.commit()
    other_headers = {"Authorization": "Bearer " + create_access_token(str(other.id))}
    response = client.put(f"/api/v1/study/notes/{chapter.id}", headers=other_headers,
                          json={"content": "冒领草案", "agent_execution_id": execution.id})
    assert response.status_code == 404
    response = client.put(f"/api/v1/study/notes/{second_chapter.id}", headers=headers,
                          json={"content": "跨专题保存", "agent_execution_id": execution.id})
    assert response.status_code == 400


def test_resume_retains_previously_generated_note_and_sources(client, db):
    _, course, chapter, headers = context(db)
    run(client, headers, course, chapter, "请完善笔记并补充教材引用")
    execution = db.scalar(select(AgentExecution))
    response = client.post("/api/v1/ai/workspace/agent/stream", headers=headers, json={
        "execution_id": execution.id, "role": "student", "question": execution.question,
    })
    assert response.status_code == 200
    data = client.get(f"/api/v1/ai/workspace/agent/executions/{execution.id}", headers=headers).json()["data"]
    assert data["status"] == "waiting_user_action"
    assert len(data["tool_results"]) == 3
    assert data["result"]["sources"]
    assert data["result"]["goals"][0]["passed"] is True


@pytest.mark.parametrize("role", ["student", "teacher"])
def test_completed_handoff_reopen_is_read_only(client, db, role):
    _, course, chapter, headers = context(db, role)
    question = "请完善笔记并补充教材引用" if role == "student" else "生成课后任务并配评分量规"
    run(client, headers, course, chapter, question, role)
    execution = db.scalar(select(AgentExecution))
    if role == "student":
        response = client.put(f"/api/v1/study/notes/{chapter.id}", headers=headers,
                              json={"content": "已审阅的笔记补充。", "agent_execution_id": execution.id})
        assert response.status_code == 200
    else:
        action = execution.result["actions"][0]
        response = client.post("/api/v1/assignments", headers=headers, json={
            **action["draft"], "rubric": action["rubric"], "agent_execution_id": execution.id,
            "due_time": (utc_now() + timedelta(days=2)).isoformat() + "Z",
        })
        assert response.status_code == 201
    db.refresh(execution)
    before = deepcopy(execution.result)
    history = deepcopy(execution.tool_results)
    finished_time = execution.finished_time
    for text in (question, "请继续这个任务并给出下一步建议"):
        response = client.post("/api/v1/ai/workspace/agent/stream", headers=headers,
                               json={"execution_id": execution.id, "role": role, "question": text})
        assert response.status_code == 200
        assert "event: action\n" not in response.text
        db.refresh(execution)
        assert execution.status == "completed"
        assert execution.result == before
        assert execution.tool_results == history
        assert execution.finished_time == finished_time


@pytest.mark.parametrize("kind", ["note", "assignment"])
def test_handoff_failure_rolls_back_record_and_agent_state(client, db, monkeypatch, kind):
    role = "student" if kind == "note" else "teacher"
    user, course, chapter, headers = context(db, role)
    if kind == "note":
        assert client.put(f"/api/v1/study/notes/{chapter.id}", headers=headers,
                          json={"content": "<p>必须保留的原始笔记。</p>"}).status_code == 200
    run(client, headers, course, chapter, "完善笔记" if kind == "note" else "生成课后任务并配评分量规", role)
    execution = db.scalar(select(AgentExecution))
    original_finish = AgentExecutionService.finish_handoff

    def fail_after_staging(self, *args, **kwargs):
        original_finish(self, *args, **kwargs)
        raise RuntimeError("模拟提交前的业务异常")

    monkeypatch.setattr(AgentExecutionService, "finish_handoff", fail_after_staging)
    if kind == "note":
        path = f"/api/v1/study/notes/{chapter.id}"
        payload = {"content": "不应残留的草稿", "agent_execution_id": execution.id}
        request = client.put
    else:
        action = execution.result["actions"][0]
        path = "/api/v1/assignments"
        payload = {**action["draft"], "rubric": action["rubric"], "agent_execution_id": execution.id,
                   "due_time": (utc_now() + timedelta(days=2)).isoformat() + "Z"}
        request = client.post
    with pytest.raises(RuntimeError, match="模拟提交前"):
        request(path, headers=headers, json=payload)
    db.expire_all()
    assert execution.status == "waiting_user_action"
    assert not execution.result.get("saved_resources")
    if kind == "note":
        assert db.scalar(select(StudyNote).where(StudyNote.user_id == user.id)).content == "<p>必须保留的原始笔记。</p>"
        assert db.scalar(select(func.count()).select_from(LearningEvent).where(
            LearningEvent.user_id == user.id, LearningEvent.event_type == "note_saved")) == 1
    else:
        assert db.scalar(select(func.count()).select_from(TeacherAssignment)) == 0
    monkeypatch.setattr(AgentExecutionService, "finish_handoff", original_finish)
    assert request(path, headers=headers, json=payload).status_code in (200, 201)
    assert request(path, headers=headers, json=payload).status_code == 409


@pytest.mark.parametrize("kind", ["note", "assignment"])
def test_concurrent_handoff_only_one_submission_wins(tmp_path, kind):
    """Two real DB connections race the same execution, without an in-process lock."""
    engine = create_engine(f"sqlite:///{tmp_path / 'concurrent.db'}", connect_args={"check_same_thread": False, "timeout": 10})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    role = "student" if kind == "note" else "teacher"
    with sessions() as db:
        user, course, chapter, _ = context(db, role)
        user_id, course_id, chapter_id = user.id, course.id, chapter.id
        service = AgentExecutionService(db, user)
        execution = service.create(role=role, intent="test", question="测试草案",
                                   context=AiWorkspaceContextData(course_id=course_id, chapter_id=chapter_id))
        execution_id = execution.id
        execution.tool_results = [{"tool": "draft_note_improvement" if kind == "note" else "draft_assignment",
                                   "status": "advice_ready", "data": {}}]
        service.advice_ready(execution, {"goals": [{"key": "goal_note" if kind == "note" else "goal_assignment",
                                                    "status": "draft_ready"}]})
    barrier = Barrier(2)

    def submit(index):
        with sessions() as db:
            user = db.get(User, user_id)
            service = AgentExecutionService(db, user)
            barrier.wait(timeout=10)
            try:
                execution = service.validate_handoff(execution_id, kind=kind, course_id=course_id,
                                                       chapter_id=chapter_id, content=f"审阅后笔记{index}")
                if kind == "note":
                    resource = StudyService(db).save_note(user_id, chapter_id, f"审阅后笔记{index}", commit=False)
                else:
                    resource = AssignmentService(db).create(user_id, AssignmentCreate(
                        course_id=course_id, chapter_id=chapter_id, learning_stage="review", task_kind="note",
                        title=f"并发任务{index}", due_time=(utc_now() + timedelta(days=2)).replace(tzinfo=timezone.utc),
                    ), commit=False)
                service.finish_handoff(execution, kind=kind, resource_id=resource.id)
                db.commit()
                return 200
            except HTTPException as exc:
                db.rollback()
                return exc.status_code
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(submit, [1, 2])) == [200, 409]
        with sessions() as db:
            model = StudyNote if kind == "note" else TeacherAssignment
            assert db.scalar(select(func.count()).select_from(model)) == 1
            execution = db.get(AgentExecution, execution_id)
            assert execution.status == "completed"
            assert len(execution.result["saved_resources"]) == 1
    finally:
        engine.dispose()

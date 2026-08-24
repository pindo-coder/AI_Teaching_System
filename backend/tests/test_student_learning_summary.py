from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.core.time import BUSINESS_TIMEZONE
from app.models.chapter import Chapter
from app.models.course import Course
from app.models.learning_task import LearningEvent, UserTaskProgress
from app.models.user import User
from app.schemas.task import LearningEventCreate
from app.services.agent_context_service import AgentContextService
from app.services.planning_agent import PlanningAgent, ToolCall
from app.services.learning_service import LearningService
from app.services.student_learning_summary_service import StudentLearningSummaryService
from app.services.task_service import TaskService


def _student_context(db: Session) -> tuple[User, User, Course, Chapter]:
    student = User(username="summary_student", password_hash=hash_password("test-pass-123"), role="student")
    other = User(username="summary_other", password_hash=hash_password("test-pass-123"), role="student")
    course = Course(name="思想道德与法治", description="test")
    db.add_all([student, other, course])
    db.flush()
    chapter = Chapter(course_id=course.id, title="坚定理想信念", content="正文", sort_order=1)
    db.add(chapter)
    db.commit()
    return student, other, course, chapter


def test_partial_task_progress_is_weighted_and_ai_needs_follow_up_evidence(db: Session) -> None:
    student, _, course, chapter = _student_context(db)
    service = TaskService(db)

    reading = service.record(student.id, LearningEventCreate(
        course_id=course.id, chapter_id=chapter.id, learning_stage="preview",
        event_type="reading_progress", event_data={"percent": 40},
    ))
    assert reading.progress == 18
    dashboard = LearningService(db).dashboard(student)
    assert dashboard.overall_progress == 18
    assert dashboard.learning_status == "in_progress"
    assert dashboard.stage_footprints[0].activities[0].learning_stage == "preview"

    ai_only = service.record(student.id, LearningEventCreate(
        course_id=course.id, chapter_id=chapter.id, learning_stage="preview",
        event_type="ai_assist_used", event_data={"task_type": "preview_questions"},
    ))
    ai_task = next(item for item in ai_only.tasks if item.task_type == "ai_preview")
    assert ai_task.status == "in_progress"
    assert ai_task.progress_value == 50
    assert ai_only.progress == 28

    with_follow_up = service.record(student.id, LearningEventCreate(
        course_id=course.id, chapter_id=chapter.id, learning_stage="preview",
        event_type="question_submitted", event_data={"count": 1},
    ))
    ai_task = next(item for item in with_follow_up.tasks if item.task_type == "ai_preview")
    assert ai_task.status == "completed"
    assert ai_task.evidence_summary == "已在 AI 辅助后补充自主学习证据"


def test_seven_day_summary_obeys_time_window_and_user_isolation(db: Session) -> None:
    student, other, course, chapter = _student_context(db)
    now = datetime(2026, 8, 9, 20, 0, 0, tzinfo=BUSINESS_TIMEZONE)
    stored_now = datetime(2026, 8, 9, 12, 0, 0)
    db.add_all([
        LearningEvent(
            user_id=student.id, course_id=course.id, chapter_id=chapter.id, learning_stage="preview",
            event_type="chapter_opened", event_data={}, created_time=stored_now - timedelta(days=6),
        ),
        LearningEvent(
            user_id=student.id, course_id=course.id, chapter_id=chapter.id, learning_stage="preview",
            event_type="reading_progress", event_data={"percent": 80}, created_time=stored_now - timedelta(days=8),
        ),
        LearningEvent(
            user_id=other.id, course_id=course.id, chapter_id=chapter.id, learning_stage="preview",
            event_type="ai_assist_used", event_data={}, created_time=stored_now - timedelta(days=1),
        ),
    ])
    db.commit()

    summary = StudentLearningSummaryService(db).summarize(student.id, now=now)

    assert summary["active"]["course_count"] == 1
    assert summary["active"]["chapter_count"] == 1
    assert summary["learning_actions"]["events"] == {"打开专题": 1}
    assert summary["learning_actions"]["ai_assist_events"] == 0
    assert summary["period"]["end"] == "2026-08-09T12:00:00Z"


def test_seven_day_summary_lists_verified_completions_by_completed_time(db: Session) -> None:
    student, _, course, chapter = _student_context(db)
    now = datetime(2026, 8, 9, 20, 0, 0, tzinfo=BUSINESS_TIMEZONE)
    stored_now = datetime(2026, 8, 9, 12, 0, 0)
    tasks = TaskService(db).ensure_tasks(course.id, chapter.id, "preview")
    db.add_all([
        UserTaskProgress(
            user_id=student.id,
            task_point_id=tasks[0].id,
            status="completed",
            progress_value=100,
            evidence_summary="已查看专题导览",
            completed_time=stored_now - timedelta(days=1),
            # 即使更新时间不在窗口内，也应按真实完成时间纳入。
            updated_time=stored_now - timedelta(days=8),
        ),
        UserTaskProgress(
            user_id=student.id,
            task_point_id=tasks[1].id,
            status="completed",
            progress_value=100,
            evidence_summary="历史完成",
            completed_time=stored_now - timedelta(days=8),
            # 历史完成项即使最近被同步，也不能误报成最近完成。
            updated_time=stored_now - timedelta(days=1),
        ),
        UserTaskProgress(
            user_id=student.id,
            task_point_id=tasks[2].id,
            status="in_progress",
            progress_value=50,
            evidence_summary="已使用 AI 辅助",
            updated_time=stored_now - timedelta(hours=3),
        ),
    ])
    db.commit()

    summary = StudentLearningSummaryService(db).summarize(student.id, now=now)

    assert summary["task_points"]["completed"] == 1
    assert summary["task_points"]["in_progress"] == 1
    assert summary["task_points"]["completed_items"] == [{
        "task_point_id": tasks[0].id,
        "course_id": course.id,
        "course_name": course.name,
        "chapter_id": chapter.id,
        "chapter_title": chapter.title,
        "learning_stage": "preview",
        "task_type": tasks[0].task_type,
        "title": tasks[0].title,
        "completed_time": "2026-08-08T12:00:00Z",
        "evidence_summary": "已查看专题导览",
    }]
    assert summary["task_points"]["completed_items_truncated"] is False


def test_planning_prompt_renders_json_example_without_treating_braces_as_variables() -> None:
    messages = PlanningAgent._planning_prompt().format_messages(
        role="student",
        question="请汇总近 7 天学习情况",
        context="{}",
        tools="{}",
    )

    assert '{"tools":[{"name":"工具名"' in str(messages[0].content)


def test_recent_summary_tool_is_student_only(db: Session, monkeypatch) -> None:
    student, _, _, _ = _student_context(db)
    context = AgentContextService(db, student).resolve()
    planner = PlanningAgent(db, student)

    def should_not_call_llm(*_args, **_kwargs):
        raise AssertionError("明确的近 7 天总结不应调用外部模型规划")

    monkeypatch.setattr(planner, "_llm_plan", should_not_call_llm)
    for question in (
        "请给我近 7 天个人学习总结",
        "我最近完成了哪些任务？",
        "汇总近期做完的任务",
    ):
        plan = planner.plan(question, "student", context)
        assert [call.name for call in plan] == ["summarize_recent_learning"]
    result = planner.invoke(
        ToolCall("summarize_recent_learning", "汇总近 7 天个人学习情况"),
        question="请给我近 7 天个人学习总结", role="student", context=context,
    )
    assert result.status == "completed"
    assert "近 7 天" in result.text
    assert "具体完成" in result.text
    assert result.action["href"] == "/assignments"

    teacher = User(username="summary_teacher", password_hash=hash_password("test-pass-123"), role="teacher")
    db.add(teacher)
    db.commit()
    denied = PlanningAgent(db, teacher).invoke(
        ToolCall("summarize_recent_learning", "读取学生个人总结"),
        question="读取学生总结", role="teacher", context=AgentContextService(db, teacher).resolve(),
    )
    assert denied.status == "failed"
    assert denied.data == {"denied_tool": "summarize_recent_learning", "role": "teacher"}

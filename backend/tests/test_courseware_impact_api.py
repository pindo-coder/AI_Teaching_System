from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.models.agent_run import AgentRun
from app.models.authority_discovery import (
    AuthoritySourceRegistry,
    MaterialCandidate,
    PolicyChange,
)
from app.models.chapter import Chapter
from app.models.course import Course
from app.models.user import User


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


def _context(db: Session) -> tuple[User, User, AgentRun, PolicyChange]:
    teacher = User(
        username="impact_teacher",
        password_hash=hash_password("secure-pass-123"),
        role="teacher",
        approval_status="approved",
    )
    stranger = User(
        username="impact_stranger",
        password_hash=hash_password("secure-pass-456"),
        role="teacher",
        approval_status="approved",
    )
    course = Course(name="课件影响测试课程", description="测试")
    db.add_all([teacher, stranger, course])
    db.flush()
    chapter = Chapter(
        course_id=course.id,
        title="办理流程",
        content="通知自发布之日起3个工作日内反馈。",
        sort_order=1,
    )
    registry = AuthoritySourceRegistry(
        name="测试权威来源",
        domain="old.example.com",
        entry_url="https://old.example.com",
    )
    db.add_all([chapter, registry])
    db.flush()
    candidate = MaterialCandidate(
        source_registry_id=registry.id,
        title="办理流程更新",
        source_url="https://new.example.com/policy",
        canonical_url="https://new.example.com/policy",
        source_level="A",
    )
    db.add(candidate)
    db.flush()
    change = PolicyChange(
        candidate_id=candidate.id,
        change_type="content",
        old_source_title="办理流程旧版",
        old_source_url="https://old.example.com/policy",
        new_source_title="办理流程新版",
        new_source_url="https://new.example.com/policy",
        old_excerpt="通知自发布之日起3个工作日内反馈。",
        new_excerpt="通知自发布之日起5个工作日内反馈。",
        review_status="confirmed",
        kb_sync_status="synced",
        affected_course_ids=[course.id],
        affected_chapter_ids=[chapter.id],
    )
    run = AgentRun(
        created_by=teacher.id,
        agent_type="teacher_lesson_prep",
        status="completed",
        course_id=course.id,
        chapter_id=chapter.id,
        evidence_snapshot=[
            {
                "source_type": "policy",
                "source_title": "办理流程旧版",
                "course_id": course.id,
                "chapter_id": chapter.id,
                "excerpt": "通知自发布之日起3个工作日内反馈。",
                "source_url": "https://old.example.com/policy",
            }
        ],
        output_data={
            "artifact_bundle": {
                "ppt": {
                    "revision_id": "rev-current",
                    "slides": [
                        {
                            "title": "办理流程",
                            "takeaway": "按通知要求及时反馈",
                            "bullets": ["自发布之日起3个工作日内反馈"],
                            "evidence_refs": ["资料1"],
                        }
                    ],
                }
            }
        },
    )
    db.add_all([change, run])
    db.commit()
    db.refresh(change)
    db.refresh(run)
    return teacher, stranger, run, change


def test_courseware_impact_rejects_non_owner(
    client: TestClient,
    db: Session,
) -> None:
    _, stranger, run, change = _context(db)
    url = f"/api/v1/agent/runs/{run.id}/courseware-impact"

    assert client.get(url, headers=_headers(stranger)).status_code == 403
    draft = client.post(
        f"{url}/draft",
        headers=_headers(stranger),
        json={
            "change_id": change.id,
            "slide_index": 0,
            "expected_revision_id": "rev-current",
        },
    )
    assert draft.status_code == 403


def test_courseware_impact_draft_rejects_stale_revision(
    client: TestClient,
    db: Session,
) -> None:
    teacher, _, run, change = _context(db)

    response = client.post(
        f"/api/v1/agent/runs/{run.id}/courseware-impact/draft",
        headers=_headers(teacher),
        json={
            "change_id": change.id,
            "slide_index": 0,
            "expected_revision_id": "rev-stale",
        },
    )

    assert response.status_code == 409


def test_courseware_impact_returns_offline_demo_draft(
    client: TestClient,
    db: Session,
) -> None:
    teacher, _, run, change = _context(db)
    impact_url = f"/api/v1/agent/runs/{run.id}/courseware-impact"

    record = client.get(impact_url, headers=_headers(teacher))
    assert record.status_code == 200
    record_data = record.json()["data"]["record"]
    assert record_data["status"] == "ready"
    assert record_data["revision_id"] == "rev-current"
    assert record_data["impacts"][0]["change_id"] == change.id

    draft = client.post(
        f"{impact_url}/draft",
        headers=_headers(teacher),
        json={
            "change_id": change.id,
            "slide_index": 0,
            "expected_revision_id": "rev-current",
        },
    )
    assert draft.status_code == 200
    data = draft.json()["data"]
    assert data["needs_teacher_review"] is True
    assert "离线演示" in data["draft_text"]
    assert data["record"]["revision_id"] == "rev-current"
    assert data["record"]["impacts"][0]["new_source_url"] == "https://new.example.com/policy"
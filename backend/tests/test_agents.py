from datetime import date
from io import BytesIO
from zipfile import ZipFile

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.models.chapter import Chapter
from app.models.course import Course
from app.models.teaching_class import (
    AcademicTerm,
    ClassMembership,
    CourseSubject,
    TeachingClass,
    TeachingClassMaterial,
    TeachingClassTeacher,
)
from app.models.user import User
from app.services.agent_service import (
    _prepare_ppt_canvas_for_slide,
    _sanitize_ppt_design,
)
from app.services.ppt_multimodal_service import PptMultimodalService


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


def _context(db: Session) -> tuple[User, User, Course, Chapter]:
    teacher = User(
        username="agent_teacher",
        password_hash=hash_password("secure-pass-123"),
        role="teacher",
        approval_status="approved",
    )
    student = User(
        username="agent_student",
        password_hash=hash_password("secure-pass-123"),
        role="student",
    )
    course = Course(name="Agent 备课测试课程", description="测试")
    db.add_all([teacher, student, course])
    db.flush()
    chapter = Chapter(
        course_id=course.id,
        title="全过程人民民主",
        content="全过程人民民主是社会主义民主政治的本质属性。",
        sort_order=1,
    )
    db.add(chapter)
    db.commit()
    return teacher, student, course, chapter


def _payload(course: Course, chapter: Chapter) -> dict:
    return {
        "agent_type": "teacher_lesson_prep",
        "course_id": course.id,
        "chapter_id": chapter.id,
        "teaching_class_id": None,
        "input": {
            "lesson_hours": 2,
            "student_level": "本科生",
            "teaching_goal": "理解全过程人民民主的基本内涵",
            "output_types": ["outline"],
        },
    }


def _teaching_class(
    db: Session,
    teacher: User,
    student: User,
    course: Course,
) -> TeachingClass:
    subject = CourseSubject(name="思政课程", code="IDEOLOGY")
    term = AcademicTerm(
        name="2026 秋季",
        start_date=date(2026, 9, 1),
        end_date=date(2027, 1, 20),
        is_current=True,
    )
    db.add_all([subject, term])
    db.flush()
    item = TeachingClass(
        subject_id=subject.id,
        term_id=term.id,
        name="思政一班",
        code="SZ01",
        owner_id=teacher.id,
        status="active",
        join_code="AGENT001",
    )
    db.add(item)
    db.flush()
    db.add_all([
        TeachingClassTeacher(
            teaching_class_id=item.id,
            user_id=teacher.id,
            teacher_role="primary",
        ),
        TeachingClassMaterial(
            teaching_class_id=item.id,
            course_id=course.id,
            material_role="primary",
            sort_order=0,
        ),
        ClassMembership(
            teaching_class_id=item.id,
            user_id=student.id,
            status="active",
            join_method="roster",
        ),
    ])
    db.commit()
    return item


def _pptx_template_bytes() -> bytes:
    target = BytesIO()
    with ZipFile(target, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr(
            "ppt/presentation.xml",
            (
                '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
                '<p:sldSz cx="12192000" cy="6858000" />'
                "</p:presentation>"
            ),
        )
        archive.writestr("ppt/slides/slide1.xml", "<p:sld xmlns:p=\"http://schemas.openxmlformats.org/presentationml/2006/main\" />")
        archive.writestr(
            "ppt/theme/theme1.xml",
            (
                '<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                '<a:themeElements><a:clrScheme name="Custom">'
                '<a:dk1><a:srgbClr val="162033"/></a:dk1>'
                '<a:lt1><a:srgbClr val="FAF7F0"/></a:lt1>'
                '<a:accent1><a:srgbClr val="A32638"/></a:accent1>'
                '<a:accent2><a:srgbClr val="214F86"/></a:accent2>'
                '</a:clrScheme></a:themeElements>'
                "</a:theme>"
            ),
        )
    return target.getvalue()


def test_personalized_ppt_design_canvas_is_validated() -> None:
    design, pages = _sanitize_ppt_design(
        {
            "design": {
                "name": "人民当家作主的制度之路",
                "concept": "以道路和节点表现制度发展。",
                "palette": {"primary": "#8f2638", "accent": "not-a-color"},
            },
            "pages": [
                {
                    "index": 0,
                    "background": "primary",
                    "elements": [
                        {
                            "type": "shape",
                            "x": -20,
                            "y": 2,
                            "w": 180,
                            "h": 120,
                            "fill": "accent",
                        },
                        {
                            "type": "text",
                            "source": "title",
                            "style": "hero",
                            "x": 8,
                            "y": 16,
                            "w": 70,
                            "h": 24,
                            "color": "inverse",
                        },
                        {
                            "type": "text",
                            "source": "takeaway",
                            "style": "quote",
                            "x": 8,
                            "y": 52,
                            "w": 72,
                            "h": 18,
                            "color": "inverse",
                        },
                        {"type": "text", "source": "invented.fact", "x": 1, "y": 1},
                    ],
                }
            ],
        },
        1,
    )
    assert design["palette"]["primary"] == "8F2638"
    assert design["palette"]["accent"] == "D3A23A"
    assert len(pages[0]) == 3
    assert pages[0][0]["x"] == 0
    assert pages[0][0]["y"] == 6


def test_ppt_canvas_rejects_blank_decorative_layout_and_keeps_valid_content() -> None:
    slide = {
        "title": "新时代坚持和发展中国特色社会主义",
        "takeaway": "明确新时代坚持和发展中国特色社会主义的核心课题。",
        "bullets": ["理解理论逻辑", "把握实践要求"],
    }
    decorative = [
        {"type": "text", "source": "title"},
        {"type": "text", "source": "bullet:9"},
        {"type": "shape", "source": ""},
    ]
    prepared, diagnostics = _prepare_ppt_canvas_for_slide(slide, decorative, 0)
    assert prepared is None
    assert diagnostics["recovered_with_safe_layout"] is True

    complete = [
        {"type": "text", "source": "title"},
        {"type": "text", "source": "takeaway"},
        {"type": "text", "source": "bullet:0"},
        {"type": "text", "source": "bullet:9"},
        {"type": "shape", "source": ""},
    ]
    prepared, diagnostics = _prepare_ppt_canvas_for_slide(slide, complete, 0)
    assert prepared is not None
    assert [item.get("source") for item in prepared] == [
        "title",
        "takeaway",
        "bullet:0",
        "",
    ]
    assert diagnostics["recovered_with_safe_layout"] is False


def test_teacher_lesson_prep_waits_for_evidence_confirmation_then_generates_outline(
    client: TestClient, db: Session
) -> None:
    teacher, _, course, chapter = _context(db)
    created = client.post(
        "/api/v1/agent/runs",
        headers=_headers(teacher),
        json=_payload(course, chapter),
    )
    assert created.status_code == 200
    run = created.json()["data"]
    assert run["status"] == "waiting_confirmation"
    assert run["current_step"] == 1
    assert len(run["evidence_snapshot"]) == 1
    assert run["steps"][0]["status"] == "completed"
    assert run["steps"][1]["status"] == "completed"
    assert run["steps"][2]["status"] == "pending"

    confirmed = client.post(
        f"/api/v1/agent/runs/{run['id']}/confirm",
        headers=_headers(teacher),
        json={"action": "approve_evidence"},
    )
    assert confirmed.status_code == 200

    detail = client.get(
        f"/api/v1/agent/runs/{run['id']}",
        headers=_headers(teacher),
    )
    assert detail.status_code == 200
    completed = detail.json()["data"]
    assert completed["status"] == "completed"
    assert completed["output_data"]["outline"]["title"].endswith("教学课纲")
    assert sum(
        item["duration_minutes"]
        for item in completed["output_data"]["outline"]["teaching_flow"]
    ) == 90
    assert completed["steps"][2]["status"] == "completed"

    events = client.get(
        f"/api/v1/agent/runs/{run['id']}/events",
        headers=_headers(teacher),
    )
    assert events.status_code == 200
    assert "event: snapshot" in events.text
    assert "event: done" in events.text


def test_student_cannot_create_or_read_teacher_agent_runs(
    client: TestClient, db: Session
) -> None:
    teacher, student, course, chapter = _context(db)
    forbidden = client.post(
        "/api/v1/agent/runs",
        headers=_headers(student),
        json=_payload(course, chapter),
    )
    assert forbidden.status_code == 403

    run = client.post(
        "/api/v1/agent/runs",
        headers=_headers(teacher),
        json=_payload(course, chapter),
    ).json()["data"]
    assert client.get(
        f"/api/v1/agent/runs/{run['id']}",
        headers=_headers(student),
    ).status_code == 403


def test_waiting_agent_can_be_cancelled_and_retried(
    client: TestClient, db: Session
) -> None:
    teacher, _, course, chapter = _context(db)
    run = client.post(
        "/api/v1/agent/runs",
        headers=_headers(teacher),
        json=_payload(course, chapter),
    ).json()["data"]

    cancelled = client.post(
        f"/api/v1/agent/runs/{run['id']}/cancel",
        headers=_headers(teacher),
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["data"]["status"] == "cancelled"

    retried = client.post(
        f"/api/v1/agent/runs/{run['id']}/retry",
        headers=_headers(teacher),
    )
    assert retried.status_code == 200
    retried_data = retried.json()["data"]
    assert retried_data["status"] == "waiting_confirmation"
    assert retried_data["retry_of_run_id"] == run["id"]


def test_teacher_can_generate_preview_and_download_all_teaching_artifacts(
    client: TestClient, db: Session
) -> None:
    teacher, _, course, chapter = _context(db)
    run = client.post(
        "/api/v1/agent/runs",
        headers=_headers(teacher),
        json=_payload(course, chapter),
    ).json()["data"]
    client.post(
        f"/api/v1/agent/runs/{run['id']}/confirm",
        headers=_headers(teacher),
        json={"action": "approve_evidence"},
    )

    generated = client.post(
        f"/api/v1/agent/runs/{run['id']}/artifacts",
        headers=_headers(teacher),
        json={"output_types": ["ppt", "lesson_plan", "classroom_activities"]},
    )
    assert generated.status_code == 200
    detail = client.get(
        f"/api/v1/agent/runs/{run['id']}",
        headers=_headers(teacher),
    ).json()["data"]
    assert detail["status"] == "completed"
    assert detail["current_step"] == 3
    assert detail["steps"][3]["status"] == "completed"
    assert set(detail["output_data"]["artifacts"]) == {
        "ppt",
        "lesson_plan",
        "classroom_activities",
    }
    assert "storage_path" not in detail["output_data"]["artifacts"]["ppt"]
    assert detail["output_data"]["artifacts"]["ppt"]["slide_count"] >= 8
    assert len(detail["output_data"]["artifact_bundle"]["classroom_activities"]) >= 1
    ppt_slides = detail["output_data"]["artifact_bundle"]["ppt"]["slides"]
    ppt_design = detail["output_data"]["artifact_bundle"]["ppt"]["design"]
    ppt_quality = detail["output_data"]["artifact_bundle"]["ppt"]["quality_report"]
    assert ppt_design["status"] == "personalized"
    assert ppt_design["designed_pages"] == len(ppt_slides)
    assert all(len(slide.get("canvas") or []) >= 3 for slide in ppt_slides)
    assert 0 <= ppt_quality["score"] <= 100
    layouts = {slide["layout"] for slide in ppt_slides}
    assert {
        "title",
        "agenda",
        "question",
        "concept",
        "process",
        "comparison",
        "timeline",
        "discussion",
        "summary",
    }.issubset(layouts)
    for slide in ppt_slides:
        visible_text = " ".join(
            [
                slide.get("title", ""),
                slide.get("takeaway", ""),
                *slide.get("bullets", []),
            ]
        )
        assert "[资料" not in visible_text
        assert "资料依据" not in visible_text

    for key in ("ppt", "lesson_plan", "classroom_activities"):
        response = client.get(
            f"/api/v1/agent/runs/{run['id']}/artifacts/{key}/download",
            headers=_headers(teacher),
        )
        assert response.status_code == 200
        assert response.content.startswith(b"PK")

    revised = client.post(
        f"/api/v1/agent/runs/{run['id']}/ppt/slides/1/revise",
        headers=_headers(teacher),
        json={"instruction": "突出本页核心问题，减少说明文字", "mode": "both"},
    )
    assert revised.status_code == 200
    revised_data = revised.json()["data"]["output_data"]
    assert revised_data["ppt_versions"]
    assert (
        revised_data["artifact_bundle"]["ppt"]["slides"][1]["takeaway"]
        == "突出本页核心问题，减少说明文字"
    )
    version_id = revised_data["ppt_versions"][0]["version_id"]
    restored = client.post(
        f"/api/v1/agent/runs/{run['id']}/ppt/versions/restore",
        headers=_headers(teacher),
        json={"version_id": version_id},
    )
    assert restored.status_code == 200


def test_teacher_can_upload_and_select_ppt_style_template(
    client: TestClient,
    db: Session,
) -> None:
    teacher, _, course, chapter = _context(db)
    uploaded = client.post(
        "/api/v1/agent/ppt-templates",
        headers=_headers(teacher),
        data={"name": "校级公开课模板", "description": "红蓝主色"},
        files={
            "file": (
                "公开课模板.pptx",
                _pptx_template_bytes(),
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            )
        },
    )
    assert uploaded.status_code == 200
    template = uploaded.json()["data"]
    assert template["slide_count"] == 1
    assert template["aspect_ratio"] == "16:9"
    assert template["theme_data"]["palette"]["primary"] == "A32638"

    run = client.post(
        "/api/v1/agent/runs",
        headers=_headers(teacher),
        json=_payload(course, chapter),
    ).json()["data"]
    client.post(
        f"/api/v1/agent/runs/{run['id']}/confirm",
        headers=_headers(teacher),
        json={"action": "approve_evidence"},
    )
    generated = client.post(
        f"/api/v1/agent/runs/{run['id']}/artifacts",
        headers=_headers(teacher),
        json={
            "output_types": ["ppt"],
            "ppt_preferences": {
                "scenario": "open_lesson",
                "visual_style": "serious",
                "content_density": "standard",
                "min_slides": 9,
                "max_slides": 12,
                "include_interaction": True,
                "include_visuals": False,
                "template_id": template["id"],
            },
        },
    )
    assert generated.status_code == 200
    detail = client.get(
        f"/api/v1/agent/runs/{run['id']}",
        headers=_headers(teacher),
    ).json()["data"]
    assert detail["input_data"]["ppt_template_reference"]["name"] == "校级公开课模板"


def test_artifacts_require_an_existing_outline(client: TestClient, db: Session) -> None:
    teacher, _, course, chapter = _context(db)
    run = client.post(
        "/api/v1/agent/runs",
        headers=_headers(teacher),
        json=_payload(course, chapter),
    ).json()["data"]
    response = client.post(
        f"/api/v1/agent/runs/{run['id']}/artifacts",
        headers=_headers(teacher),
        json={"output_types": ["ppt"]},
    )
    assert response.status_code == 409


def test_exact_slide_count_and_multimodal_capability_fallback(
    client: TestClient,
    db: Session,
) -> None:
    teacher, _, course, chapter = _context(db)
    run = client.post(
        "/api/v1/agent/runs",
        headers=_headers(teacher),
        json=_payload(course, chapter),
    ).json()["data"]
    client.post(
        f"/api/v1/agent/runs/{run['id']}/confirm",
        headers=_headers(teacher),
        json={"action": "approve_evidence"},
    )
    generated = client.post(
        f"/api/v1/agent/runs/{run['id']}/artifacts",
        headers=_headers(teacher),
        json={
            "output_types": ["ppt"],
            "ppt_preferences": {
                "slide_count": 7,
                "include_visuals": False,
            },
        },
    )
    assert generated.status_code == 200
    detail = client.get(
        f"/api/v1/agent/runs/{run['id']}",
        headers=_headers(teacher),
    ).json()["data"]
    assert len(detail["output_data"]["artifact_bundle"]["ppt"]["slides"]) == 7
    assert detail["output_data"]["artifacts"]["ppt"]["slide_count"] == 7

    capability = client.get("/api/v1/agent/capabilities", headers=_headers(teacher))
    assert capability.status_code == 200
    assert capability.json()["data"]["ppt_multimodal_available"] is False


def test_multimodal_service_attaches_generated_asset(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "generated_artifact_directory", str(tmp_path))
    monkeypatch.setattr(settings, "ppt_multimodal_enabled", True)
    monkeypatch.setattr(settings, "ppt_multimodal_api_key", "test-key")
    monkeypatch.setattr(settings, "ppt_multimodal_model", "wan2.7-image")
    service = PptMultimodalService(99)
    monkeypatch.setattr(
        service,
        "_generate_one",
        lambda slide, design, index: {
            "storage_path": "99/ppt_visuals/slide-2.png",
            "file_name": "slide-2.png",
            "media_type": "image/png",
            "model": "wan2.7-image",
            "prompt": "symbolic scene",
        },
    )
    ppt = {
        "design": {"name": "专题视觉"},
        "slides": [
            {"canvas": [{"type": "text", "source": "title"}]},
            {
                "title": "青年担当",
                "takeaway": "把个人成长融入时代发展",
                "visual_prompt": "青年在城市与校园之间学习实践",
                "canvas": [
                    {"type": "text", "source": "title"},
                    {"type": "image", "source": "visual_asset"},
                ],
            },
        ],
    }
    enhanced = service.enhance(ppt)
    assert enhanced["multimodal"]["status"] == "completed"
    assert enhanced["multimodal"]["generated_count"] == 1
    assert enhanced["slides"][1]["visual_asset"]["model"] == "wan2.7-image"


def test_teacher_can_publish_ppt_and_discussion_to_students(
    client: TestClient,
    db: Session,
) -> None:
    teacher, student, course, chapter = _context(db)
    teaching_class = _teaching_class(db, teacher, student, course)
    payload = _payload(course, chapter)
    payload["teaching_class_id"] = teaching_class.id
    run = client.post(
        "/api/v1/agent/runs",
        headers=_headers(teacher),
        json=payload,
    ).json()["data"]
    client.post(
        f"/api/v1/agent/runs/{run['id']}/confirm",
        headers=_headers(teacher),
        json={"action": "approve_evidence"},
    )
    client.post(
        f"/api/v1/agent/runs/{run['id']}/artifacts",
        headers=_headers(teacher),
        json={
            "output_types": ["ppt", "classroom_activities"],
            "ppt_preferences": {"slide_count": 6},
        },
    )
    published = client.post(
        f"/api/v1/agent/runs/{run['id']}/publish",
        headers=_headers(teacher),
        json={
            "teaching_class_id": teaching_class.id,
            "title": "全过程人民民主教学成果",
            "description": "课堂课件与讨论。",
            "publish_ppt": True,
            "publish_discussions": True,
            "discussion_indices": [0],
            "confirmed": True,
        },
    )
    assert published.status_code == 200
    publication = published.json()["data"]
    assert publication["ppt_available"] is True
    assert len(publication["discussion_activity_ids"]) == 1

    student_list = client.get(
        "/api/v1/agent/publications",
        headers=_headers(student),
    )
    assert student_list.status_code == 200
    assert student_list.json()["data"][0]["id"] == publication["id"]
    downloaded = client.get(
        f"/api/v1/agent/publications/{publication['id']}/ppt",
        headers=_headers(student),
    )
    assert downloaded.status_code == 200
    assert downloaded.content.startswith(b"PK")

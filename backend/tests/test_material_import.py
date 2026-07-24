from io import BytesIO

from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.models.user import User
from app.models.material_import import MaterialImportBatch, MaterialImportItem
from app.services.material_import_service import preview_material_file, recover_material_batches
from app.services.material_center_service import _ArticleTextParser


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


def test_csv_preview_recognizes_nonstandard_columns_and_gbk() -> None:
    content = (
        "新闻标题,详情页,文章来源,公开日期,主题词\n"
        "推进中国式现代化,https://example.com/a,中央有关部门,2026年7月20日,中国式现代化、党的领导\n"
    ).encode("gb18030")
    preview = preview_material_file("materials.csv", content)
    sheet = preview.sheets[0]
    row = sheet.rows[0]
    assert row.source_title == "推进中国式现代化"
    assert row.source_url == "https://example.com/a"
    assert row.publisher == "中央有关部门"
    assert row.published_date == "2026-07-20"
    assert row.knowledge_tags == ["中国式现代化", "党的领导"]
    assert row.errors == []


def test_excel_preview_detects_header_after_description_rows() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "中央材料"
    sheet.append(["中央材料网址汇总"])
    sheet.append(["由管理员核验后导入"])
    sheet.append(["材料名称", "原文链接", "发布单位", "发布日期"])
    sheet.append(["全过程人民民主", "https://example.com/democracy", "中央有关部门", "2026-07-18"])
    stream = BytesIO()
    workbook.save(stream)
    preview = preview_material_file("materials.xlsx", stream.getvalue())
    assert preview.sheets[0].header_row == 3
    assert preview.sheets[0].rows[0].source_title == "全过程人民民主"


def test_preview_normalizes_metadata_to_persisted_field_lengths() -> None:
    long_title = "题" * 300
    long_publisher = "来源" * 150
    content = (
        "标题,网址,来源,适用范围,版本\n"
        f"{long_title},https://example.com/normalized,{long_publisher},{'范围' * 300},{'版本' * 80}\n"
    ).encode()
    row = preview_material_file("long-fields.csv", content).sheets[0].rows[0]
    assert len(row.source_title) == 255
    assert len(row.publisher) == 255
    assert len(row.applicable_scope) == 500
    assert len(row.version_label) == 100


def test_webpage_metadata_can_fill_optional_spreadsheet_fields() -> None:
    parser = _ArticleTextParser()
    parser.feed("""
        <html><head>
          <meta property="og:title" content="权威材料标题">
          <meta name="source" content="中央有关部门">
          <meta property="article:published_time" content="2026-07-20 10:00:00">
        </head><body><article><h1>页面标题</h1><p>正文内容</p></article></body></html>
    """)
    title, publisher, published_date = parser.metadata()
    assert title == "权威材料标题"
    assert publisher == "中央有关部门"
    assert published_date.isoformat() == "2026-07-20"


def test_batch_preview_api_is_admin_only(client: TestClient, db: Session) -> None:
    admin = User(username="batch_admin", password_hash=hash_password("password-123"), role="admin")
    teacher = User(username="batch_teacher", password_hash=hash_password("password-123"), role="teacher", approval_status="approved")
    db.add_all([admin, teacher]); db.commit(); db.refresh(admin); db.refresh(teacher)
    content = "标题,网址,发布机关,发布日期\n材料,https://example.com/a,中央有关部门,2026-07-20\n".encode()
    denied = client.post(
        "/api/v1/knowledge/materials/batch/preview", headers=_headers(teacher),
        files={"file": ("materials.csv", content, "text/csv")},
    )
    assert denied.status_code == 403
    response = client.post(
        "/api/v1/knowledge/materials/batch/preview", headers=_headers(admin),
        files={"file": ("materials.csv", content, "text/csv")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["sheets"][0]["rows"][0]["selected"] is True


def test_confirmed_batch_is_persisted_before_background_processing(
    client: TestClient, db: Session, monkeypatch,
) -> None:
    admin = User(username="batch_create_admin", password_hash=hash_password("password-123"), role="admin")
    db.add(admin); db.commit(); db.refresh(admin)
    monkeypatch.setattr(
        "app.api.v1.endpoints.knowledge.schedule_material_batch",
        lambda _batch_id, _bind: None,
    )
    response = client.post(
        "/api/v1/knowledge/materials/batches", headers=_headers(admin),
        json={
            "original_filename": "materials.xlsx", "sheet_name": "中央材料",
            "items": [{
                "row_number": 4, "source_url": "https://example.com/a",
                "source_title": "推进中国式现代化", "publisher": "中央有关部门",
                "published_date": "2026-07-20", "knowledge_tags": ["中国式现代化"],
            }],
        },
    )
    assert response.status_code == 201, response.text
    payload = response.json()["data"]
    assert payload["status"] == "queued"
    assert payload["total_count"] == 1
    assert payload["items"][0]["source_title"] == "推进中国式现代化"
    queried = client.get(
        f"/api/v1/knowledge/materials/batches/{payload['id']}", headers=_headers(admin)
    )
    assert queried.status_code == 200


def test_batch_history_is_scoped_to_current_admin(
    client: TestClient, db: Session, monkeypatch,
) -> None:
    first = User(username="history_admin_1", password_hash=hash_password("password-123"), role="admin")
    second = User(username="history_admin_2", password_hash=hash_password("password-123"), role="admin")
    db.add_all([first, second]); db.commit(); db.refresh(first); db.refresh(second)
    monkeypatch.setattr(
        "app.api.v1.endpoints.knowledge.schedule_material_batch",
        lambda _batch_id, _bind: None,
    )
    for user, title in ((first, "第一批"), (second, "第二批")):
        response = client.post(
            "/api/v1/knowledge/materials/batches", headers=_headers(user),
            json={"original_filename": f"{title}.csv", "items": [{
                "row_number": 1,
                "source_url": f"https://example.com/{user.id}",
                "source_title": title,
            }]},
        )
        assert response.status_code == 201

    history = client.get(
        "/api/v1/knowledge/materials/batches", headers=_headers(first)
    )
    assert history.status_code == 200
    assert [item["original_filename"] for item in history.json()["data"]] == ["第一批.csv"]
    assert "items" not in history.json()["data"][0]


def test_batch_accepts_more_than_previous_twenty_item_limit() -> None:
    from app.schemas.knowledge import MaterialBatchCreate

    payload = MaterialBatchCreate(items=[{
        "row_number": index + 1,
        "source_url": f"https://example.com/{index}",
    } for index in range(21)])
    assert len(payload.items) == 21


def test_interrupted_batch_is_requeued_on_service_start(
    db: Session, monkeypatch,
) -> None:
    admin = User(username="recover_admin", password_hash=hash_password("password-123"), role="admin")
    db.add(admin); db.flush()
    batch = MaterialImportBatch(
        created_by=admin.id, status="processing", total_count=1,
        course_ids=[], chapter_ids=[], access_policy="full_preview",
    )
    db.add(batch); db.flush()
    item = MaterialImportItem(
        batch_id=batch.id, row_number=1, source_url="https://example.com/recover",
        status="processing", knowledge_tags=[], raw_data={},
    )
    db.add(item); db.commit()
    scheduled: list[int] = []
    monkeypatch.setattr(
        "app.services.material_import_service.schedule_material_batch",
        lambda batch_id, _bind: scheduled.append(batch_id),
    )

    assert recover_material_batches(db.get_bind()) == 1
    db.expire_all()
    assert db.get(MaterialImportBatch, batch.id).status == "queued"
    assert db.get(MaterialImportItem, item.id).status == "queued"
    assert scheduled == [batch.id]

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.db.session import get_db
from app.main import app


def test_health_check(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ok"


def test_readiness_check_queries_database(client: TestClient) -> None:
    response = client.get("/api/v1/ready")

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ready"


def test_readiness_check_returns_503_when_database_is_unavailable(client: TestClient) -> None:
    class UnavailableSession:
        def execute(self, *_args: object, **_kwargs: object) -> None:
            raise OperationalError("SELECT 1", {}, Exception("database unavailable"))

    def unavailable_db():
        yield UnavailableSession()

    original_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = unavailable_db
    try:
        response = client.get("/api/v1/ready")
    finally:
        if original_override is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = original_override

    assert response.status_code == 503
    assert response.json()["detail"] == "数据库暂时不可用"

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_health_reports_ok_when_database_is_readable(client):
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_reports_unavailable_when_database_cannot_open(tmp_path):
    settings = Settings(
        db_path=str(tmp_path),
        admin_password="admin-test-password",
        session_secret="test-session-secret",
    )

    with TestClient(create_app(settings)) as client:
        response = client.get("/healthz")

    assert response.status_code == 503
    assert response.json() == {"status": "error"}

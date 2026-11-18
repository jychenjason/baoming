from fastapi.testclient import TestClient

from app.main import create_app


def test_health_reports_ok_when_database_is_readable(client):
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_reports_unavailable_when_database_cannot_open(
    make_settings, tmp_path
):
    settings = make_settings(db_path=str(tmp_path))

    with TestClient(create_app(settings)) as client:
        response = client.get("/healthz")

    assert response.status_code == 503
    assert response.json() == {"status": "error"}

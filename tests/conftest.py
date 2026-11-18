import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def make_settings(tmp_path):
    def build(**overrides):
        values = {
            "db_path": str(tmp_path / "app.db"),
            "admin_password": "admin-test-password",
            "session_secret": "test-session-secret",
        }
        values.update(overrides)
        return Settings(**values)

    return build


@pytest.fixture
def settings(make_settings):
    return make_settings()


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def test_dashboard_is_protected_and_admin_publish_remains_protected(monkeypatch):
    monkeypatch.setattr(settings, "dashboard_username", "dashboard-user")
    monkeypatch.setattr(settings, "dashboard_password", "dashboard-password")
    monkeypatch.setattr(settings, "admin_api_token", "admin-token")
    monkeypatch.setattr(settings, "scheduler_enabled", False)

    with TestClient(app) as client:
        dashboard_response = client.get("/dashboard", auth=("dashboard-user", "dashboard-password"))
        admin_response = client.post("/admin/publish-now")

    assert dashboard_response.status_code == 200
    assert admin_response.status_code == 401
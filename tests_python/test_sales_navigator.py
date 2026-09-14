from fastapi.testclient import TestClient

from apps.sales_navigator.main import SESSIONS, app


def test_scenario_requires_login() -> None:
    SESSIONS.clear()
    client = TestClient(app)
    response = client.get("/api/scenario/start")
    assert response.status_code == 401


def test_demo_login_opens_scenario(monkeypatch) -> None:
    SESSIONS.clear()
    monkeypatch.setenv("SALES_NAVIGATOR_PASSWORD", "test-password")
    client = TestClient(app)
    response = client.post("/login", data={"password": "test-password"}, follow_redirects=True)
    assert response.status_code == 200
    assert "Мы уже работаем с другим подрядчиком" in response.text
    branch = client.get("/api/scenario/price")
    assert branch.status_code == 200
    assert branch.json()["manager"].startswith("Давайте сравним")


def test_unknown_branch_returns_not_found() -> None:
    SESSIONS.clear()
    client = TestClient(app)
    client.post("/login", data={"password": "demo"})
    response = client.get("/api/scenario/unknown")
    assert response.status_code == 404

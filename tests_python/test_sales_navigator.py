from fastapi.testclient import TestClient

from copy import deepcopy

from apps.sales_navigator.main import SESSIONS, app, load


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
    assert "С кем можно поговорить по вопросу продвижения вашего сайта" in response.text
    qualification = client.get("/api/scenario/qualification")
    assert qualification.status_code == 200
    assert qualification.json()["manager"] == "Отлично, тогда коротко уточню: вы уже продвигаете сайт в Яндексе или это пока в планах?"
    branch = client.get("/api/scenario/price")
    assert branch.status_code == 200
    assert branch.json()["manager"].startswith("Давайте сравним")


def test_unknown_branch_returns_not_found() -> None:
    SESSIONS.clear()
    client = TestClient(app)
    client.post("/login", data={"password": "demo"})
    response = client.get("/api/scenario/unknown")
    assert response.status_code == 404


def test_editor_persists_valid_scenario_and_rejects_broken_link(monkeypatch, tmp_path) -> None:
    SESSIONS.clear()
    monkeypatch.setenv("SALES_NAVIGATOR_DATA_PATH", str(tmp_path / "scenario.json"))
    client = TestClient(app)
    client.post("/login", data={"password": "demo"})
    loaded = client.get("/api/scenario").json()
    scenario = deepcopy(loaded["scenario"])
    scenario["new-node-1"] = {"client": "Ответ", "manager": "Реплика", "hint": "Подсказка", "choices": []}
    scenario["planning"]["choices"] = [{"label": "Продолжить", "next": "new-node-1"}]
    saved = client.put("/api/scenario", json={"scenario": scenario, "revision": loaded["revision"]})
    assert saved.status_code == 200
    assert "new-node-1" in load()
    broken = deepcopy(scenario); broken["start"]["choices"][0]["next"] = "missing"
    assert client.put("/api/scenario", json={"scenario": broken, "revision": saved.json()["revision"]}).status_code == 422
    assert load() == scenario

from fastapi.testclient import TestClient

from copy import deepcopy

from apps.sales_navigator.main import SESSIONS, app, load


def client() -> TestClient:
    return TestClient(app, base_url="https://sales.mtrhit.ru")


def configure_roles(monkeypatch) -> None:
    monkeypatch.setenv("SALES_NAVIGATOR_ADMIN_PASSWORD", "admin-test-password")
    monkeypatch.setenv("SALES_NAVIGATOR_MANAGER_PASSWORD", "manager-test-password")


def test_scenario_requires_login() -> None:
    SESSIONS.clear()
    test_client = client()
    response = test_client.get("/api/scenario/start")
    assert response.status_code == 401
    assert test_client.get("/editor", follow_redirects=False).status_code == 401


def test_demo_login_opens_scenario(monkeypatch) -> None:
    SESSIONS.clear()
    configure_roles(monkeypatch)
    test_client = client()
    response = test_client.post("/login", data={"password": "admin-test-password"}, follow_redirects=True)
    assert response.status_code == 200
    assert "С кем можно поговорить по вопросу продвижения вашего сайта" in response.text
    assert '}},names={start:' in response.text
    assert "Редактировать этот шаг" in response.text
    assert "Добавить вариант ответа" in response.text
    assert "cancelInlineEdit" in response.text
    assert test_client.get("/map").status_code == 200
    assert "Карта сценария" in test_client.get("/map").text
    qualification = test_client.get("/api/scenario/qualification")
    assert qualification.status_code == 200
    assert qualification.json()["manager"] == "Отлично, тогда коротко уточню: вы уже продвигаете сайт в Яндексе или это пока в планах?"
    branch = test_client.get("/api/scenario/price")
    assert branch.status_code == 200
    assert branch.json()["manager"].startswith("Давайте сравним")


def test_manager_is_read_only_and_has_no_edit_controls(monkeypatch) -> None:
    SESSIONS.clear()
    configure_roles(monkeypatch)
    test_client = client()
    response = test_client.post("/login", data={"password": "manager-test-password"}, follow_redirects=True)
    assert response.status_code == 200
    assert "Редактировать этот шаг" not in response.text
    assert 'href="/editor"' not in response.text
    assert test_client.get("/api/scenario/start").status_code == 200
    assert test_client.get("/editor").status_code == 403
    loaded = test_client.get("/api/scenario").json()
    assert test_client.put("/api/scenario", json=loaded).status_code == 403


def test_unknown_branch_returns_not_found(monkeypatch) -> None:
    SESSIONS.clear()
    configure_roles(monkeypatch)
    test_client = client()
    test_client.post("/login", data={"password": "manager-test-password"})
    response = test_client.get("/api/scenario/unknown")
    assert response.status_code == 404


def test_editor_persists_valid_scenario_and_rejects_broken_link(monkeypatch, tmp_path) -> None:
    SESSIONS.clear()
    configure_roles(monkeypatch)
    monkeypatch.setenv("SALES_NAVIGATOR_DATA_PATH", str(tmp_path / "scenario.json"))
    test_client = client()
    test_client.post("/login", data={"password": "admin-test-password"})
    loaded = test_client.get("/api/scenario").json()
    scenario = deepcopy(loaded["scenario"])
    scenario["new-node-1"] = {"client": "Ответ", "manager": "Реплика", "hint": "Подсказка", "choices": []}
    scenario["planning"]["choices"] = [{"label": "Продолжить", "next": "new-node-1"}]
    saved = test_client.put("/api/scenario", json={"scenario": scenario, "revision": loaded["revision"]})
    assert saved.status_code == 200
    assert "new-node-1" in load()
    broken = deepcopy(scenario); broken["start"]["choices"][0]["next"] = "missing"
    assert test_client.put("/api/scenario", json={"scenario": broken, "revision": saved.json()["revision"]}).status_code == 422
    assert load() == scenario
    page = test_client.get("/editor").text
    assert "Первый звонок" in page
    assert "Уже есть подрядчик" in page
    assert "MutationObserver" not in page
    assert "const names={start:" in page

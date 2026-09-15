from fastapi.testclient import TestClient

from copy import deepcopy
from playwright.sync_api import sync_playwright

from apps.sales_navigator.main import SESSIONS, app, load, validate


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


def test_admin_adds_distinct_editable_linked_branch_in_both_editors(monkeypatch) -> None:
    SESSIONS.clear()
    configure_roles(monkeypatch)
    SESSIONS["browser-test-session"] = "admin"
    test_client = client()
    test_client.cookies.set("sales_session", "browser-test-session")
    original = test_client.get("/api/scenario").json()
    home_page = test_client.get("/").text
    editor_page = test_client.get("/editor").text

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.route("https://sales.mtrhit.ru/", lambda route: route.fulfill(body=home_page, content_type="text/html"))
        page.route("https://sales.mtrhit.ru/editor", lambda route: route.fulfill(body=editor_page, content_type="text/html"))
        page.route("https://sales.mtrhit.ru/api/scenario", lambda route: route.fulfill(json=original))

        page.goto("https://sales.mtrhit.ru/")
        page.locator("#edit").click()
        page.locator("#edit-client").fill("Несохранённый текст исходного шага")
        page.locator("#add-choice").click()
        inline = page.evaluate("({current:c,scenario:n,history:h})")
        inline_next = inline["scenario"]["start"]["choices"][-1]["next"]
        assert inline_next != "start"
        assert inline_next not in original["scenario"]
        assert inline["current"] == "start"
        assert inline["history"] == []
        assert inline["scenario"]["start"]["client"] == "Несохранённый текст исходного шага"
        assert page.locator("#edit-choices [data-choice]").count() == len(inline["scenario"]["start"]["choices"])
        assert page.locator("#edit-choices [data-choice]").last.locator("input").input_value() == "Новый вариант ответа"
        assert page.locator("#edit-choices [data-choice]").last.locator("select").input_value() == inline_next
        assert "Добавлен вариант ответа" in page.locator("#edit-status").inner_text()
        assert page.locator("#edit-choices [data-choice]").last.locator("input").evaluate("x=>document.activeElement===x")
        assert inline["scenario"][inline_next]["choices"] == []
        validate(inline["scenario"])
        page.locator("#edit-choices [data-choice]").last.locator("input").fill("Первый вложенный ответ")
        page.locator("#edit-choices [data-choice]").last.locator("[data-open]").click()
        opened = page.evaluate("({current:c,scenario:n,history:h})")
        assert opened["current"] == inline_next
        assert opened["history"] == ["start"]
        assert opened["scenario"]["start"]["choices"][-1]["label"] == "Первый вложенный ответ"
        assert "Открыта связанная ветка" in page.locator("#edit-status").inner_text()
        for field, key in (("edit-client", "client"), ("edit-manager", "manager"), ("edit-hint", "hint")):
            assert page.locator(f"#{field}").input_value() == opened["scenario"][inline_next][key]
            page.locator(f"#{field}").fill(f"Редактируемый {key}")
        page.locator("#add-choice").click()
        nested = page.evaluate("({current:c,scenario:n,history:h})")
        nested_next = nested["scenario"][inline_next]["choices"][-1]["next"]
        assert nested["current"] == inline_next
        assert nested_next not in original["scenario"] and nested_next != inline_next
        assert nested["scenario"][inline_next]["client"] == "Редактируемый client"
        assert page.locator("#edit-choices [data-choice]").count() == 1
        assert page.locator("#edit-choices [data-choice] [data-open]").count() == 1
        validate(nested["scenario"])
        page.locator("#edit-choices [data-choice] input").fill("Второй вложенный ответ")
        page.locator("#edit-choices [data-choice] [data-open]").click()
        assert page.evaluate("c") == nested_next
        assert page.evaluate("h") == ["start", inline_next]
        assert page.locator("#edit-client").input_value() == nested["scenario"][nested_next]["client"]
        assert page.locator("#edit-panel").is_visible()
        page.locator("#cancel-edit").click()
        assert page.evaluate("({current:c,scenario:n,history:h})") == {
            "current": "start", "scenario": original["scenario"], "history": []
        }

        page.goto("https://sales.mtrhit.ru/editor")
        page.locator("#add").click()
        page.locator("#add").click()
        full = page.evaluate("({current:id,scenario:d.scenario})")
        first_next = full["scenario"]["start"]["choices"][-1]["next"]
        second_next = full["scenario"][first_next]["choices"][-1]["next"]
        assert first_next != second_next
        assert first_next not in original["scenario"] and second_next not in original["scenario"]
        assert full["current"] == second_next
        validate(full["scenario"])
        assert full["scenario"][second_next]["choices"] == []
        for field, key in (("client", "client"), ("manager", "manager"), ("hint", "hint")):
            assert page.locator(f"#{field}").input_value() == full["scenario"][second_next][key]
            page.locator(f"#{field}").fill(f"Редактируемый {key}")
        page.evaluate("collect()")
        assert page.evaluate("d.scenario[id].manager") == "Редактируемый manager"
        browser.close()

from fastapi.testclient import TestClient

from copy import deepcopy
from playwright.sync_api import sync_playwright
import pytest

from apps.sales_navigator.main import SESSIONS, app, load, load_quick_help, quick_help_path, revision, validate


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
    assert 'id="edit-title"' not in response.text
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


def test_admin_edits_quick_help_without_changing_scenario(monkeypatch, tmp_path) -> None:
    SESSIONS.clear()
    configure_roles(monkeypatch)
    monkeypatch.setenv("SALES_NAVIGATOR_DATA_PATH", str(tmp_path / "scenario.json"))
    test_client = client()
    test_client.post("/login", data={"password": "admin-test-password"})
    scenario_before = revision(load())
    initial = test_client.get("/api/quick-help")
    assert initial.status_code == 200
    assert len(initial.json()["items"]) == 10
    edited = deepcopy(initial.json()["items"])
    edited["about"] = {"title": "О сервисе", "body": "Проверочный текст справки."}
    edited["custom-1"] = {"title": "Новый раздел", "body": "Описание нового раздела."}
    saved = test_client.put("/api/quick-help", json={"items": edited, "revision": initial.json()["revision"]})
    assert saved.status_code == 200
    assert saved.json()["items"]["about"]["title"] == "О сервисе"
    assert saved.json()["items"]["custom-1"]["body"] == "Описание нового раздела."
    assert load_quick_help() == edited
    assert quick_help_path().exists()
    assert revision(load()) == scenario_before

    invalid = deepcopy(edited)
    invalid["about"]["body"] = "<b>Нельзя</b>"
    rejected = test_client.put("/api/quick-help", json={"items": invalid, "revision": saved.json()["revision"]})
    assert rejected.status_code == 422
    assert load_quick_help() == edited

    invalid_key = deepcopy(edited)
    invalid_key["новый-раздел"] = invalid_key.pop("custom-1")
    rejected_key = test_client.put("/api/quick-help", json={"items": invalid_key, "revision": saved.json()["revision"]})
    assert rejected_key.status_code == 422

    manager = client()
    manager.post("/login", data={"password": "manager-test-password"})
    assert manager.get("/api/quick-help").status_code == 403
    assert 'id="edit-quick-help"' not in manager.get("/").text


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
    assert "title" not in load()["new-node-1"]
    invalid_title = deepcopy(scenario); invalid_title["new-node-1"]["title"] = " "
    with pytest.raises(ValueError, match="название ветки"):
        validate(invalid_title)
    page = test_client.get("/editor").text
    assert "Первый звонок" in page
    assert "Уже есть подрядчик" in page
    assert "MutationObserver" not in page
    assert "const names={start:" in page


def test_named_branch_saves_without_migrating_legacy_nodes(monkeypatch, tmp_path) -> None:
    SESSIONS.clear()
    configure_roles(monkeypatch)
    monkeypatch.setenv("SALES_NAVIGATOR_DATA_PATH", str(tmp_path / "scenario.json"))
    test_client = client()
    test_client.post("/login", data={"password": "admin-test-password"})
    loaded = test_client.get("/api/scenario").json()
    scenario = deepcopy(loaded["scenario"])
    scenario["contact"]["title"] = "Коллега <контакт>"
    saved = test_client.put("/api/scenario", json={"scenario": scenario, "revision": loaded["revision"]})
    assert saved.status_code == 200
    assert load()["contact"]["title"] == "Коллега <контакт>"
    assert "title" not in load()["start"]
    assert "Коллега &lt;контакт&gt;" in test_client.get("/map").text
    scenario["contact"]["title"] = " "
    assert test_client.put("/api/scenario", json={"scenario": scenario, "revision": saved.json()["revision"]}).status_code == 422
    assert load()["contact"]["title"] == "Коллега <контакт>"


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


def test_admin_names_branches_and_reorders_only_current_branch_in_both_editors(monkeypatch) -> None:
    SESSIONS.clear()
    configure_roles(monkeypatch)
    SESSIONS["branch-browser-session"] = "admin"
    test_client = client()
    test_client.cookies.set("sales_session", "branch-browser-session")
    original = test_client.get("/api/scenario").json()
    home_page = test_client.get("/").text
    editor_page = test_client.get("/editor").text
    errors = []
    writes = []

    def scenario_route(route) -> None:
        if route.request.method == "PUT":
            payload = route.request.post_data_json
            writes.append(payload)
            route.fulfill(json={"scenario": payload["scenario"], "revision": "saved-revision"})
        else:
            route.fulfill(json=original)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("https://sales.mtrhit.ru/", lambda route: route.fulfill(body=home_page, content_type="text/html"))
        page.route("https://sales.mtrhit.ru/editor", lambda route: route.fulfill(body=editor_page, content_type="text/html"))
        page.route("https://sales.mtrhit.ru/api/scenario", scenario_route)

        page.goto("https://sales.mtrhit.ru/")
        page.locator("#edit").click()
        assert page.locator("#edit-title").input_value() == "Первый звонок"
        page.locator("#edit-title").fill("Стартовая беседа")
        page.locator("#edit-choices [data-choice]").nth(1).locator("input").fill("Другой коллега — уточнить")
        page.locator("#edit-choices [data-choice]").nth(1).get_by_role("button", name="Поднять вариант ответа").click()
        inline = page.evaluate("n")
        assert [choice["next"] for choice in inline["start"]["choices"][:3]] == [
            "contact", "qualification", "time"
        ]
        assert inline["start"]["choices"][0]["label"] == "Другой коллега — уточнить"
        assert inline["qualification"]["choices"] == original["scenario"]["qualification"]["choices"]
        assert inline["start"]["title"] == "Стартовая беседа"
        page.locator("#edit-choices [data-choice]").first.get_by_role("button", name="Опустить вариант ответа").click()
        assert [choice["next"] for choice in page.evaluate("n.start.choices")[:3]] == [
            "qualification", "contact", "time"
        ]
        page.locator("#add-choice").click()
        created = page.evaluate("n.start.choices.at(-1).next")
        assert page.evaluate("n")[created]["title"].startswith("Новый ответ клиента ")
        assert page.locator("#edit-choices [data-choice]").last.locator("select option:checked").text_content() == page.evaluate("n")[created]["title"]
        page.locator("#edit-choices [data-choice]").last.locator("[data-open]").click()
        assert page.locator("#edit-title").input_value() == page.evaluate("n")[created]["title"]
        assert page.locator("#edit-title").evaluate("element => document.activeElement === element")
        page.locator("#edit-title").fill("Уточнение запроса клиента")
        page.locator("#add-choice").click()
        assert page.locator("#edit-choices [data-choice] select option").filter(has_text="Уточнение запроса клиента").count() == 1
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert page.locator("#edit-choices [data-choice] [data-up]").is_visible()
        page.locator("#cancel-edit").click()
        assert page.evaluate("n") == original["scenario"]
        page.locator("#edit").click()
        page.locator("#edit-title").fill("Тестовое начало разговора")
        page.locator("#edit-choices [data-choice]").nth(1).get_by_role("button", name="Поднять вариант ответа").click()
        page.locator("#save-edit").click()
        page.wait_for_function("document.querySelector('#edit-panel').hidden")
        assert writes[-1]["scenario"]["start"]["title"] == "Тестовое начало разговора"
        assert writes[-1]["scenario"]["start"]["choices"][0]["next"] == "contact"
        validate(writes[-1]["scenario"])

        page.goto("https://sales.mtrhit.ru/editor")
        assert page.locator("#title").input_value() == "Первый звонок"
        page.locator("#title").fill("Первый контакт")
        assert "Первый контакт" in page.locator("#nodes [data-id='start']").inner_text()
        page.locator("#choices .choice").nth(1).locator("input").fill("Контакт коллеги — проверить")
        page.locator("#choices .choice").nth(1).get_by_role("button", name="Поднять вариант ответа").click()
        full = page.evaluate("d.scenario")
        assert [choice["next"] for choice in full["start"]["choices"][:3]] == [
            "contact", "qualification", "time"
        ]
        assert full["start"]["choices"][0]["label"] == "Контакт коллеги — проверить"
        assert full["qualification"]["choices"] == original["scenario"]["qualification"]["choices"]
        page.locator("#add").click()
        full_created = page.evaluate("id")
        assert page.locator("#title").input_value() == page.evaluate("d.scenario[id].title")
        assert page.locator("#title").input_value().startswith("Новый ответ клиента ")
        assert page.locator("#title").evaluate("element => document.activeElement === element")
        page.locator("#title").fill("Уточнение <срочно>")
        page.locator("#nodes [data-id='start']").click()
        assert "Уточнение <срочно>" in page.locator(f"#nodes [data-id='{full_created}']").inner_text()
        assert page.locator("#choices .choice").last.locator("select option:checked").text_content() == "Уточнение <срочно>"
        assert page.locator("#title").input_value() == "Первый контакт"
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert page.locator("#choices .choice [data-up]").first.is_visible()
        page.locator("#cancel").click()
        page.wait_for_function("d.scenario.start.choices.length === 3 && !d.scenario['new-node-1']")
        assert page.evaluate("d.scenario") == original["scenario"]
        page.locator("#title").fill("Начало разговора")
        page.locator("#save").click()
        page.wait_for_function("document.querySelector('#status').textContent === 'Сохранено'")
        assert writes[-1]["scenario"]["start"]["title"] == "Начало разговора"
        validate(writes[-1]["scenario"])
        assert errors == []
        browser.close()


def test_manager_persistent_navigation_search_collapse_current_and_mobile(monkeypatch) -> None:
    SESSIONS.clear()
    configure_roles(monkeypatch)
    SESSIONS["manager-nav-session"] = "manager"
    test_client = client()
    test_client.cookies.set("sales_session", "manager-nav-session")
    home_page = test_client.get("/").text
    assert 'id="branch-nav"' in home_page
    assert "Найти ветку" in home_page
    assert 'id="edit-title"' not in home_page
    errors = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("https://sales.mtrhit.ru/", lambda route: route.fulfill(body=home_page, content_type="text/html"))
        page.goto("https://sales.mtrhit.ru/")
        assert page.locator("#branch-nav").is_visible()
        assert page.locator("#nav-mobile-toggle").is_hidden()
        assert page.locator("#nav-tree [data-nav-key]").count() < len(page.evaluate("Object.keys(n)"))
        assert page.locator("#nav-tree [data-nav-open='start']").get_attribute("aria-current") == "step"
        assert page.locator("#nav-tree [data-nav-toggle='start']").get_attribute("aria-expanded") == "true"
        page.locator("#nav-tree [data-nav-toggle='start']").click()
        assert page.locator("#nav-tree [data-nav-key]").count() == 1
        assert page.locator("#nav-tree [data-nav-toggle='start']").get_attribute("aria-expanded") == "false"
        page.locator("#nav-tree [data-nav-toggle='start']").click()
        page.evaluate("n.qualification.title='Уточнить задачу';navRender()")
        assert page.locator("#nav-tree [data-nav-open='qualification']").inner_text() == "Уточнить задачу"
        page.locator("#nav-tree [data-nav-open='qualification']").click()
        assert page.evaluate("c") == "qualification"
        assert page.locator("#client").inner_text() == page.evaluate("n[c].client")
        assert page.locator("#nav-tree [data-nav-open='qualification']").get_attribute("aria-current") == "step"
        assert page.locator("#nav-tree [data-nav-toggle='start']").get_attribute("aria-expanded") == "true"
        page.locator("#back").click()
        assert page.evaluate("c") == "start"
        page.locator("#choices button").first.click()
        assert page.evaluate("c") == "qualification"
        assert page.locator("#nav-tree [data-nav-open='qualification']").get_attribute("aria-current") == "step"
        page.locator("#restart").click()
        assert page.evaluate("c") == "start"
        page.locator("#nav-tree .reference [data-nav-open='time']").click()
        assert page.evaluate("c") == "time"
        assert page.locator("#nav-tree .current [data-nav-open='time']").is_visible()
        page.locator("#restart").click()

        page.locator("#nav-search").fill("Нужны доказательства")
        assert page.locator("#nav-tree [data-nav-open='proof']").is_visible()
        page.locator("#nav-tree [data-nav-open='proof']").click()
        assert page.evaluate("c") == "proof"
        assert page.locator("#nav-tree [data-nav-open='proof']").get_attribute("aria-current") == "step"
        page.locator("#nav-search").fill("нет такой ветки")
        assert "Ветка не найдена" in page.locator("#nav-tree").inner_text()
        page.locator("#nav-search").clear()

        page.set_viewport_size({"width": 390, "height": 844})
        assert page.locator("#branch-nav").is_visible()
        assert page.locator("#nav-search").is_hidden()
        assert page.locator("#client").is_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.locator("#nav-mobile-toggle").click()
        assert page.locator("#nav-search").is_visible()
        assert page.locator("#nav-mobile-toggle").get_attribute("aria-expanded") == "true"
        page.locator("#nav-tree [data-nav-open='start']").click()
        assert page.evaluate("c") == "start"
        assert page.locator("#nav-search").is_hidden()
        assert page.locator("#client").is_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert page.locator("#edit").count() == 0
        assert page.locator("#branch-nav [data-up], #branch-nav [data-down], #branch-nav [data-remove]").count() == 0
        assert errors == []
        browser.close()


def test_manager_centered_workspace_resizable_tree_and_quick_help(monkeypatch) -> None:
    SESSIONS.clear()
    configure_roles(monkeypatch)
    SESSIONS["manager-workspace-session"] = "manager"
    test_client = client()
    test_client.cookies.set("sales_session", "manager-workspace-session")
    home_page = test_client.get("/").text
    assert 'id="nav-resizer"' in home_page
    assert 'id="quick-help"' in home_page
    assert 'id="help-modal"' in home_page
    errors = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("https://sales.mtrhit.ru/", lambda route: route.fulfill(body=home_page, content_type="text/html"))
        page.goto("https://sales.mtrhit.ru/")

        main_box = page.locator("main").bounding_box()
        assert main_box is not None
        assert abs(main_box["x"] + main_box["width"] / 2 - 720) <= 30
        assert page.locator(".quick-help-button").count() == 10

        initial_width = page.locator("#branch-nav").bounding_box()["width"]
        handle = page.locator("#nav-resizer").bounding_box()
        assert handle is not None
        page.mouse.move(handle["x"] + handle["width"] / 2, handle["y"] + 50)
        page.mouse.down()
        page.mouse.move(handle["x"] + handle["width"] / 2 + 72, handle["y"] + 50)
        page.mouse.up()
        resized_width = page.locator("#branch-nav").bounding_box()["width"]
        assert resized_width >= initial_width + 60
        assert page.locator("#nav-resizer").get_attribute("aria-valuenow") == str(round(resized_width))
        stored_width = page.evaluate("localStorage.getItem('sales-navigator-branch-width')")
        assert stored_width == str(round(resized_width))
        page.reload()
        assert abs(page.locator("#branch-nav").bounding_box()["width"] - resized_width) <= 1

        expected_titles = [
            "О MetricHit", "Как это работает", "Тест 1 000 кликов", "Цены и тарифы", "Как начать",
            "Что видно в кабинете", "Частые вопросы", "Возражения", "Поддержка и контакты", "Что не обещаем",
        ]
        for index, title in enumerate(expected_titles):
            page.locator(".quick-help-button").nth(index).click()
            assert page.locator("#help-modal").is_visible()
            assert page.locator("#help-title").inner_text() == title
            page.locator("#help-close").click()
            assert page.locator("#help-modal").is_hidden()

        page.get_by_role("button", name="Как это работает").click()
        assert "искусственные переходы" in page.locator("#help-content").inner_text()
        page.keyboard.press("Escape")
        assert page.locator("#help-modal").is_hidden()
        page.get_by_role("button", name="Цены и тарифы").click()
        page.locator("#help-modal").click(position={"x": 5, "y": 5})
        assert page.locator("#help-modal").is_hidden()

        page.set_viewport_size({"width": 390, "height": 844})
        assert page.locator("#nav-resizer").is_hidden()
        assert page.locator(".quick-help-button").count() == 10
        assert page.locator("main").bounding_box()["y"] < page.locator("#quick-help").bounding_box()["y"]
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.get_by_role("button", name="Что не обещаем").click()
        assert page.locator("#help-modal").is_visible()
        assert page.locator("#help-dialog, .help-dialog").count() == 1
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.keyboard.press("Escape")
        assert errors == []
        browser.close()


def test_admin_edits_quick_help_in_the_workspace(monkeypatch) -> None:
    SESSIONS.clear()
    configure_roles(monkeypatch)
    SESSIONS["quick-help-admin-session"] = "admin"
    test_client = client()
    test_client.cookies.set("sales_session", "quick-help-admin-session")
    home_page = test_client.get("/").text
    initial = test_client.get("/api/quick-help").json()
    writes = []
    errors = []

    def quick_help_route(route) -> None:
        if route.request.method == "PUT":
            payload = route.request.post_data_json
            writes.append(payload)
            route.fulfill(json={"items": payload["items"], "revision": "saved-help-revision"})
        else:
            route.fulfill(json=initial)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("https://sales.mtrhit.ru/", lambda route: route.fulfill(body=home_page, content_type="text/html"))
        page.route("https://sales.mtrhit.ru/api/quick-help", quick_help_route)
        page.goto("https://sales.mtrhit.ru/")
        assert page.locator("#edit-quick-help").is_visible()
        page.locator("#edit-quick-help").click()
        page.locator("#help-editor-modal").wait_for(state="visible")
        assert page.locator(".help-editor-item").count() == 10
        page.get_by_role("button", name="Переместить О MetricHit ниже").click()
        assert page.locator("#help-editor-list button").first.inner_text() == "Как это работает"
        page.locator("#help-editor-add").click()
        assert page.locator(".help-editor-item").count() == 11
        page.locator("#help-edit-title").fill("Условия запуска")
        page.locator("#help-edit-body").fill("Первый абзац.\n\nВторой абзац.")
        page.locator("#help-editor-save").click()
        page.wait_for_function("document.querySelector('#help-editor-modal').hidden")
        assert list(writes[-1]["items"])[0] == "mechanics"
        assert writes[-1]["items"]["custom-1"] == {"title": "Условия запуска", "body": "Первый абзац.\n\nВторой абзац."}
        assert page.locator(".quick-help-button").first.inner_text() == "Как это работает"
        assert page.get_by_role("button", name="Условия запуска").is_visible()
        page.get_by_role("button", name="Условия запуска").click()
        assert page.locator("#help-title").inner_text() == "Условия запуска"
        assert page.locator("#help-content p").count() == 2
        page.keyboard.press("Escape")
        assert page.locator("#help-modal").is_hidden()
        page.locator("#edit-quick-help").click()
        page.locator("#help-editor-cancel").click()
        assert page.locator("#help-editor-modal").is_hidden()
        assert errors == []
        browser.close()


def test_navigation_guards_large_shared_cyclic_and_broken_graph(monkeypatch) -> None:
    SESSIONS.clear()
    configure_roles(monkeypatch)
    SESSIONS["graph-nav-session"] = "manager"
    test_client = client()
    test_client.cookies.set("sales_session", "graph-nav-session")
    home_page = test_client.get("/").text
    errors = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("https://sales.mtrhit.ru/", lambda route: route.fulfill(body=home_page, content_type="text/html"))
        page.goto("https://sales.mtrhit.ru/")
        page.evaluate("""() => {
            for (let i=1;i<=30;i++) n['dense-'+i]={title:'Ветка '+i,client:'Ответ',manager:'Реплика',hint:'Подсказка',choices:[]};
            n.start.choices.push({label:'Начать длинный путь',next:'dense-1'});
            n.start.choices.push({label:'Сломанный переход',next:'absent-node'});
            for (let i=1;i<30;i++) n['dense-'+i].choices.push({label:'Далее '+i,next:'dense-'+(i+1)});
            n['dense-20'].choices.push({label:'Общая ветка',next:'dense-10'});
            n['dense-30'].choices.push({label:'Вернуться к началу',next:'start'});
            n['orphan-one']={title:'Отдельная ветка',client:'Ответ',manager:'Реплика',hint:'Подсказка',choices:[]};
            navRender();
        }""")
        assert page.locator("#nav-tree [data-nav-key]").count() < 15
        assert page.evaluate("navGraph().paths.size") == len(page.evaluate("Object.keys(n)"))
        assert page.evaluate("navGraph().root.children.map(node=>node.key)") == [
            "qualification", "contact", "time", "dense-1"
        ]
        assert "Другие ветки" in page.locator("#nav-tree").inner_text()
        page.locator("#nav-tree .nav-group button").click()
        page.locator("#nav-tree [data-nav-open='orphan-one']").click()
        assert page.evaluate("c") == "orphan-one"
        assert page.locator("#nav-tree [data-nav-open='orphan-one']").get_attribute("aria-current") == "step"
        page.locator("#restart").click()
        page.locator("#nav-search").fill("Ветка 30")
        assert page.locator("#nav-tree [data-nav-open='dense-30']").is_visible()
        assert page.locator("#nav-tree [data-nav-key]").count() < 45
        page.locator("#nav-tree [data-nav-open='dense-30']").click()
        assert page.evaluate("c") == "dense-30"
        assert page.locator("#nav-tree [data-nav-open='dense-30']").get_attribute("aria-current") == "step"
        page.locator("#nav-search").clear()
        assert page.locator("#nav-tree [data-nav-key]").count() < 45
        assert page.evaluate("navTree.scrollHeight > navTree.clientHeight")
        assert page.evaluate("""() => {
            const tree=navTree.getBoundingClientRect(),current=navTree.querySelector('.nav-row.current').getBoundingClientRect();
            return current.top>=tree.top && current.bottom<=tree.bottom;
        }""")
        page.locator("#restart").click()
        page.locator("#choices button").last.click()
        assert page.evaluate("c") == "start"
        assert "недоступна" in page.locator("#nav-status").inner_text()
        assert errors == []
        browser.close()


def test_admin_navigation_blocks_unsaved_inline_edits_until_cancel(monkeypatch) -> None:
    SESSIONS.clear()
    configure_roles(monkeypatch)
    SESSIONS["admin-nav-session"] = "admin"
    test_client = client()
    test_client.cookies.set("sales_session", "admin-nav-session")
    home_page = test_client.get("/").text
    errors = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("https://sales.mtrhit.ru/", lambda route: route.fulfill(body=home_page, content_type="text/html"))
        page.goto("https://sales.mtrhit.ru/")
        page.locator("#edit").click()
        page.locator("#edit-client").fill("Несохранённая реплика")
        page.locator("#nav-tree [data-nav-open='qualification']").click()
        assert page.evaluate("c") == "start"
        assert page.locator("#edit-panel").is_visible()
        assert page.locator("#edit-client").input_value() == "Несохранённая реплика"
        assert "Сначала сохраните" in page.locator("#nav-status").inner_text()
        assert "Отменить" in page.locator("#edit-status").inner_text()
        page.locator("#choices button").first.click()
        assert page.evaluate("c") == "start"
        assert page.locator("#edit-client").input_value() == "Несохранённая реплика"
        page.locator("header a[href='/editor']").click()
        page.locator("header form button").click()
        assert page.url == "https://sales.mtrhit.ru/"
        assert page.locator("#edit-panel").is_visible()
        page.locator("#cancel-edit").click()
        assert page.locator("#nav-status").inner_text() == ""
        page.locator("#nav-tree [data-nav-open='qualification']").click()
        assert page.evaluate("c") == "qualification"
        assert page.locator("#nav-tree [data-nav-open='qualification']").get_attribute("aria-current") == "step"
        assert errors == []
        browser.close()

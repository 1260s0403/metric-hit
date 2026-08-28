from __future__ import annotations

import socket
import sqlite3
import subprocess
import sys
import time
import re
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, Playwright, expect, sync_playwright


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _temporary_database(tmp_path: Path) -> Path:
    database = tmp_path / "operator-e2e.sqlite"
    subprocess.run(["node", "scripts/init-memory.mjs", str(database)], check=True, capture_output=True, text=True)
    with sqlite3.connect(database) as connection:
        source_id = "00000000-0000-4000-8000-000000000040"
        connection.execute(
            "INSERT INTO sources (id,type,title,content,author) VALUES (?,'owner_input','E2E источник','Тестовый источник','owner')",
            (source_id,),
        )
        connection.executemany(
            """INSERT INTO memory_candidates (id,type,semantic_key,title,content,data_json,source_id,author)
               VALUES (?,'product_fact',?,?,?,'{}',?,'owner')""",
            [
                ("00000000-0000-4000-8000-000000000041", "e2e.approve", "Подтвердить в E2E", "Полный текст кандидата на подтверждение", source_id),
                ("00000000-0000-4000-8000-000000000042", "e2e.reject", "Отклонить в E2E", "Полный текст кандидата на отклонение", source_id),
            ],
        )
        connection.execute(
            """INSERT INTO memory_items (id,type,semantic_key,title,content,source_id,author)
               VALUES ('00000000-0000-4000-8000-000000000043','product_fact','e2e.conflict','Текущее E2E','Текущее значение',?,'owner')""",
            (source_id,),
        )
        connection.execute(
            """INSERT INTO memory_candidates (id,type,semantic_key,title,content,data_json,source_id,author)
               VALUES ('00000000-0000-4000-8000-000000000044','product_fact','e2e.conflict','Конфликт E2E','Новое значение','{}',?,'owner')""",
            (source_id,),
        )
        connection.execute(
            """UPDATE memory_candidates SET status='approved',reviewed_by='owner',reviewed_at='2026-08-16T00:00:00.000Z',version=version+1
               WHERE id='00000000-0000-4000-8000-000000000044'"""
        )
    return database


@pytest.fixture
def browser() -> Browser:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        try:
            yield browser
        finally:
            browser.close()


@pytest.fixture
def panel(tmp_path: Path) -> str:
    database = _temporary_database(tmp_path)
    port = _free_port()
    process = subprocess.Popen(
        [sys.executable, "-m", "metrichit_os", "operator-panel", "--db", str(database), "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)
    else:
        process.terminate()
        raise RuntimeError(process.stderr.read())
    try:
        yield base_url
    finally:
        process.terminate()
        process.wait(timeout=5)


@pytest.fixture
def page(browser: Browser, panel: str, tmp_path: Path) -> Page:
    page = browser.new_page(viewport={"width": 1200, "height": 700})
    try:
        yield page
    except BaseException:
        screenshots = tmp_path / "screenshots"
        screenshots.mkdir(exist_ok=True)
        page.screenshot(path=str(screenshots / "operator-panel-failure.png"), full_page=True)
        raise
    finally:
        page.close()


def _add_entry(page: Page, topic: str, text: str) -> str:
    if not page.get_by_test_id("knowledge-screen").is_visible():
        page.get_by_test_id("tab-artem").click()
    page.get_by_test_id("add-topic").fill(topic)
    page.get_by_test_id("add-text").fill(text)
    page.get_by_test_id("add-entry").click()
    page.reload()
    card = page.locator('[data-testid^="knowledge-entry-"]').filter(has_text=topic)
    expect(card).to_be_visible()
    action = card.locator('[data-testid^="create-task-"]')
    expect(action).to_be_visible()
    return str(action.get_attribute("data-testid")).removeprefix("create-task-")


def _create_task(page: Page, topic: str, text: str) -> str:
    entry_id = _add_entry(page, topic, text)
    page.get_by_test_id(f"create-task-{entry_id}").click()
    expect(page.get_by_test_id("task-modal")).to_be_visible()
    page.get_by_test_id("task-save").click()
    link = page.get_by_test_id(f"knowledge-entry-{entry_id}").locator('[data-testid^="open-task-"]')
    expect(link).to_be_visible()
    return str(link.get_attribute("href")).split("focus_task=")[1].split("#")[0]


def _open_tasks(page: Page, task_id: str) -> None:
    page.get_by_test_id(f"open-task-{task_id}").click()
    expect(page).to_have_url(f"{page.url.split('/?')[0]}/?view=tasks&focus_task={task_id}#task-{task_id}")
    expect(page.get_by_test_id("tab-tasks")).to_have_attribute("aria-current", "page")


def test_ideas_dashboard_has_real_summary_navigation_complete_feed_and_task_actions(page: Page, panel: str, tmp_path: Path) -> None:
    page.set_viewport_size({"width": 1536, "height": 1024})
    console_errors: list[str] = []
    page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
    page.goto(panel)
    secondary_project = _panel_post(page, "/api/projects", {"name": "Второй проект", "description": "Для распределения идей"})
    entries = [
        _panel_post(page, "/api/entries", {
            "kind": "idea", "topic": f"Идея {index}", "text": f"Описание {index}",
            **({"project_id": secondary_project["id"]} if index >= 3 else {}),
        })
        for index in range(22)
    ]
    task = _panel_post(page, "/api/tasks", {"id": entries[0]["id"]})

    page.goto(f"{panel}/?view=idea")
    expect(page.get_by_test_id("ideas-summary")).to_be_visible()
    expect(page.get_by_test_id("ideas-summary")).to_have_count(1)
    expect(page.locator(".ideas-dashboard-grid")).to_have_count(1)
    expect(page.locator(".ideas-analytics")).to_have_count(1)
    expect(page.get_by_test_id("ideas-feed")).to_have_count(1)
    expect(page.get_by_test_id("ideas-feed").locator('[data-testid^="idea-feed-"]')).to_have_count(22)
    assert page.get_by_test_id("ideas-feed").evaluate("node => getComputedStyle(node).overflowY") == "auto"
    assert page.locator(".ideas-dashboard-grid").evaluate("node => getComputedStyle(node).gridTemplateColumns.split(' ').length") == 2
    chart = page.get_by_test_id("ideas-by-project")
    expect(chart).to_contain_text("Идеи по проектам")
    expect(chart).to_contain_text("22")
    expect(chart).to_contain_text("идей")
    expect(chart).to_contain_text("Второй проект")
    expect(chart).to_contain_text("3")
    expect(chart).to_contain_text("19")
    expect(chart).not_to_contain_text("Задачи по проектам")
    for test_id in ("ideas-summary-new-icon", "ideas-summary-tasks-icon", "ideas-summary-unassigned-icon"):
        expect(page.get_by_test_id(test_id)).to_be_visible()
        expect(page.get_by_test_id(test_id).locator("svg")).to_have_count(1)
        assert page.get_by_test_id(test_id).evaluate("node => getComputedStyle(node).width") == "25px"
    legend_layout = chart.locator(".ideas-donut-line").evaluate_all("""lines => lines.map(line => {
        const label = line.querySelector('span').getBoundingClientRect();
        const count = line.querySelector('strong').getBoundingClientRect();
        return {fontSize: getComputedStyle(line).fontSize, countFontSize: getComputedStyle(line.querySelector('strong')).fontSize, countStartsAfterLabel: count.left > label.right};
    })""")
    assert all(item == {"fontSize": "16px", "countFontSize": "17px", "countStartsAfterLabel": True} for item in legend_layout)
    assert page.locator(".page-header p").evaluate("node => getComputedStyle(node).fontSize") == "16px"
    feed_header = page.locator(".ideas-feed-head")
    assert feed_header.evaluate("node => getComputedStyle(node).minHeight") == "52px"
    assert feed_header.locator("h3").evaluate("node => getComputedStyle(node).marginTop") == "0px"
    first_idea = page.get_by_test_id("ideas-feed").locator('[data-testid^="idea-feed-"]').first
    assert first_idea.locator(".ideas-feed-copy strong").evaluate("node => getComputedStyle(node).fontSize") == "16px"
    assert first_idea.locator(".ideas-feed-copy p").evaluate("node => getComputedStyle(node).fontSize") == "13px"
    expect(page.get_by_test_id(f"idea-open-task-{task['id']}")).to_be_visible()
    page.screenshot(path=str(tmp_path / "ideas-dashboard-wide.png"), full_page=True)

    page.get_by_test_id("ideas-summary-new").click()
    expect(page).to_have_url(re.compile(r"idea_filter=new"))
    expect(page.get_by_test_id("ideas-feed").locator('[data-testid^="idea-feed-"]')).to_have_count(21)
    page.get_by_test_id("ideas-summary-tasks").click()
    expect(page).to_have_url(re.compile(r"view=tasks.*source=ideas"))
    expect(page.get_by_test_id(f"task-card-{task['id']}")).to_be_visible()

    page.goto(f"{panel}/?view=idea")
    page.get_by_test_id(f"create-task-{entries[1]['id']}").click()
    expect(page.get_by_test_id("task-modal")).to_be_visible()
    page.get_by_test_id("task-save").click()
    expect(page).to_have_url(re.compile(r"view=idea"))
    expect(page.get_by_test_id(f"idea-feed-{entries[1]['id']}").locator('button')).to_have_text("Открыть задачу")
    expect(page.get_by_test_id("ideas-summary-tasks")).to_contain_text("2")
    page.screenshot(path=str(tmp_path / "ideas-after-task.png"), full_page=True)

    page.get_by_test_id("idea-topic").fill("Идея из панели")
    page.get_by_test_id("idea-description").fill("Проверка основной формы создания идеи")
    page.get_by_test_id("idea-submit").click()
    expect(page.get_by_test_id("ideas-feed").locator('[data-testid^="idea-feed-"]')).to_have_count(23)
    page.get_by_test_id("ideas-summary-unassigned").click()
    expect(page).to_have_url(re.compile(r"idea_filter=unassigned"))
    expect(page.get_by_test_id("ideas-feed")).to_be_visible()
    assert not console_errors


def test_task_creation_refreshes_current_tasks_view_without_navigation(page: Page, panel: str, tmp_path: Path) -> None:
    page.goto(f"{panel}/?view=tasks")
    expect(page.get_by_test_id("tasks-summary")).to_be_visible()
    expect(page.get_by_test_id("tasks-by-project")).to_contain_text("Задачи по проектам")
    expect(page.get_by_test_id("tasks-create-form")).to_be_visible()
    page.get_by_test_id("task-dashboard-title").fill("Задача без перехода")
    page.get_by_test_id("task-dashboard-description").fill("Список должен обновиться на текущем экране.")
    page.get_by_test_id("new-task").click()
    expect(page).to_have_url(re.compile(r"view=tasks"))
    expect(page.get_by_test_id("tasks-create-form")).to_be_visible()
    expect(page.locator('[data-testid^="task-card-"]').filter(has_text="Задача без перехода")).to_be_visible()
    page.screenshot(path=str(tmp_path / "tasks-after-create.png"), full_page=True)


def _panel_post(page: Page, path: str, payload: dict[str, object]) -> dict[str, object]:
    return page.evaluate(
        """async ({path, payload}) => {
            const token = JSON.parse(document.querySelector('#operator-panel-startup').textContent).token;
            const response = await fetch(path, {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'X-Operator-Token': token},
                body: JSON.stringify(payload),
            });
            const body = await response.json();
            if (!response.ok) throw new Error(body.message);
            return body;
        }""",
        {"path": path, "payload": payload},
    )


def test_navigation_exposes_only_active_screen(page: Page, panel: str) -> None:
    page.goto(panel)
    assert page.locator(".global-nav > button span").all_text_contents() == [
        "Обзор", "Поиск", "Проекты", "Задачи", "Решения", "Память", "Активность", "Рекомендации", "Мои идеи",
    ]
    for view in ("overview", "search", "artem", "idea", "tasks", "memory"):
        page.get_by_test_id(f"tab-{view}").click()
        expect(page.get_by_test_id(f"tab-{view}")).to_have_class("active")
        expect(page.get_by_test_id(f"tab-{view}")).to_have_attribute("aria-current", "page")
        assert page.locator('[data-view].active').count() == 1
        if view == "overview":
            expect(page.get_by_test_id("overview-screen")).to_be_visible()
            expect(page.get_by_test_id("knowledge-screen")).to_be_hidden()
            expect(page.get_by_test_id("memory-screen")).to_be_hidden()
        elif view == "search":
            expect(page.get_by_test_id("search-screen")).to_be_visible()
            expect(page.get_by_test_id("knowledge-screen")).to_be_hidden()
            expect(page.get_by_test_id("memory-screen")).to_be_hidden()
        elif view in {"artem", "idea"}:
            expect(page.get_by_test_id("knowledge-screen")).to_be_visible()
            expect(page.get_by_test_id("memory-screen")).to_be_hidden()
        elif view == "tasks":
            expect(page.get_by_test_id("knowledge-screen")).to_be_hidden()
            expect(page.get_by_test_id("memory-screen")).to_be_hidden()
        else:
            expect(page.get_by_test_id("knowledge-screen")).to_be_hidden()
            expect(page.get_by_test_id("memory-screen")).to_be_visible()


def test_navigation_hides_overview_content_after_every_view_transition(page: Page, panel: str) -> None:
    page.goto(panel)

    screens = {
        "overview": "overview-screen",
        "search": "search-screen",
        "projects": "projects-screen",
        "activity": "activity-screen",
    }
    for view in ("search", "projects", "activity", "tasks", "overview", "search"):
        page.get_by_test_id(f"tab-{view}").click()
        for screen_view, test_id in screens.items():
            assertion = expect(page.get_by_test_id(test_id))
            if screen_view == view:
                assertion.to_be_visible()
            else:
                assertion.to_be_hidden()


def test_yadro_uses_monochrome_application_shell_and_context_heading(page: Page, panel: str, tmp_path: Path) -> None:
    page.goto(panel)

    styles = page.locator(".panel-header").evaluate(
        "header => ({position: getComputedStyle(header).position, borderRight: getComputedStyle(header).borderRightWidth, background: getComputedStyle(document.body).backgroundColor, activeBackground: getComputedStyle(document.querySelector('[data-testid=\\\"tab-overview\\\"]')).backgroundColor})"
    )

    assert styles == {
        "position": "fixed",
        "borderRight": "1px",
        "background": "rgb(16, 17, 18)",
        "activeBackground": "rgb(40, 42, 45)",
    }
    expect(page.get_by_test_id("workspace-context")).to_contain_text("Ядро")
    expect(page.get_by_test_id("page-title")).to_have_text("Обзор")
    page.screenshot(path=str(tmp_path / "monochrome-overview.png"), full_page=True)

    page.get_by_test_id("tab-tasks").click()
    expect(page.get_by_test_id("page-title")).to_have_text("Задачи")
    page.screenshot(path=str(tmp_path / "monochrome-tasks.png"), full_page=True)
    assert page.evaluate("""() => [...document.querySelectorAll('*')].every(node => {
        const values = [getComputedStyle(node).color, getComputedStyle(node).backgroundColor, getComputedStyle(node).borderColor];
        return values.every(value => { const rgb = value.match(/\\d+/g)?.map(Number); return !rgb || !(rgb[2] > rgb[0] + 8 && rgb[2] > rgb[1] + 8); });
    })""")


def test_reference_sidebar_exposes_the_full_navigation_without_footer_controls(page: Page, panel: str) -> None:
    page.set_viewport_size({"width": 1674, "height": 952})
    page.goto(panel)

    positions = page.locator(".global-nav > button:not([data-testid='tab-decisions'])").evaluate_all(
        "nodes => nodes.map(node => node.getBoundingClientRect().y)",
    )
    assert [label for _, label in sorted(zip(positions, page.locator(".global-nav > button:not([data-testid='tab-decisions']) span").all_text_contents()))] == [
        "Обзор", "Проекты", "Активность", "Рекомендации", "Мои идеи", "Задачи", "Память", "Поиск",
    ]
    assert page.locator(".panel-header").evaluate("node => getComputedStyle(node).width") == "350px"
    assert page.locator(".nav-footer").evaluate("node => getComputedStyle(node).display") == "none"
    assert page.locator("[data-testid='tab-overview'] svg").evaluate("node => getComputedStyle(node).width") == "27px"


def test_owner_overview_prioritizes_context_and_separates_navigation_levels(page: Page, panel: str) -> None:
    page.goto(panel)

    expect(page.get_by_test_id("overview-today-priority")).to_be_visible()
    overview_cards = page.locator('[data-testid="overview-screen"] > .overview-grid > .overview-card')
    expect(overview_cards.nth(0)).to_have_attribute("data-testid", "overview-today-priority")
    expect(overview_cards.nth(1)).to_have_attribute("data-testid", "overview-pending-decisions")
    expect(overview_cards.nth(2)).to_have_attribute("data-testid", "overview-high-priority")
    expect(overview_cards.nth(3)).to_have_attribute("data-testid", "overview-nearest-tasks")
    expect(overview_cards.nth(4)).to_have_attribute("data-testid", "overview-focus-today")
    expect(overview_cards.nth(5)).to_have_attribute("data-testid", "overview-recent-activity")
    expect(page.locator(".global-nav")).to_be_visible()
    expect(page.get_by_test_id("tab-overview")).to_have_attribute("aria-current", "page")

    page.get_by_test_id("tab-memory").click()
    expect(page.locator(".memory-secondary")).to_be_visible()
    expect(page.locator(".local-tabs")).to_be_hidden()
    page.locator(".memory-secondary > summary").click()
    expect(page.locator(".local-tabs")).to_be_visible()
    expect(page.get_by_test_id("tab-memory")).to_have_attribute("aria-current", "page")
    expect(page.locator('.local-tabs button.active')).to_have_text("Текущий контекст")


def test_owner_reviews_memory_candidates_with_required_rejection_reason(page: Page, panel: str) -> None:
    approve_id = "00000000-0000-4000-8000-000000000041"
    reject_id = "00000000-0000-4000-8000-000000000042"
    page.goto(f"{panel}/?view=memory")
    page.locator(".memory-secondary > summary").click()
    page.get_by_test_id("memory-tab-candidates").click()
    expect(page.get_by_test_id(f"memory-candidate-{approve_id}")).to_be_visible()
    page.get_by_test_id(f"memory-candidate-details-{approve_id}").click()
    expect(page.get_by_test_id(f"memory-candidate-content")).to_contain_text("Полный текст кандидата")
    page.get_by_test_id(f"memory-candidate-approve-{approve_id}").click()
    expect(page.get_by_test_id(f"memory-candidate-{approve_id}")).to_have_count(0)

    page.get_by_test_id(f"memory-candidate-details-{reject_id}").click()
    page.get_by_test_id(f"memory-candidate-reject-{reject_id}").click()
    expect(page.get_by_test_id(f"memory-candidate-feedback-{reject_id}")).to_contain_text("Укажите причину")
    page.get_by_test_id(f"memory-candidate-note-{reject_id}").fill("Не подтверждено источником")
    page.get_by_test_id(f"memory-candidate-reject-{reject_id}").click()
    expect(page.get_by_test_id("memory-candidates-empty")).to_be_visible()


def test_owner_resolves_memory_conflict_with_required_reason(page: Page, panel: str) -> None:
    conflict_candidate_id = "00000000-0000-4000-8000-000000000044"
    page.goto(f"{panel}/?view=memory")
    page.locator(".memory-secondary > summary").click()
    page.get_by_test_id("memory-tab-conflicts").click()
    card = page.locator('[data-testid^="memory-conflict-"]').filter(has_text="Конфликт E2E")
    expect(card).to_be_visible()
    expect(card.get_by_test_id("memory-existing-content")).to_have_text("Текущее значение")
    expect(card.get_by_test_id("memory-conflicting-content")).to_have_text("Новое значение")
    keep = card.locator(f'[data-testid^="memory-conflict-keep-"]')
    keep.click()
    expect(card.locator('[data-testid^="memory-conflict-feedback-"]')).to_contain_text("Укажите причину")
    card.locator('[data-testid^="memory-conflict-reason-"]').fill("Текущая запись подтверждена")
    keep.click()
    expect(page.get_by_test_id("memory-conflicts-empty")).to_be_visible()
    assert conflict_candidate_id not in page.locator("#memory-items").inner_text()


def test_focused_task_is_visible_from_top_middle_and_bottom_of_long_list(page: Page, panel: str) -> None:
    page.goto(panel)
    task_ids = []
    for index in range(9):
        task_ids.append(_create_task(page, f"Длинный список {index}", f"Контекст задачи {index}. " * 8))
        page.reload()
    for task_id in (task_ids[0], task_ids[len(task_ids) // 2], task_ids[-1]):
        page.goto(f"{panel}/?view=tasks&focus_task={task_id}#task-{task_id}")
        card = page.get_by_test_id(f"task-card-{task_id}")
        expect(card).to_be_in_viewport()
        expect(card).to_contain_text("Открытая задача")


def test_task_creation_is_idempotent_and_focuses_visible_card(page: Page, panel: str) -> None:
    page.goto(panel)
    task_id = _create_task(page, "Проверка", "Полное описание задачи для браузерного сценария.")
    # Reloading proves existing database state is rendered without another creation request.
    page.goto(f"{panel}/?view=artem")
    expect(page.get_by_test_id(f"task-feedback-{task_id}")).to_have_text("Задача уже создана")
    _open_tasks(page, task_id)
    card = page.get_by_test_id(f"task-card-{task_id}")
    expect(card).to_be_in_viewport()
    expect(card).to_have_class(re.compile(r"\btask-focused\b"))
    assert card.evaluate("node => getComputedStyle(node).backgroundColor") == "rgb(32, 34, 37)"
    expect(card).to_contain_text("Открытая задача")


def test_task_edit_persists_subproject_once_and_renders_it_in_project_detail(page: Page, panel: str) -> None:
    page.goto(panel)
    parent = _panel_post(page, "/api/projects", {"name": "E2E родитель", "description": "Родитель для задачи"})
    child = _panel_post(page, "/api/projects", {"name": "E2E подпроект", "description": "Подпроект для задачи", "parent_project_id": parent["id"]})
    task = _panel_post(page, "/api/tasks", {
        "title": "E2E задача подпроекта",
        "description": "Проверка назначения подпроекта.",
        "priority": "normal",
        "project_id": parent["id"],
    })
    task_id = str(task["id"])

    page.goto(f"{panel}/?view=tasks")
    page.get_by_test_id(f"task-details-toggle-{task_id}").click()
    page.get_by_test_id(f"task-edit-{task_id}").click()
    expect(page.get_by_test_id("task-project").locator("option")).to_have_count(3)
    page.get_by_test_id("task-project").select_option(str(parent["id"]))
    expect(page.get_by_test_id("task-subproject")).to_have_value("")
    page.get_by_test_id("task-subproject").select_option(str(child["id"]))
    expect(page.get_by_test_id("task-subproject")).to_have_value(str(child["id"]))
    request_payloads: list[str] = []
    page.on("request", lambda request: request_payloads.append(request.post_data or "") if request.url.endswith(f"/api/tasks/{task_id}/edit") else None)
    page.get_by_test_id("task-save").click()
    expect(page.get_by_test_id("task-modal")).to_be_hidden()
    assert str(child["id"]) in request_payloads[-1]

    feedback = page.get_by_test_id(f"task-edit-feedback-{task_id}")
    expect(feedback).to_have_count(1)
    expect(feedback).to_have_text("Изменения сохранены")
    expect(page.get_by_test_id(f"task-relationship-{task_id}")).to_have_text("E2E родитель / E2E подпроект")

    page.reload()
    expect(page.get_by_test_id(f"task-relationship-{task_id}")).to_have_text("E2E родитель / E2E подпроект")
    page.goto(f"{panel}/?view=projects&project_id={child['id']}&project_tab=tasks")
    project_task = page.locator("article").filter(has_text="E2E задача подпроекта")
    expect(project_task).to_contain_text("E2E задача подпроекта")
    page.get_by_test_id("tab-overview").click()
    page.get_by_test_id("tab-tasks").click()
    expect(page).not_to_have_url(re.compile(r"focus_task"))
    expect(page.locator(".focus-label")).to_have_count(0)


def test_subproject_workspace_keeps_global_menu_and_switches_real_scoped_tabs(page: Page, panel: str) -> None:
    page.set_viewport_size({"width": 1674, "height": 952})
    page.goto(panel)
    parent = _panel_post(page, "/api/projects", {"name": "Рабочий проект", "description": "Родитель"})
    child = _panel_post(page, "/api/projects", {"name": "Панель E2E", "description": "Контекст подпроекта", "parent_project_id": parent["id"]})
    task = _panel_post(page, "/api/tasks", {"title": "Задача подпроекта", "description": "Проверка вкладок", "priority": "high", "project_id": parent["id"], "subproject_id": child["id"]})

    page.goto(f"{panel}/?view=projects&project_id={child['id']}")
    expect(page.get_by_test_id(f"project-workspace-{child['id']}")).to_be_visible()
    expect(page.get_by_test_id("project-tab-overview")).to_have_attribute("aria-current", "page")
    nav = page.locator(".global-nav > button:not([data-testid='tab-decisions'])")
    positions = nav.evaluate_all("nodes => nodes.map(node => node.getBoundingClientRect().y)")
    assert [label for _, label in sorted(zip(positions, nav.locator("span").all_text_contents()))] == ["Обзор", "Проекты", "Активность", "Рекомендации", "Мои идеи", "Задачи", "Память", "Поиск"]
    expect(page.locator(".subproject-summary-card")).to_contain_text("1")
    expect(page.locator(".subproject-top-grid")).to_be_visible()
    expect(page.locator(".subproject-bottom-grid")).to_be_visible()
    expect(page.locator(".subproject-tags")).to_be_visible()
    geometry = page.evaluate("""() => {
      const box = selector => document.querySelector(selector).getBoundingClientRect();
      const top = box('.subproject-top-grid'), bottom = box('.subproject-bottom-grid'), tags = box('.subproject-tags');
      const cards = [...document.querySelectorAll('.subproject-bottom-grid > .subproject-mini-card')].map(node => node.getBoundingClientRect());
      return {top, bottom, tags, cards};
    }""")
    assert geometry["top"]["y"] == pytest.approx(186, abs=1)
    assert geometry["top"]["height"] == pytest.approx(343, abs=1)
    assert geometry["bottom"]["y"] == pytest.approx(545, abs=1)
    assert geometry["bottom"]["height"] == pytest.approx(260, abs=1)
    assert geometry["tags"]["y"] == pytest.approx(820, abs=1)
    assert geometry["cards"][0]["width"] > geometry["cards"][1]["width"]
    assert geometry["cards"][2]["width"] > geometry["cards"][0]["width"]

    page.get_by_test_id("project-tab-tasks").click()
    expect(page.get_by_test_id("project-tab-tasks")).to_have_attribute("aria-current", "page")
    expect(page.get_by_test_id(f"task-card-{task['id']}")).to_contain_text("Задача подпроекта")
    expect(page).to_have_url(re.compile(r"project_tab=tasks"))

    page.get_by_test_id("project-tab-artem").click()
    expect(page.get_by_test_id("project-tab-artem")).to_have_attribute("aria-current", "page")
    expect(page.locator(".subproject-entry-list")).to_be_visible()


def test_details_are_single_and_actions_share_row(page: Page, panel: str) -> None:
    page.goto(panel)
    text = "Полное описание должно быть видно только после открытия подробностей, поэтому этот длинный контекст не должен целиком повторяться в заголовке задачи."
    task_id = _create_task(page, "Детали", text)
    _open_tasks(page, task_id)
    card = page.get_by_test_id(f"task-card-{task_id}")
    detail = page.get_by_test_id(f"task-details-{task_id}")
    expect(detail.locator(".row-detail")).to_be_hidden()
    expect(card.locator(":scope > button")).to_have_count(0)
    expect(page.get_by_test_id(f"task-actions-{task_id}")).to_be_hidden()
    for suffix in ("completed", "cancelled"):
        expect(page.get_by_test_id(f"task-{suffix}-{task_id}")).to_be_hidden()
    page.get_by_test_id(f"task-details-toggle-{task_id}").click()
    expect(detail.locator(".row-detail")).to_be_visible()
    expect(page.get_by_test_id(f"task-actions-{task_id}")).to_have_css("display", "flex")
    assert card.inner_text().count(text) == 1
    page.get_by_test_id(f"task-details-toggle-{task_id}").click()
    expect(detail.locator(".row-detail")).to_be_hidden()


def test_summary_and_action_plan_use_visible_modal_and_all_close_paths(page: Page, panel: str) -> None:
    page.goto(panel)
    _add_entry(page, "Выжимка", "Проверить модальное окно.")
    modal = page.get_by_test_id("modal-overlay")
    page.get_by_test_id("summary").click()
    expect(modal).to_be_visible()
    expect(page.locator("body")).to_have_css("overflow", "hidden")
    page.get_by_test_id("modal-close").click()
    expect(modal).to_be_hidden()
    page.get_by_test_id("summary").click()
    expect(modal).to_be_visible()
    page.keyboard.press("Escape")
    expect(modal).to_be_hidden()
    page.get_by_test_id("action-plan").click()
    expect(modal).to_be_visible()
    modal.click(position={"x": 2, "y": 2})
    expect(modal).to_be_hidden()
    expect(page.locator("body")).to_have_css("overflow", "visible")


def test_task_statuses_persist_after_reload(page: Page, panel: str) -> None:
    page.goto(panel)
    completed_id = _create_task(page, "Выполнить", "Завершить эту задачу.")
    _open_tasks(page, completed_id)
    page.get_by_test_id(f"task-details-toggle-{completed_id}").click()
    with page.expect_response(lambda response: response.url.endswith(f"/api/tasks/{completed_id}/status") and response.request.method == "POST") as completed_response:
        page.get_by_test_id(f"task-completed-{completed_id}").evaluate("button => button.click()")
    assert completed_response.value.json()["status"] == "completed"
    expect(page.get_by_test_id(f"task-card-{completed_id}").locator(":scope > .task-check")).to_be_checked()
    page.reload()
    expect(page.get_by_test_id(f"task-card-{completed_id}").locator(":scope > .task-check")).to_be_checked()
    with page.expect_response(lambda response: response.url.endswith(f"/api/tasks/{completed_id}/status") and response.request.method == "POST") as reopened_response:
        page.get_by_test_id(f"task-card-{completed_id}").locator(":scope > .task-check").uncheck()
    assert reopened_response.value.json()["status"] == "open"
    reopened = page.get_by_test_id(f"task-card-{completed_id}").locator(":scope > .task-check")
    expect(reopened).not_to_be_checked()
    expect(reopened).to_be_enabled()
    page.reload()
    expect(page.get_by_test_id(f"task-card-{completed_id}").locator(":scope > .task-check")).not_to_be_checked()
    page.goto(panel)
    cancelled_id = _create_task(page, "Отменить", "Отменить эту задачу.")
    _open_tasks(page, cancelled_id)
    page.get_by_test_id(f"task-details-toggle-{cancelled_id}").click()
    page.get_by_test_id(f"task-cancelled-{cancelled_id}").evaluate("button => button.click()")
    checkbox = page.get_by_test_id(f"task-card-{cancelled_id}").locator(":scope > .task-check")
    expect(checkbox).not_to_be_checked()
    expect(checkbox).to_be_disabled()


def test_task_focus_is_only_kept_for_explicit_open_action(page: Page, panel: str) -> None:
    page.goto(panel)
    task_id = _create_task(page, "Явно открыть", "Проверка навигации без липкого фокуса.")
    _open_tasks(page, task_id)
    focused = page.get_by_test_id(f"task-card-{task_id}")
    expect(focused).to_have_class(re.compile(r"\btask-focused\b"))
    expect(focused.locator(".focus-label")).to_have_text("Открытая задача")

    page.get_by_test_id("tab-projects").click()
    expect(page).not_to_have_url(re.compile(r"focus_task"))
    page.get_by_test_id("tab-tasks").click()
    expect(page).not_to_have_url(re.compile(r"focus_task"))
    expect(page.locator(".focus-label")).to_have_count(0)
    expect(page.get_by_test_id(f"task-card-{task_id}")).not_to_have_class(re.compile(r"\btask-focused\b"))


def test_unified_intake_accepts_text_url_and_text_file_and_keeps_invalid_url(page: Page, panel: str) -> None:
    page.goto(panel)
    page.get_by_test_id("tab-artem").click()

    page.get_by_test_id("intake-text").click()
    expect(page.get_by_test_id("add-text")).to_be_visible()
    expect(page.get_by_test_id("intake-description-row")).to_be_hidden()
    page.get_by_test_id("add-text").fill("Текст из входящего потока")
    page.get_by_test_id("add-entry").click()
    expect(page.get_by_test_id("entries")).to_contain_text("Текст из входящего потока")

    page.get_by_test_id("intake-url").click()
    expect(page.get_by_test_id("intake-url")).to_have_attribute("aria-pressed", "true")
    expect(page.get_by_test_id("add-text")).to_be_hidden()
    expect(page.get_by_test_id("intake-description-row")).to_be_visible()
    page.locator("#intake-url").fill("not-a-url")
    page.get_by_test_id("add-entry").click()
    expect(page.locator("#message")).to_contain_text("Введите корректную ссылку")
    expect(page.locator("#intake-url")).to_have_value("not-a-url")
    page.locator("#intake-url").fill("https://example.com/source")
    page.locator("#intake-description").fill("Проверить источник перед использованием")
    page.get_by_test_id("add-entry").click()
    expect(page.get_by_test_id("entries")).to_contain_text("https://example.com/source")
    expect(page.get_by_test_id("entries")).to_contain_text("Проверить источник перед использованием")
    page.locator('[data-testid^="knowledge-entry-"]').filter(has_text="Проверить источник перед использованием").locator('[data-testid^="create-task-"]').click()
    expect(page.get_by_test_id("task-description")).to_have_value("Проверить источник перед использованием\n\nhttps://example.com/source")
    page.get_by_test_id("task-save").click()
    page.get_by_test_id("tab-tasks").click()
    expect(page.locator('[data-testid^="task-card-"]').first).to_contain_text("Проверить источник перед использованием")

    page.get_by_test_id("tab-artem").click()
    page.get_by_test_id("intake-file").click()
    expect(page.get_by_test_id("add-text")).to_be_hidden()
    expect(page.get_by_test_id("intake-description-row")).to_be_visible()
    page.locator("#intake-description").fill("Согласовать содержание файла")
    page.locator("#intake-file").set_input_files({"name": "brief.md", "mimeType": "text/markdown", "buffer": b"# Brief\nFile input"})
    page.get_by_test_id("add-entry").click()
    expect(page.get_by_test_id("entries")).to_contain_text("brief")
    expect(page.get_by_test_id("entries")).to_contain_text("File input")
    expect(page.get_by_test_id("entries")).to_contain_text("Согласовать содержание файла")

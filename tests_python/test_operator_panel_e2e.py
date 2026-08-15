from __future__ import annotations

import socket
import subprocess
import sys
import time
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
    page.get_by_test_id("add-topic").fill(topic)
    page.get_by_test_id("add-text").fill(text)
    page.get_by_test_id("add-entry").click()
    page.wait_for_function(
        """() => [...document.querySelectorAll('[data-testid^="create-task-"]')]
        .some(node => /[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(node.dataset.testid))"""
    )
    action = page.locator('[data-testid^="create-task-"]').first
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


def test_navigation_exposes_only_active_screen(page: Page, panel: str) -> None:
    page.goto(panel)
    for view in ("artem", "idea", "tasks", "memory"):
        page.get_by_test_id(f"tab-{view}").click()
        expect(page.get_by_test_id(f"tab-{view}")).to_have_class("active")
        expect(page.get_by_test_id(f"tab-{view}")).to_have_attribute("aria-current", "page")
        assert page.locator('[data-testid="tab-artem"].active,[data-testid="tab-idea"].active,[data-testid="tab-tasks"].active,[data-testid="tab-memory"].active').count() == 1
        if view in {"artem", "idea"}:
            expect(page.get_by_test_id("knowledge-screen")).to_be_visible()
            expect(page.get_by_test_id("memory-screen")).to_be_hidden()
        elif view == "tasks":
            expect(page.get_by_test_id("knowledge-screen")).to_be_hidden()
            expect(page.get_by_test_id("memory-screen")).to_be_hidden()
        else:
            expect(page.get_by_test_id("knowledge-screen")).to_be_hidden()
            expect(page.get_by_test_id("memory-screen")).to_be_visible()


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
    page.reload()
    expect(page.get_by_test_id(f"task-feedback-{task_id}")).to_have_text("Задача уже создана")
    _open_tasks(page, task_id)
    card = page.get_by_test_id(f"task-card-{task_id}")
    expect(card).to_be_in_viewport()
    assert card.evaluate("node => getComputedStyle(node).borderTopWidth") == "3px"
    assert card.evaluate("node => getComputedStyle(node).backgroundColor") == "rgb(18, 55, 69)"
    expect(card).to_contain_text("Открытая задача")


def test_details_are_single_and_actions_share_row(page: Page, panel: str) -> None:
    page.goto(panel)
    text = "Полное описание должно быть видно только после открытия подробностей, поэтому этот длинный контекст не должен целиком повторяться в заголовке задачи."
    task_id = _create_task(page, "Детали", text)
    _open_tasks(page, task_id)
    card = page.get_by_test_id(f"task-card-{task_id}")
    expect(page.get_by_test_id(f"task-details-{task_id}")).to_be_hidden()
    expect(page.get_by_test_id(f"task-actions-{task_id}")).to_have_css("display", "flex")
    for suffix in ("details-toggle", "completed", "cancelled"):
        expect(page.get_by_test_id(f"task-{suffix}-{task_id}")).to_be_visible()
    page.get_by_test_id(f"task-details-toggle-{task_id}").click()
    expect(page.get_by_test_id(f"task-details-{task_id}")).to_be_visible()
    assert card.inner_text().count(text) == 1
    page.get_by_test_id(f"task-details-toggle-{task_id}").click()
    expect(page.get_by_test_id(f"task-details-{task_id}")).to_be_hidden()


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
    page.get_by_test_id(f"task-completed-{completed_id}").click()
    expect(page.get_by_test_id(f"task-card-{completed_id}")).to_contain_text("completed")
    page.reload()
    expect(page.get_by_test_id(f"task-card-{completed_id}")).to_contain_text("completed")
    page.goto(panel)
    cancelled_id = _create_task(page, "Отменить", "Отменить эту задачу.")
    _open_tasks(page, cancelled_id)
    page.get_by_test_id(f"task-cancelled-{cancelled_id}").click()
    expect(page.get_by_test_id(f"task-card-{cancelled_id}")).to_contain_text("cancelled")

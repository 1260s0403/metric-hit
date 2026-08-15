from __future__ import annotations

import socket
import subprocess
import sys
import time
import re
from datetime import date, timedelta
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, expect, sync_playwright

from metrichit_os.knowledge_store import KnowledgeStore


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _database(tmp_path: Path) -> Path:
    database = tmp_path / "task-panel-e2e.sqlite"
    subprocess.run(["node", "scripts/init-memory.mjs", str(database)], check=True, capture_output=True, text=True)
    return database


def _seed_task(store: KnowledgeStore, *, topic: str, text: str, priority: str = "normal", due_date: str | None = None) -> dict[str, object]:
    entry = store.add(kind="artem", topic=topic, text=text)
    task = store.to_task(entry_id=str(entry["id"]))
    return store.edit_task(
        task_id=str(task["id"]), title=str(task["title"]), description=str(task["description"]),
        priority=priority, due_date=due_date,
    )


@pytest.fixture
def browser() -> Browser:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        try:
            yield browser
        finally:
            browser.close()


@pytest.fixture
def panel(tmp_path: Path) -> tuple[str, KnowledgeStore]:
    database = _database(tmp_path)
    store = KnowledgeStore(database)
    port = _free_port()
    process = subprocess.Popen(
        [sys.executable, "-m", "metrichit_os", "operator-panel", "--db", str(database), "--port", str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
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
        yield base_url, store
    finally:
        process.terminate()
        process.wait(timeout=5)


@pytest.fixture
def page(browser: Browser, panel: tuple[str, KnowledgeStore], tmp_path: Path) -> Page:
    page = browser.new_page(viewport={"width": 1200, "height": 700})
    try:
        yield page
    except BaseException:
        screenshots = tmp_path / "screenshots"
        screenshots.mkdir(exist_ok=True)
        page.screenshot(path=str(screenshots / "task-panel-failure.png"), full_page=True)
        raise
    finally:
        page.close()


def _open_tasks(page: Page, panel: str) -> None:
    page.goto(f"{panel}/?view=tasks")
    expect(page.get_by_test_id("tab-tasks")).to_have_attribute("aria-current", "page")


def test_edit_shows_local_confirmation_and_persists_after_reload(page: Page, panel: tuple[str, KnowledgeStore]) -> None:
    base_url, store = panel
    task = _seed_task(store, topic="Before title", text="Before description")
    task_id = str(task["id"])
    _open_tasks(page, base_url)

    page.get_by_test_id(f"task-details-toggle-{task_id}").click()
    page.get_by_test_id(f"task-edit-{task_id}").click()
    page.get_by_test_id(f"task-edit-title-{task_id}").fill("After title")
    page.get_by_test_id(f"task-edit-description-{task_id}").fill("After description")
    page.get_by_test_id(f"task-edit-priority-{task_id}").select_option("high")
    page.get_by_test_id(f"task-edit-due-date-{task_id}").fill((date.today() + timedelta(days=2)).isoformat())
    page.get_by_test_id(f"task-edit-save-{task_id}").click()
    expect(page.get_by_test_id(f"task-edit-feedback-{task_id}")).to_have_text("Изменения сохранены")
    card = page.get_by_test_id(f"task-card-{task_id}")
    expect(card).to_have_class(re.compile(r"\btask-focused\b"))
    page.reload()
    expect(page.get_by_test_id(f"task-card-{task_id}")).to_contain_text("After title")
    page.get_by_test_id(f"task-details-toggle-{task_id}").click()
    expect(page.get_by_test_id(f"task-details-{task_id}")).to_contain_text("After description")
    expect(page.get_by_test_id(f"task-card-{task_id}")).to_contain_text("high")


def test_combined_filters_reset_and_recommended_order(page: Page, panel: tuple[str, KnowledgeStore]) -> None:
    base_url, store = panel
    today = date.today()
    overdue = _seed_task(store, topic="Overdue high", text="match", priority="high", due_date=(today - timedelta(days=1)).isoformat())
    _seed_task(store, topic="Today normal", text="match", priority="normal", due_date=today.isoformat())
    high = _seed_task(store, topic="High no date", text="match", priority="high")
    _seed_task(store, topic="Low no date", text="match", priority="low")
    _open_tasks(page, base_url)
    cards = page.locator('[data-testid^="task-card-"]')
    expect(cards.nth(0)).to_have_attribute("data-testid", f"task-card-{overdue['id']}")
    expect(cards.nth(2)).to_have_attribute("data-testid", f"task-card-{high['id']}")

    page.get_by_test_id("task-status-filter").select_option("open")
    page.get_by_test_id("task-priority-filter").select_option("high")
    page.get_by_test_id("task-due-filter").select_option("overdue")
    expect(page.get_by_test_id("task-count")).to_contain_text("1")
    expect(cards).to_have_count(1)
    expect(page).to_have_url(re.compile(r"status=open.*priority=high.*due=overdue"))
    page.get_by_test_id("task-reset").click()
    expect(page.get_by_test_id("task-status-filter")).to_have_value("all")
    expect(page.get_by_test_id("task-priority-filter")).to_have_value("all")
    expect(page.get_by_test_id("task-due-filter")).to_have_value("all")
    expect(cards).to_have_count(4)


def test_today_open_focuses_the_card(page: Page, panel: tuple[str, KnowledgeStore]) -> None:
    base_url, store = panel
    task = _seed_task(store, topic="Open from today", text="urgent", priority="high", due_date=date.today().isoformat())
    task_id = str(task["id"])
    _open_tasks(page, base_url)
    expect(page.get_by_test_id("today-tasks")).to_be_visible()
    page.get_by_test_id(f"today-open-{task_id}").click()
    expect(page).to_have_url(re.compile(rf"focus_task={task_id}"))
    card = page.get_by_test_id(f"task-card-{task_id}")
    expect(card).to_be_in_viewport()
    expect(card).to_have_class(re.compile(r"\btask-focused\b"))


def test_completed_task_disappears_from_open_and_today(page: Page, panel: tuple[str, KnowledgeStore]) -> None:
    base_url, store = panel
    task = _seed_task(store, topic="Complete today", text="urgent", priority="high", due_date=date.today().isoformat())
    task_id = str(task["id"])
    page.goto(f"{base_url}/?view=tasks&status=open")
    expect(page.get_by_test_id(f"today-open-{task_id}")).to_be_visible()
    page.get_by_test_id(f"task-completed-{task_id}").click()
    expect(page.get_by_test_id(f"task-card-{task_id}")).to_have_count(0)
    expect(page.get_by_test_id(f"today-open-{task_id}")).to_have_count(0)


def test_narrow_viewport_has_no_horizontal_overflow(page: Page, panel: tuple[str, KnowledgeStore]) -> None:
    base_url, store = panel
    _seed_task(store, topic="A very long task title that should wrap without forcing a horizontal scrollbar", text="Description")
    page.set_viewport_size({"width": 360, "height": 700})
    _open_tasks(page, base_url)
    assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")

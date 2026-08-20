from __future__ import annotations

import socket
import sqlite3
import subprocess
import sys
import time
import re
from pathlib import Path
from uuid import uuid4

import pytest
from playwright.sync_api import Browser, Page, expect, sync_playwright

from metrichit_os.knowledge_store import KnowledgeStore


def _port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture
def browser() -> Browser:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        yield browser
        browser.close()


@pytest.fixture
def panel(tmp_path: Path) -> tuple[str, dict[str, str]]:
    database = tmp_path / "search-e2e.sqlite"
    subprocess.run(["node", "scripts/init-memory.mjs", str(database)], check=True, capture_output=True, text=True)
    store = KnowledgeStore(database)
    artem = store.add(kind="artem", topic="Поиск Ёлка", text="текст поиск", tags="маркер")
    idea = store.add(kind="idea", topic="Идея поиска", text="ёлка в идее")
    escaped = store.add(kind="artem", topic="<img src=x onerror=alert(1)> needle-html", text="safe")
    task = store.to_task(entry_id=str(idea["id"]))
    with sqlite3.connect(database) as connection:
        source = str(uuid4())
        fact, decision, document = str(uuid4()), str(uuid4()), str(uuid4())
        connection.execute("INSERT INTO sources (id,type,title,content,author) VALUES (?,?,?,?,?)", (source, "test", "Source", "x", "owner"))
        connection.execute("INSERT INTO memory_items (id,type,semantic_key,title,content,source_id,author) VALUES (?,?,?,?,?,?,?)", (fact, "fact", "search.fact", "Факт поиска", "ёлка", source, "owner"))
        connection.execute("INSERT INTO decisions (id,type,title,content,source_id,author) VALUES (?,?,?,?,?,?)", (decision, "decision", "Решение поиска", "ёлка", source, "owner"))
        connection.execute("INSERT INTO documents (id,type,title,content,data_json,status,author) VALUES (?,?,?,?,?,'active','owner')", (document, "memory_document", "Документ поиска", "ёлка", "{}"))
    port = _port()
    process = subprocess.Popen([sys.executable, "-m", "metrichit_os", "operator-panel", "--db", str(database), "--port", str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    base = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=.2):
                break
        except OSError:
            time.sleep(.1)
    else:
        process.terminate(); raise RuntimeError(process.stderr.read())
    try:
        yield base, {"artem": str(artem["id"]), "idea": str(idea["id"]), "escaped": str(escaped["id"]), "task": str(task["id"]), "fact": fact, "decision": decision, "document": document}
    finally:
        process.terminate(); process.wait(timeout=5)


@pytest.fixture
def page(browser: Browser, panel: tuple[str, dict[str, str]]) -> Page:
    page = browser.new_page(viewport={"width": 1200, "height": 800})
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    yield page
    page.close()
    assert errors == []


def _search(page: Page, base: str, query: str) -> None:
    page.goto(f"{base}/?view=search")
    expect(page.get_by_test_id("tab-search")).to_have_attribute("aria-current", "page")
    page.get_by_test_id("global-search-query").fill(query)
    page.get_by_test_id("global-search-submit").click()


def test_global_search_filters_navigation_back_and_mobile(page: Page, panel: tuple[str, dict[str, str]]) -> None:
    base, ids = panel
    _search(page, base, "елка")
    expect(page.get_by_test_id("search-result-artem-" + ids["artem"])).to_be_visible()
    expect(page.get_by_test_id("search-result-idea-" + ids["idea"])).to_be_visible()
    expect(page.get_by_test_id("search-result-fact-" + ids["fact"])).to_be_visible()
    expect(page.get_by_test_id("search-result-decision-" + ids["decision"])).to_be_visible()
    expect(page.get_by_test_id("search-result-document-" + ids["document"])).to_be_visible()
    page.get_by_test_id("global-search-type").select_option("idea")
    page.get_by_test_id("global-search-submit").click()
    expect(page.get_by_test_id("global-search-results")).to_have_count(1)
    page.get_by_test_id("search-result-idea-" + ids["idea"]).click()
    expect(page.get_by_test_id("tab-idea")).to_have_attribute("aria-current", "page")
    expect(page.get_by_test_id("knowledge-entry-" + ids["idea"])).to_have_class(re.compile(r"\bentry-focused\b"))
    page.go_back()
    expect(page.get_by_test_id("tab-search")).to_have_attribute("aria-current", "page")
    expect(page.get_by_test_id("global-search-query")).to_have_value("елка")
    expect(page.get_by_test_id("global-search-type")).to_have_value("idea")
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")


def test_search_empty_hint_and_task_and_memory_targets(page: Page, panel: tuple[str, dict[str, str]]) -> None:
    base, ids = panel
    page.goto(f"{base}/?view=search")
    expect(page.get_by_test_id("global-search-count")).to_have_text("Введите запрос для поиска.")
    page.get_by_test_id("global-search-query").fill("nothing-here")
    page.get_by_test_id("global-search-submit").click()
    expect(page.get_by_test_id("search-empty")).to_have_text("Ничего не найдено.")
    _search(page, base, "елка")
    page.get_by_test_id("global-search-type").select_option("task")
    page.get_by_test_id("global-search-submit").click()
    page.get_by_test_id("search-result-task-" + ids["task"]).click()
    expect(page.get_by_test_id("task-card-" + ids["task"])).to_have_class(re.compile(r"\btask-focused\b"))
    _search(page, base, "елка")
    page.get_by_test_id("global-search-type").select_option("fact")
    page.get_by_test_id("global-search-submit").click()
    page.get_by_test_id("search-result-fact-" + ids["fact"]).click()
    expect(page.get_by_test_id("memory-fact-" + ids["fact"])).to_have_class(re.compile(r"\bentry-focused\b"))


def test_search_escapes_result_text(page: Page, panel: tuple[str, dict[str, str]]) -> None:
    base, ids = panel
    _search(page, base, "needle-html")
    card = page.get_by_test_id("search-result-artem-" + ids["escaped"])
    expect(card).to_contain_text("<img src=x onerror=alert(1)>")
    expect(card.locator("img")).to_have_count(0)

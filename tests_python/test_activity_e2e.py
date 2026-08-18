from __future__ import annotations

import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from metrichit_os.knowledge_store import KnowledgeStore
from metrichit_os.project_store import ProjectStore
from metrichit_os.activity import list_activity


def test_activity_browser_flow(tmp_path: Path) -> None:
    database = tmp_path / "activity-e2e.sqlite"
    subprocess.run(["node", "scripts/init-memory.mjs", str(database)], check=True, capture_output=True, text=True)
    store = KnowledgeStore(database); project, _ = ProjectStore(database).create(name="Панель", description="Работа над панелью")
    entry = store.add(kind="idea", topic="<b>Idea</b>", text="text", project_id=str(project["id"])); task = store.to_task(entry_id=str(entry["id"]), project_id=str(project["id"])); store.edit_task(task_id=str(task["id"]), title="Edited", description="new", priority="high", due_date="2026-08-20")
    with socket.socket() as probe: probe.bind(("127.0.0.1", 0)); port = probe.getsockname()[1]
    process = subprocess.Popen([sys.executable, "-m", "metrichit_os", "operator-panel", "--db", str(database), "--port", str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=.1): break
            except OSError: time.sleep(.1)
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True); page = browser.new_page(viewport={"width": 1600, "height": 1024}); errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error))); page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
            page.goto(f"http://127.0.0.1:{port}/?view=activity", wait_until="domcontentloaded")
            assert page.get_by_test_id("tab-activity").get_attribute("aria-current") == "page"
            page.wait_for_timeout(500); assert page.get_by_test_id("activity-list").locator("article").count() >= 1
            page.get_by_test_id("activity-type").select_option("task"); page.get_by_test_id("activity-action").select_option("update"); page.get_by_test_id("activity-apply").click()
            page.evaluate("history.back()"); page.wait_for_timeout(300); assert page.get_by_test_id("activity-type").input_value() == "all"
            page.get_by_test_id("activity-type").select_option("task"); page.get_by_test_id("activity-action").select_option("update"); page.get_by_test_id("activity-apply").click()
            page.locator('[data-testid^="activity-event-"]').first.click(); assert page.locator(".activity-v4-drawer").is_visible(); assert "{" not in page.locator(".activity-v4-drawer").inner_text()
            row = page.locator('[data-testid^="activity-event-"]').first; before = row.bounding_box(); drawer = page.locator(".activity-v4-drawer").bounding_box(); after = row.bounding_box()
            assert before and after and drawer and abs(before["width"] - after["width"]) < 1 and drawer["x"] >= after["x"] + after["width"]
            page.locator('[data-testid^="activity-open-"]').first.click(); expect(page.locator(".task-focused")).to_have_count(1)
            page.goto(f"http://127.0.0.1:{port}/?view=activity", wait_until="domcontentloaded")
            page.get_by_test_id("activity-project").select_option(str(project["id"])); assert page.get_by_test_id("activity-list").locator("article").count() >= 1
            page.locator('.activity-v4-filter[data-type="project"]').click(); assert page.get_by_test_id("activity-list").locator("article").count() >= 1
            page.get_by_test_id("activity-period").select_option("today"); assert "period=today" in page.url and page.get_by_test_id("activity-list").locator("article").count() >= 1
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth") and not errors
            browser.close()
    finally:
        process.terminate(); process.wait(timeout=5)


def test_activity_filters_project_scope_and_time(tmp_path: Path) -> None:
    database = tmp_path / "activity-filters.sqlite"
    subprocess.run(["node", "scripts/init-memory.mjs", str(database)], check=True, capture_output=True, text=True)
    project, _ = ProjectStore(database).create(name="Клиенты", description="")
    KnowledgeStore(database).create_task(title="Scoped task", description="", project_id=str(project["id"]))
    assert any(item["title"] == "Scoped task" for item in list_activity(database, project=str(project["id"]))["items"])
    assert any(item["object_type"] == "project" for item in list_activity(database, item_type="project")["items"])
    import sqlite3
    with sqlite3.connect(database) as db:
        old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
        db.execute("INSERT INTO audit_log (id,type,title,data_json,author,created_at,updated_at,access_level,version,entity_type,entity_id,action) VALUES ('00000000-0000-0000-0000-000000000001','memory_change','Old event','{}','owner',?,?,'restricted',1,'memory_item','00000000-0000-0000-0000-000000000002','create')", (old, old))
    assert not list_activity(database, period="30", item_type="memory")["items"]

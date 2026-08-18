from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from metrichit_os.knowledge_store import KnowledgeStore


def test_activity_browser_flow(tmp_path: Path) -> None:
    database = tmp_path / "activity-e2e.sqlite"
    subprocess.run(["node", "scripts/init-memory.mjs", str(database)], check=True, capture_output=True, text=True)
    store = KnowledgeStore(database); entry = store.add(kind="idea", topic="<b>Idea</b>", text="text"); task = store.to_task(entry_id=str(entry["id"])); store.edit_task(task_id=str(task["id"]), title="Edited", description="new", priority="high", due_date="2026-08-20")
    with socket.socket() as probe: probe.bind(("127.0.0.1", 0)); port = probe.getsockname()[1]
    process = subprocess.Popen([sys.executable, "-m", "metrichit_os", "operator-panel", "--db", str(database), "--port", str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=.1): break
            except OSError: time.sleep(.1)
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True); page = browser.new_page(viewport={"width": 390, "height": 844}); errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error))); page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
            page.goto(f"http://127.0.0.1:{port}/?view=activity", wait_until="networkidle")
            assert page.get_by_test_id("tab-activity").get_attribute("aria-current") == "page"
            page.wait_for_timeout(500); assert page.get_by_test_id("activity-list").locator("article").count() >= 1
            page.get_by_test_id("activity-type").select_option("task"); page.get_by_test_id("activity-action").select_option("update"); page.get_by_test_id("activity-apply").click()
            page.go_back(); page.wait_for_timeout(300); assert page.get_by_test_id("activity-type").input_value() == "all"
            page.get_by_test_id("activity-type").select_option("task"); page.get_by_test_id("activity-action").select_option("update"); page.get_by_test_id("activity-apply").click()
            page.locator('[data-testid^="activity-event-"]').first.click(); assert page.locator(".activity-v4-drawer").is_visible(); assert "{" not in page.locator(".activity-v4-drawer").inner_text()
            page.locator('[data-testid^="activity-open-"]').first.click(); expect(page.locator(".task-focused")).to_have_count(1)
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth") and not errors
            browser.close()
    finally:
        process.terminate(); process.wait(timeout=5)

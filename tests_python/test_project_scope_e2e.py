from __future__ import annotations

import json
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from metrichit_os.project_scope import DEFAULT_PROJECT_ID, YADRO_CONTROL_PLANE_PROJECT_ID
from metrichit_os.project_store import ProjectStore


def test_edge_creates_scoped_task_recommendation_and_idea_and_rejects_cross_project(tmp_path: Path) -> None:
    database = tmp_path / "scope-e2e.sqlite"
    subprocess.run(["node", "scripts/init-memory.mjs", str(database)], check=True, capture_output=True)
    projects = ProjectStore(database)
    metric_child, _ = projects.create(name="MetricHit SEO", description="SEO", parent_project_id=DEFAULT_PROJECT_ID)
    core_child, _ = projects.create(name="Core infra", description="Core", parent_project_id=YADRO_CONTROL_PLANE_PROJECT_ID)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    process = subprocess.Popen(
        [sys.executable, "-m", "metrichit_os", "operator-panel", "--db", str(database), "--port", str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(60):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=.1):
                    break
            except OSError:
                time.sleep(.1)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.goto(f"http://127.0.0.1:{port}/?view=idea")
            expect(page.get_by_test_id("active-scope")).to_contain_text("MetricHit")
            expect(page.get_by_test_id("idea-project")).to_have_value(DEFAULT_PROJECT_ID)
            page.get_by_test_id("idea-topic").fill("Scoped idea")
            page.get_by_test_id("idea-description").fill("Idea body")
            page.get_by_test_id("idea-submit").click()

            page.get_by_test_id("tab-artem").click()
            page.locator('#add [name="topic"]').fill("Scoped recommendation")
            page.locator('#add [name="text"]').fill("Recommendation body")
            page.get_by_test_id("add-entry").click()
            expect(page.locator("#message")).to_contain_text("добавлен")

            page.get_by_test_id("tab-tasks").click()
            page.get_by_test_id("new-task").click()
            expect(page.get_by_test_id("task-project")).to_have_value(DEFAULT_PROJECT_ID)
            page.get_by_test_id("task-subproject").select_option(str(metric_child["id"]))
            page.get_by_test_id("task-title").fill("Scoped task")
            page.get_by_test_id("task-description").fill("Task body")
            page.get_by_test_id("task-save").click()
            page.wait_for_url("**focus_task=**")

            invalid = page.evaluate(
                """async ({projectId, childId}) => {
                  const startup=JSON.parse(document.querySelector('#operator-panel-startup').textContent);
                  const response=await fetch('/api/tasks',{method:'POST',headers:{'Content-Type':'application/json','X-Operator-Token':startup.token},body:JSON.stringify({title:'Cross project',description:'x',project_id:projectId,subproject_id:childId})});
                  return {status:response.status,body:await response.json()};
                }""",
                {"projectId": DEFAULT_PROJECT_ID, "childId": str(core_child["id"])},
            )
            assert invalid["status"] == 400 and "belong" in invalid["body"]["message"]
            with sqlite3.connect(database) as connection:
                scopes = connection.execute(
                    "SELECT type,title,json_extract(data_json,'$.project_id'),json_extract(data_json,'$.subproject_id') FROM documents WHERE type='knowledge_entry' UNION ALL SELECT type,title,json_extract(data_json,'$.project_id'),json_extract(data_json,'$.subproject_id') FROM tasks WHERE type='standalone_task'"
                ).fetchall()
            browser.close()
    finally:
        process.terminate()
        process.wait(timeout=5)

    assert {row[1] for row in scopes} == {"Scoped idea", "Scoped recommendation", "Scoped task"}
    assert next(row for row in scopes if row[1] == "Scoped task")[2] == DEFAULT_PROJECT_ID
    assert next(row for row in scopes if row[1] == "Scoped task")[3] == str(metric_child["id"])

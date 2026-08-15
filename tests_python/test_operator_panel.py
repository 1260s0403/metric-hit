from __future__ import annotations

import re
import sqlite3
import subprocess

import pytest
from fastapi.testclient import TestClient

from metrichit_os.config import CURRENT_CONTEXT
from metrichit_os.operator_panel import create_operator_app, run_operator_panel


def temporary_database(tmp_path):
    database = tmp_path / "memory.sqlite"
    subprocess.run(["node", "scripts/init-memory.mjs", str(database)], check=True, capture_output=True, text=True)
    return database


def panel(tmp_path):
    database = temporary_database(tmp_path)
    client = TestClient(create_operator_app(database))
    page = client.get("/")
    token = re.search(r'const token="([^"]+)"', page.text).group(1)
    return client, token, database


def add(client, token, kind, topic, text, tags=""):
    return client.post(
        "/api/entries", headers={"X-Operator-Token": token},
        json={"kind": kind, "topic": topic, "text": text, "tags": tags},
    )


def seed_memory(database, visible_content="Найти это"):
    source_id = "00000000-0000-0000-0000-000000000010"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO sources (id, type, title, content, author) VALUES (?, 'test', 'Источник', 'x', 'owner')",
            (source_id,),
        )
        connection.executemany(
            """INSERT INTO memory_items (id, type, semantic_key, title, content, status, source_id, author, version)
               VALUES (?, 'fact', ?, ?, ?, ?, ?, 'owner', 1)""",
            [
                ("00000000-0000-0000-0000-000000000011", "fact.visible", "Видимый факт", visible_content, "active", source_id),
                ("00000000-0000-0000-0000-000000000012", "fact.hidden", "Скрытый факт", "Не показывать", "archived", source_id),
            ],
        )
        connection.executemany(
            """INSERT INTO decisions (id, type, title, content, status, author, version)
               VALUES (?, 'decision', ?, ?, ?, 'owner', 1)""",
            [
                ("00000000-0000-0000-0000-000000000013", "Видимое решение", "Найти решение", "active"),
                ("00000000-0000-0000-0000-000000000014", "Скрытое решение", "Не показывать", "archived"),
            ],
        )


def test_refuses_external_host(tmp_path):
    with pytest.raises(ValueError, match="127.0.0.1"):
        run_operator_panel(temporary_database(tmp_path), port=8765, host="0.0.0.0")


def test_page_title_stays_metrichit_while_visual_heading_is_yadro(tmp_path):
    client, _, _ = panel(tmp_path)
    page = client.get("/").text

    assert "<title>MetricHit</title>" in page
    assert "<h1>Ядро</h1>" in page


def test_dashboard_is_default_and_keeps_view_separate_from_kind(tmp_path):
    client, token, _ = panel(tmp_path)
    add(client, token, "artem", "Рекомендация", "Текст рекомендации").raise_for_status()

    page = client.get("/")
    dashboard = client.get("/api/dashboard")

    assert 'data-view="overview"' in page.text
    assert re.search(r'data-view="overview"[^>]*class="active"[^>]*aria-current="page"', page.text)
    assert dashboard.status_code == 200
    assert len(dashboard.json()["artem"]["items"]) == 1
    assert dashboard.json()["tasks"]["open"] == 0


def test_memory_context_uses_allowed_path_only(tmp_path):
    client, _, _ = panel(tmp_path)

    result = client.get("/api/memory/context", params={"path": "C:/outside.md"})

    assert result.json()["content"] == CURRENT_CONTEXT.read_text(encoding="utf-8")


def test_memory_shows_only_approved_records_and_searches(tmp_path):
    client, _, database = panel(tmp_path)
    seed_memory(database)

    facts = client.get("/api/memory/facts", params={"query": "Найти"}).json()
    decisions = client.get("/api/memory/decisions", params={"query": "решение"}).json()

    assert [item["semantic_key"] for item in facts] == ["fact.visible"]
    assert [item["title"] for item in decisions] == ["Видимое решение"]


def test_memory_is_read_only_and_escapes_html(tmp_path):
    client, _, database = panel(tmp_path)
    seed_memory(database, "<img src=x onerror=alert(1)>")

    assert "<img src=x onerror=alert(1)>" not in client.get("/").text
    assert "content.textContent=item.content" in client.get("/").text
    assert not any(route.path.startswith("/api/memory") and "POST" in route.methods for route in client.app.routes)


def test_lists_and_searches_by_current_kind(tmp_path):
    client, token, _ = panel(tmp_path)
    add(client, token, "artem", "SEO", "Проверить интент").raise_for_status()
    add(client, token, "idea", "Контент", "Проверить рубрику").raise_for_status()

    assert [item["kind"] for item in client.get("/api/entries", params={"kind": "artem"}).json()] == ["artem_recommendation"]
    assert [item["kind"] for item in client.get("/api/entries", params={"kind": "idea", "query": "рубрику"}).json()] == ["owner_idea"]


def test_summary_separates_kinds_and_respects_search(tmp_path):
    client, token, _ = panel(tmp_path)
    add(client, token, "artem", "SEO", "Найти это", "seo").raise_for_status()
    add(client, token, "artem", "SEO", "Скрыть это").raise_for_status()
    add(client, token, "idea", "Контент", "Идея владельца").raise_for_status()

    artem = client.get("/api/summary", params={"kind": "artem", "query": "Найти"}).json()
    idea = client.get("/api/summary", params={"kind": "idea"}).json()

    assert artem["count"] == 1
    assert "Найти это" in artem["markdown"] and "Скрыть это" not in artem["markdown"]
    assert "Идея владельца" in idea["markdown"] and "Найти это" not in idea["markdown"]


def test_summary_is_compact_and_deterministic(tmp_path):
    client, token, _ = panel(tmp_path)
    text = "Первое полезное предложение. Второе длинное предложение, которое не должно попасть в тезис."
    add(client, token, "artem", "SEO", text).raise_for_status()

    summary = client.get("/api/summary", params={"kind": "artem"}).json()["markdown"]

    assert "## Ключевые тезисы" in summary and "## Основные темы" in summary
    assert "Первое полезное предложение." in summary
    assert "Второе длинное" not in summary
    assert "UUID" not in summary


def test_adds_both_kinds_and_creates_idempotent_task(tmp_path):
    client, token, database = panel(tmp_path)
    recommendation = add(client, token, "artem", "SEO", "Проверить кластер", "seo").json()
    idea = add(client, token, "idea", "Контент", "Добавить FAQ").json()

    first = client.post("/api/tasks", headers={"X-Operator-Token": token}, json={"id": recommendation["id"]})
    second = client.post("/api/tasks", headers={"X-Operator-Token": token}, json={"id": recommendation["id"]})

    assert recommendation["kind"] == "artem_recommendation"
    assert idea["kind"] == "owner_idea"
    assert first.json()["id"] == second.json()["id"]
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1


def task(client, token, kind="artem"):
    entry = add(client, token, kind, "Тема", "Текст").json()
    return client.post("/api/tasks", headers={"X-Operator-Token": token}, json={"id": entry["id"]}).json()


def test_lists_only_related_tasks(tmp_path):
    client, token, database = panel(tmp_path)
    knowledge_task = task(client, token, "idea")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO tasks (id, type, title, content, status, author) VALUES (?, 'other', 'Скрытая', 'x', 'pending', 'owner')",
            ("00000000-0000-0000-0000-000000000002",),
        )

    items = client.get("/api/tasks").json()

    assert [item["id"] for item in items] == [knowledge_task["id"]]
    assert items[0]["source"] == "Моя идея"
    assert items[0]["status"] == "open"


def test_changes_open_task_to_completed_and_is_idempotent(tmp_path):
    client, token, database = panel(tmp_path)
    created = task(client, token)
    url = f"/api/tasks/{created['id']}/status"

    first = client.post(url, headers={"X-Operator-Token": token}, json={"status": "completed"})
    second = client.post(url, headers={"X-Operator-Token": token}, json={"status": "completed"})

    assert first.json()["status"] == second.json()["status"] == "completed"
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM audit_log WHERE entity_id=? AND action='update'", (created["id"],)).fetchone()[0] == 1


def test_changes_open_task_to_cancelled_and_rejects_reverse_transition(tmp_path):
    client, token, _ = panel(tmp_path)
    created = task(client, token)
    url = f"/api/tasks/{created['id']}/status"

    assert client.post(url, headers={"X-Operator-Token": token}, json={"status": "cancelled"}).json()["status"] == "cancelled"
    rejected = client.post(url, headers={"X-Operator-Token": token}, json={"status": "completed"})

    assert rejected.status_code == 400
    assert rejected.json()["error"] == "operator_panel_error"


def test_action_plan_groups_task_statuses_and_entries_without_task(tmp_path):
    client, token, _ = panel(tmp_path)
    open_entry = add(client, token, "artem", "Open", "Текст").json()
    complete_entry = add(client, token, "artem", "Done", "Текст").json()
    cancelled_entry = add(client, token, "artem", "Cancelled", "Текст").json()
    missing = add(client, token, "artem", "Missing", "Текст").json()
    open_task = client.post("/api/tasks", headers={"X-Operator-Token": token}, json={"id": open_entry["id"]}).json()
    complete_task = client.post("/api/tasks", headers={"X-Operator-Token": token}, json={"id": complete_entry["id"]}).json()
    cancelled_task = client.post("/api/tasks", headers={"X-Operator-Token": token}, json={"id": cancelled_entry["id"]}).json()
    for task_id, status in ((complete_task["id"], "completed"), (cancelled_task["id"], "cancelled")):
        client.post(f"/api/tasks/{task_id}/status", headers={"X-Operator-Token": token}, json={"status": status}).raise_for_status()

    plan = client.get("/api/action-plan", params={"kind": "artem"}).json()

    assert [item["id"] for item in plan["open"]] == [open_task["id"]]
    assert [item["id"] for item in plan["completed"]] == [complete_task["id"]]
    assert [item["id"] for item in plan["cancelled"]] == [cancelled_task["id"]]
    assert [item["id"] for item in plan["without_task"]] == [missing["id"]]
    assert "## Сделать сейчас" in plan["markdown"]
    assert "## Уже в работе" in plan["markdown"]
    assert "## Можно превратить в задачи" in plan["markdown"]
    assert open_task["id"] not in plan["markdown"] and missing["id"] not in plan["markdown"]


def test_task_confirmation_and_details_are_local(tmp_path):
    client, token, _ = panel(tmp_path)
    entry = add(client, token, "artem", "Тема", "Полное описание исходной рекомендации").json()

    first = client.post("/api/tasks", headers={"X-Operator-Token": token}, json={"id": entry["id"]}).json()
    second = client.post("/api/tasks", headers={"X-Operator-Token": token}, json={"id": entry["id"]}).json()
    task_item = client.get("/api/tasks").json()[0]
    page = client.get("/").text

    assert first["created"] is True and second["created"] is False and first["id"] == second["id"]
    assert task_item["description"] == "Полное описание исходной рекомендации"
    assert "taskFeedback" in page and "Открыть задачу" in page and "Подробнее" in page


def test_existing_task_is_returned_with_exact_anchor_and_target_style(tmp_path):
    client, token, _ = panel(tmp_path)
    entry = add(client, token, "artem", "Панель", "Добавить несколько регионов в один проект.").json()
    created = client.post("/api/tasks", headers={"X-Operator-Token": token}, json={"id": entry["id"]}).json()

    listed = client.get("/api/entries", params={"kind": "artem"}).json()[0]
    page = client.get("/").text

    assert listed["task"]["id"] == created["id"]
    assert f"#task-${{result.id}}" in page
    assert ".entry:target" in page


def test_task_card_uses_short_description_and_keeps_full_text_in_details(tmp_path):
    client, token, _ = panel(tmp_path)
    text = "Первое действие " + "очень длинное " * 30
    entry = add(client, token, "artem", "Панель", text).json()
    created = client.post("/api/tasks", headers={"X-Operator-Token": token}, json={"id": entry["id"], "title": "Панель"}).json()
    item = client.get("/api/tasks").json()[0]
    page = client.get("/").text

    assert item["display_title"].startswith("Панель — ")
    assert item["description"] == text
    assert "slice(0,160)" not in page and "details.className='hidden'" in page
    assert created["id"] not in page.split("function renderTasks")[1].split("details.append")[0]


def test_focus_task_and_modal_markup_are_present(tmp_path):
    client, token, _ = panel(tmp_path)
    entry = add(client, token, "artem", "Тема", "Текст").json()
    task = client.post("/api/tasks", headers={"X-Operator-Token": token}, json={"id": entry["id"]}).json()

    page = client.get("/", params={"view": "tasks", "focus_task": task["id"]}).text

    assert f'const focusTask="{task["id"]}"' in page
    assert "focus_task=${encodeURIComponent(result.id)}#task-${result.id}" in page
    assert "task-focused" in page and "focus-label" in page
    assert 'role="dialog"' in page and 'id="modal-close"' in page
    assert "document.body.style.overflow='hidden'" in page and "Escape" in page


def test_summary_and_plan_requests_work_for_both_sections(tmp_path):
    client, token, _ = panel(tmp_path)
    add(client, token, "artem", "SEO", "Тезис рекомендации").raise_for_status()
    add(client, token, "idea", "Контент", "Тезис идеи").raise_for_status()

    for kind, phrase in (("artem", "Тезис рекомендации"), ("idea", "Тезис идеи")):
        summary = client.get("/api/summary", params={"kind": kind}).json()
        plan = client.get("/api/action-plan", params={"kind": kind}).json()
        assert "kind must be" not in str(summary) + str(plan)
        assert phrase in summary["markdown"]
        assert "# План действий" in plan["markdown"]


def test_rejects_post_without_token_and_escapes_user_html(tmp_path):
    client, token, _ = panel(tmp_path)
    assert client.post("/api/entries", json={"kind": "idea", "topic": "Тема", "text": "Текст"}).status_code == 403
    text = "<img src=x onerror=alert(1)>"
    add(client, token, "idea", "Тема", text).raise_for_status()
    page = client.get("/").text
    assert text not in page
    assert "textContent=item.text" in page
    assert "color-scheme:dark" in page
    created = task(client, token)
    assert client.post(f"/api/tasks/{created['id']}/status", json={"status": "completed"}).status_code == 403


def test_tasks_focus_view_is_server_selected_and_task_actions_are_compact(tmp_path):
    client, token, _ = panel(tmp_path)
    entry = add(client, token, "idea", "Тема", "Полный исходный текст").json()
    task = client.post("/api/tasks", headers={"X-Operator-Token": token}, json={"id": entry["id"]}).json()

    page = client.get(f"/?view=tasks&focus_task={task['id']}#task-{task['id']}").text
    script = page.split("function renderTasks")[1]

    assert 'data-view="tasks" data-testid="tab-tasks" class="active" aria-current="page"' in page
    assert '<div id="knowledge" data-testid="knowledge-screen" class="hidden">' in page
    assert f'const focusTask="{task["id"]}"' in page
    assert "task-focused" in script and "focusCard" in page
    assert "box.append(title,meta,actions,details)" in script
    assert "details.append(full,origin,date,uuid)" in script
    assert "slice(0,160)" not in script

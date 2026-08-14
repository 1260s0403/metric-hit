from __future__ import annotations

import re
import sqlite3
import subprocess

import pytest
from fastapi.testclient import TestClient

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


def test_refuses_external_host(tmp_path):
    with pytest.raises(ValueError, match="127.0.0.1"):
        run_operator_panel(temporary_database(tmp_path), port=8765, host="0.0.0.0")


def test_lists_and_searches_by_current_kind(tmp_path):
    client, token, _ = panel(tmp_path)
    add(client, token, "artem", "SEO", "Проверить интент").raise_for_status()
    add(client, token, "idea", "Контент", "Проверить рубрику").raise_for_status()

    assert [item["kind"] for item in client.get("/api/entries", params={"kind": "artem"}).json()] == ["artem_recommendation"]
    assert [item["kind"] for item in client.get("/api/entries", params={"kind": "idea", "query": "рубрику"}).json()] == ["owner_idea"]


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
        assert connection.execute("SELECT count(*) FROM audit_log WHERE entity_id=?", (created["id"],)).fetchone()[0] == 1


def test_changes_open_task_to_cancelled_and_rejects_reverse_transition(tmp_path):
    client, token, _ = panel(tmp_path)
    created = task(client, token)
    url = f"/api/tasks/{created['id']}/status"

    assert client.post(url, headers={"X-Operator-Token": token}, json={"status": "cancelled"}).json()["status"] == "cancelled"
    rejected = client.post(url, headers={"X-Operator-Token": token}, json={"status": "completed"})

    assert rejected.status_code == 400
    assert rejected.json()["error"] == "operator_panel_error"


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

from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path
from uuid import uuid4

from metrichit_os.activity import list_activity
from metrichit_os.knowledge_store import KnowledgeStore


def database(tmp_path: Path) -> Path:
    path = tmp_path / "activity.sqlite"
    subprocess.run(["node", "scripts/init-memory.mjs", str(path)], check=True, capture_output=True, text=True)
    return path


def test_activity_filters_changes_and_missing_target(tmp_path: Path) -> None:
    db = database(tmp_path); store = KnowledgeStore(db)
    idea = store.add(kind="idea", topic="Idea", text="Text")
    task = store.to_task(entry_id=str(idea["id"])); store.edit_task(task_id=str(task["id"]), title="Edited", description="New", priority="high", due_date="2026-08-20")
    store.set_task_status(task_id=str(task["id"]), status="completed")
    with sqlite3.connect(db) as connection:
        connection.execute("DELETE FROM tasks WHERE id=?", (str(task["id"]),))
    result = list_activity(db)
    assert [item["action"] for item in result["items"][:2]] == ["completed", "update"]
    assert any(item["object_type"] == "idea" for item in result["items"])
    assert any(not item["available"] for item in result["items"])
    edited = next(item for item in result["items"] if item["action"] == "update")
    assert {change["field"] for change in edited["changes"]} == {"Название", "Описание", "Приоритет", "Срок"}
    assert list_activity(db, item_type="task", action="completed")["items"][0]["action"] == "completed"


def test_activity_limit_legacy_json_and_period(tmp_path: Path) -> None:
    db = database(tmp_path)
    with sqlite3.connect(db) as connection:
        for number in range(51):
            connection.execute("INSERT INTO audit_log (id,type,title,content,data_json,author,entity_type,entity_id,action) VALUES (?,?,?,?,?,?,'unknown',?,'create')", (str(uuid4()), "legacy", f"<img {number}>", "legacy", None, "owner", str(uuid4())))
    page = list_activity(db)
    assert len(page["items"]) == 50 and page["has_more"]
    assert page["items"][0]["changes"] == []
    assert list_activity(db, period="today")["items"]
    assert list_activity(db, item_type="memory")["items"] == []

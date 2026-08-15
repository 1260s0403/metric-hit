from __future__ import annotations

import json
import sqlite3
import subprocess
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import date, timedelta
from pathlib import Path

import pytest

from metrichit_os.knowledge_store import KnowledgeError, KnowledgeStore


def temporary_database(tmp_path: Path) -> Path:
    database = tmp_path / "tasks.sqlite"
    subprocess.run(["node", "scripts/init-memory.mjs", str(database)], check=True, capture_output=True, text=True)
    return database


def create_task(store: KnowledgeStore, *, topic: str, text: str) -> dict[str, object]:
    entry = store.add(kind="artem", topic=topic, text=text)
    return store.to_task(entry_id=str(entry["id"]))


def test_existing_and_new_tasks_have_safe_priority_and_due_date_defaults(tmp_path: Path) -> None:
    store = KnowledgeStore(temporary_database(tmp_path))
    created = create_task(store, topic="Новая", text="Новая задача")

    with sqlite3.connect(store.path) as connection:
        connection.execute(
            """
            INSERT INTO tasks (id, type, title, content, data_json, status, author)
            VALUES (?, 'knowledge_task', 'Старая', 'Текст', ?, 'pending', 'owner')
            """,
            (
                "00000000-0000-0000-0000-000000000777",
                json.dumps({
                    "knowledge_entry_id": created["knowledge_entry_id"],
                    "knowledge_kind": "artem_recommendation",
                    "knowledge_tags": [],
                    "knowledge_topic": "Старая",
                }),
            ),
        )

    tasks = {item["id"]: item for item in store.list_tasks()}
    assert tasks[created["id"]]["priority"] == "normal"
    assert tasks[created["id"]]["due_date"] is None
    assert tasks["00000000-0000-0000-0000-000000000777"]["priority"] == "normal"
    assert tasks["00000000-0000-0000-0000-000000000777"]["due_date"] is None


@pytest.mark.parametrize(
    ("priority", "due_date", "message"),
    [
        ("urgent", None, "priority"),
        ("high", "2026-99-99", "due_date"),
        ("high", "14-08-2026", "due_date"),
    ],
)
def test_edit_task_validates_priority_and_due_date(
    tmp_path: Path, priority: str, due_date: str | None, message: str
) -> None:
    store = KnowledgeStore(temporary_database(tmp_path))
    task = create_task(store, topic="Проверка", text="Исходный текст")

    with pytest.raises(KnowledgeError, match=message):
        store.edit_task(
            task_id=str(task["id"]), title="Новое название", description="Новое описание",
            priority=priority, due_date=due_date,
        )


def test_edit_task_preserves_source_and_writes_before_after_audit(tmp_path: Path) -> None:
    store = KnowledgeStore(temporary_database(tmp_path))
    task = create_task(store, topic="Источник", text="Исходная рекомендация")
    before = dict(task)

    changed = store.edit_task(
        task_id=str(task["id"]), title="Изменённая задача", description="Изменённое описание",
        priority="high", due_date="2026-08-16",
    )

    assert changed["title"] == "Изменённая задача"
    assert changed["description"] == "Изменённое описание"
    assert changed["priority"] == "high"
    assert changed["due_date"] == "2026-08-16"
    assert changed["knowledge_entry_id"] == before["knowledge_entry_id"]
    assert changed["knowledge_kind"] == before["knowledge_kind"]
    assert changed["created_at"] == before["created_at"]
    with sqlite3.connect(store.path) as connection:
        audit = connection.execute(
            "SELECT data_json FROM audit_log WHERE entity_id=? ORDER BY created_at DESC LIMIT 1", (task["id"],)
        ).fetchone()
    assert audit is not None
    payload = json.loads(audit[0])
    assert payload["old"]["title"] == before["title"]
    assert payload["new"]["title"] == "Изменённая задача"
    assert payload["old"]["priority"] == "normal"
    assert payload["new"]["priority"] == "high"


def test_edit_task_rejects_empty_title_and_does_not_change_task(tmp_path: Path) -> None:
    store = KnowledgeStore(temporary_database(tmp_path))
    task = create_task(store, topic="Тема", text="Текст")

    with pytest.raises(KnowledgeError, match="title"):
        store.edit_task(
            task_id=str(task["id"]), title="  ", description="Новое", priority="low", due_date=None
        )
    assert next(item for item in store.list_tasks() if item["id"] == task["id"])["title"] == task["title"]


def test_task_filters_combine_and_recommended_order_is_deterministic(tmp_path: Path) -> None:
    store = KnowledgeStore(temporary_database(tmp_path))
    overdue = create_task(store, topic="Просрочено", text="Просрочено")
    today = create_task(store, topic="Сегодня", text="Сегодня")
    high = create_task(store, topic="Высокий", text="Высокий")
    normal = create_task(store, topic="Обычный", text="Обычный")
    low = create_task(store, topic="Низкий", text="Низкий")
    completed = create_task(store, topic="Готово", text="Готово")
    current = date.today()
    edits = (
        (overdue, "high", (current - timedelta(days=1)).isoformat()),
        (today, "normal", current.isoformat()),
        (high, "high", None),
        (normal, "normal", None),
        (low, "low", None),
        (completed, "high", None),
    )
    for item, priority, due_date in edits:
        store.edit_task(task_id=str(item["id"]), title=str(item["title"]), description=str(item["description"]), priority=priority, due_date=due_date)
    store.set_task_status(task_id=str(completed["id"]), status="completed")

    listed = store.list_tasks()
    assert [item["id"] for item in listed[:5]] == [
        overdue["id"], today["id"], high["id"], normal["id"], low["id"],
    ]
    assert [item["id"] for item in store.list_tasks(query="Сегодня", status="open", priority="normal", due="today")] == [today["id"]]
    assert [item["id"] for item in store.list_tasks(status="completed")] == [completed["id"]]
    assert [item["id"] for item in store.list_tasks(due="overdue")] == [overdue["id"]]
    assert {item["id"] for item in store.list_tasks(due="none")} == {high["id"], normal["id"], low["id"], completed["id"]}


def test_today_tasks_include_overdue_today_and_at_most_five_high_without_due_date(tmp_path: Path) -> None:
    store = KnowledgeStore(temporary_database(tmp_path))
    current = date.today()
    overdue = create_task(store, topic="Просрочено", text="Просрочено")
    today = create_task(store, topic="Сегодня", text="Сегодня")
    store.edit_task(task_id=str(overdue["id"]), title="Просрочено", description="Просрочено", priority="normal", due_date=(current - timedelta(days=1)).isoformat())
    store.edit_task(task_id=str(today["id"]), title="Сегодня", description="Сегодня", priority="normal", due_date=current.isoformat())
    high_ids = []
    for number in range(6):
        item = create_task(store, topic=f"Высокая {number}", text=f"Высокая {number}")
        store.edit_task(task_id=str(item["id"]), title=str(item["title"]), description=str(item["description"]), priority="high", due_date=None)
        high_ids.append(item["id"])
    closed = create_task(store, topic="Закрытая", text="Закрытая")
    store.edit_task(task_id=str(closed["id"]), title="Закрытая", description="Закрытая", priority="high", due_date=None)
    store.set_task_status(task_id=str(closed["id"]), status="completed")

    today_items = store.today_tasks()
    ids = [item["id"] for item in today_items]
    assert overdue["id"] in ids and today["id"] in ids
    assert len([item for item in today_items if item["id"] in high_ids]) == 5
    assert closed["id"] not in ids


def test_concurrent_knowledge_to_task_creates_one_task(tmp_path: Path) -> None:
    store = KnowledgeStore(temporary_database(tmp_path))
    entry = store.add(kind="idea", topic="Concurrent", text="One task only")
    barrier = Barrier(2)

    def create() -> tuple[dict[str, object], bool]:
        barrier.wait()
        return store.to_task_with_created(entry_id=str(entry["id"]))

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = list(executor.map(lambda _: create(), range(2)))

    assert first[0]["id"] == second[0]["id"]
    assert sorted((first[1], second[1])) == [False, True]
    with sqlite3.connect(store.path) as connection:
        count = connection.execute(
            "SELECT count(*) FROM tasks WHERE json_extract(data_json, '$.knowledge_entry_id')=?", (entry["id"],)
        ).fetchone()[0]
    assert count == 1


def test_blank_due_date_is_normalized_to_none_for_filters_and_today(tmp_path: Path) -> None:
    store = KnowledgeStore(temporary_database(tmp_path))
    task = create_task(store, topic="Blank due", text="Should be due-less")
    changed = store.edit_task(
        task_id=str(task["id"]), title=str(task["title"]), description=str(task["description"]),
        priority="high", due_date="",
    )

    assert changed["due_date"] is None
    assert [item["id"] for item in store.list_tasks(due="none")] == [task["id"]]
    assert [item["id"] for item in store.today_tasks()] == [task["id"]]

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys

import pytest

from metrichit_os.config import MEMORY_DATABASE
from metrichit_os.handoff import HandoffError, HandoffStore, format_handoff
from metrichit_os.knowledge_store import KnowledgeStore


def temporary_database(tmp_path):
    database = tmp_path / "memory.sqlite"
    subprocess.run(["node", "scripts/init-memory.mjs", str(database)], check=True, capture_output=True, text=True)
    return database


def payload(**changes):
    value = {
        "idempotency_key": "handoff-unified-inbox-v1",
        "semantic_key": "architecture.unified_inbox_mvp",
        "goal": "Реализовать единый входящий поток",
        "scope": ["Текст", "Ссылки", "Файлы"],
        "constraints": ["Без UI", "Без фонового процесса"],
        "acceptance": ["Focused tests проходят", "Git остаётся чистым после коммита"],
        "source": "owner decision 2026-08-15",
        "project_id": None,
        "approved_by": "owner",
    }
    value.update(changes)
    return value


def test_approved_decision_creates_linked_existing_task_and_is_idempotent(tmp_path):
    database = temporary_database(tmp_path)
    store = HandoffStore(database)
    first = store.create_approved(payload())
    second = store.create_approved(payload())
    assert second == first == store.next()
    assert first["handoff_id"] == first["task_id"]
    assert first["status"] == "ready"
    assert first["decision"]["semantic_key"] == "architecture.unified_inbox_mvp"
    assert first["goal"] == "Реализовать единый входящий поток"

    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        candidate = connection.execute("SELECT * FROM memory_candidates WHERE id=?", (first["decision"]["candidate_id"],)).fetchone()
        task = connection.execute("SELECT * FROM tasks WHERE id=?", (first["task_id"],)).fetchone()
        assert candidate["status"] == "approved"
        assert task["type"] == "standalone_task"
        assert task["source_id"] == first["decision"]["source_id"]
        assert json.loads(task["data_json"])["handoff"]["decision_candidate_id"] == candidate["id"]
        assert json.loads(task["data_json"])["handoff"]["lifecycle"] == {"status": "ready"}
        assert connection.execute("SELECT count(*) FROM memory_candidates WHERE semantic_key=?", (candidate["semantic_key"],)).fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM tasks WHERE id=?", (task["id"],)).fetchone()[0] == 1


def test_idempotency_conflict_semantic_duplicate_and_explicit_evolution(tmp_path):
    database = temporary_database(tmp_path)
    store = HandoffStore(database)
    first = store.create_approved(payload())
    with pytest.raises(HandoffError, match="idempotency key"):
        store.create_approved(payload(goal="Другая цель"))
    with pytest.raises(HandoffError, match="semantic evolution"):
        store.create_approved(payload(idempotency_key="second"))
    evolved = store.create_approved(payload(
        idempotency_key="second",
        goal="Реализовать единый входящий поток v2",
        supersedes_candidate_id=first["decision"]["candidate_id"],
    ))
    assert evolved["decision"]["candidate_id"] != first["decision"]["candidate_id"]
    assert store.next()["task_id"] == evolved["task_id"]
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT status FROM tasks WHERE id=?", (first["task_id"],)).fetchone()[0] == "cancelled"

    duplicate = payload(
        idempotency_key="duplicate",
        semantic_key="architecture.different_key",
        supersedes_candidate_id=None,
        goal="Реализовать единый входящий поток v2",
    )
    with pytest.raises(HandoffError, match="semantic duplicate"):
        store.create_approved(duplicate)


def test_next_returns_only_active_handoffs_and_does_not_break_user_tasks(tmp_path):
    database = temporary_database(tmp_path)
    knowledge = KnowledgeStore(database)
    entry = knowledge.add(kind="idea", topic="Пользовательская задача", text="Не handoff")
    user_task = knowledge.to_task(entry_id=str(entry["id"]))
    handoff = HandoffStore(database).create_approved(payload())
    assert HandoffStore(database).next()["task_id"] == handoff["task_id"]
    assert {item["id"] for item in knowledge.list_tasks()} == {user_task["id"], handoff["task_id"]}
    claimed = HandoffStore(database).claim(handoff["handoff_id"], "developer-a")
    assert claimed["status"] == "in_progress"
    completed = HandoffStore(database).complete(handoff["handoff_id"], "a" * 40, "developer-a")
    assert completed["status"] == "completed"
    assert HandoffStore(database).next() is None
    assert knowledge.list_tasks(status="open")[0]["id"] == user_task["id"]


def test_project_link_must_be_active(tmp_path):
    database = temporary_database(tmp_path)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO documents (id,type,title,content,data_json,status,author,access_level) VALUES ('30000000-0000-4000-a000-000000000000','project','Active','Active','{}','active','owner','internal')"
        )
        connection.execute(
            "INSERT INTO documents (id,type,title,content,data_json,status,author,access_level) VALUES ('30000000-0000-4000-a000-000000000001','project','Archive','Archive','{}','archived','owner','internal')"
        )
    linked = HandoffStore(database).create_approved(payload(project_id="30000000-0000-4000-a000-000000000000"))
    assert linked["project_id"] == "30000000-0000-4000-a000-000000000000"
    with sqlite3.connect(database) as connection:
        task_data = json.loads(connection.execute("SELECT data_json FROM tasks WHERE id=?", (linked["task_id"],)).fetchone()[0])
        assert task_data["project_id"] == linked["project_id"]
    with pytest.raises(HandoffError, match="active"):
        HandoffStore(database).create_approved(payload(idempotency_key="archived-project", semantic_key="architecture.archived-project", project_id="30000000-0000-4000-a000-000000000001"))


def test_pending_duplicate_and_memory_conflict_block_atomic_handoff(tmp_path):
    database = temporary_database(tmp_path)
    with sqlite3.connect(database) as connection:
        source_id = "40000000-0000-4000-a000-000000000001"
        connection.execute(
            "INSERT INTO sources (id,type,title,content,status,author,access_level) VALUES (?, 'owner_decision', 'Pending', 'Pending', 'active', 'owner', 'internal')",
            (source_id,),
        )
        connection.execute(
            "INSERT INTO memory_candidates (id,type,semantic_key,title,content,status,source_id,author,access_level) VALUES ('40000000-0000-4000-a000-000000000002','decision','architecture.unified_inbox_mvp','Pending','Pending','pending',?,'owner','internal')",
            (source_id,),
        )
    with pytest.raises(HandoffError, match="pending semantic duplicate"):
        HandoffStore(database).create_approved(payload())

    conflicted_directory = tmp_path / "conflicted"
    conflicted_directory.mkdir()
    conflicted = temporary_database(conflicted_directory)
    with sqlite3.connect(conflicted) as connection:
        source_id = "50000000-0000-4000-a000-000000000001"
        item_id = "50000000-0000-4000-a000-000000000002"
        connection.execute(
            "INSERT INTO sources (id,type,title,content,status,author,access_level) VALUES (?, 'owner_decision', 'Existing', 'Existing', 'active', 'owner', 'internal')",
            (source_id,),
        )
        connection.execute(
            "INSERT INTO memory_items (id,type,semantic_key,title,content,data_json,status,source_id,author,access_level) VALUES (?, 'decision','architecture.unified_inbox_mvp','Existing','Different','{}','active',?,'owner','internal')",
            (item_id, source_id),
        )
    with pytest.raises(HandoffError, match="produced a memory conflict"):
        HandoffStore(conflicted).create_approved(payload())
    with sqlite3.connect(conflicted) as connection:
        assert connection.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM memory_candidates").fetchone()[0] == 0


def test_cli_create_and_next_return_stable_json_and_text(tmp_path):
    database = temporary_database(tmp_path)
    created = subprocess.run(
        [sys.executable, "-m", "metrichit_os", "handoff-create", "--db", str(database), "--stdin"],
        input=json.dumps(payload(), ensure_ascii=False), capture_output=True, text=True, encoding="utf-8", check=True,
    )
    first = json.loads(created.stdout)
    machine = subprocess.run(
        [sys.executable, "-m", "metrichit_os", "handoff-next", "--db", str(database)],
        capture_output=True, text=True, encoding="utf-8", check=True,
    )
    assert json.loads(machine.stdout)["handoff"] == first
    text = subprocess.run(
        [sys.executable, "-m", "metrichit_os", "handoff-next", "--db", str(database), "--format", "text"],
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout
    assert text == format_handoff(first)
    assert "# Codex engineering handoff" in text
    assert "Decision: architecture.unified_inbox_mvp" in text
    claimed = subprocess.run(
        [sys.executable, "-m", "metrichit_os", "handoff-claim", "--db", str(database), "--id", first["handoff_id"], "--developer", "developer-a"],
        capture_output=True, text=True, encoding="utf-8", check=True,
    )
    assert json.loads(claimed.stdout)["status"] == "in_progress"
    completed = subprocess.run(
        [sys.executable, "-m", "metrichit_os", "handoff-complete", "--db", str(database), "--id", first["handoff_id"], "--commit", "b" * 40, "--developer", "developer-a"],
        capture_output=True, text=True, encoding="utf-8", check=True,
    )
    assert json.loads(completed.stdout)["lifecycle"]["commit_hash"] == "b" * 40


def test_lifecycle_is_idempotent_and_allows_only_one_active_developer_handoff(tmp_path):
    database = temporary_database(tmp_path)
    store = HandoffStore(database)
    first = store.create_approved(payload())
    second = store.create_approved(payload(
        idempotency_key="handoff-second-v1",
        semantic_key="architecture.second_handoff_mvp",
        goal="Р РµР°Р»РёР·РѕРІР°С‚СЊ РІС‚РѕСЂРѕР№ РїРѕС‚РѕРє",
    ))
    claimed = store.claim(first["handoff_id"], "developer-a")
    assert store.claim(first["handoff_id"], "developer-a") == claimed
    with pytest.raises(HandoffError, match="another developer"):
        store.claim(first["handoff_id"], "developer-b")
    with pytest.raises(HandoffError, match="already in progress"):
        store.claim(second["handoff_id"], "developer-b")
    with pytest.raises(HandoffError, match="claimed before completion"):
        store.complete(second["handoff_id"], "c" * 40, "developer-b")
    completed = store.complete(first["handoff_id"], "c" * 40, "developer-a")
    assert store.complete(first["handoff_id"], "c" * 40, "developer-a") == completed
    with pytest.raises(HandoffError, match="different commit hash"):
        store.complete(first["handoff_id"], "d" * 40, "developer-a")
    assert store.next()["handoff_id"] == second["handoff_id"]


def test_focused_workflow_never_writes_working_database(tmp_path):
    before = hashlib.sha256(MEMORY_DATABASE.read_bytes()).hexdigest()
    database = temporary_database(tmp_path)
    HandoffStore(database).create_approved(payload())
    assert hashlib.sha256(MEMORY_DATABASE.read_bytes()).hexdigest() == before


def test_next_skips_malformed_legacy_handoff_metadata(tmp_path):
    database = temporary_database(tmp_path)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO tasks (id,type,title,content,data_json,status,author,access_level) VALUES ('60000000-0000-4000-a000-000000000001','standalone_task','Legacy','Legacy','{\"priority\":\"high\",\"handoff\":{\"kind\":\"codex_engineering\"}}','pending','owner','internal')"
        )
    assert HandoffStore(database).next() is None


def test_next_skips_broken_decision_linkage(tmp_path):
    database = temporary_database(tmp_path)
    valid = HandoffStore(database).create_approved(payload())
    with sqlite3.connect(database) as connection:
        broken = {
            "priority": "high",
            "handoff": {
                "kind": "codex_engineering",
                "goal": "Broken",
                "scope": ["Broken"],
                "constraints": ["Broken"],
                "acceptance": ["Broken"],
                "source": "Broken",
                "source_id": valid["decision"]["source_id"],
                "decision_candidate_id": valid["decision"]["candidate_id"],
                "decision_semantic_key": valid["decision"]["semantic_key"],
                "project_id": None,
            },
        }
        connection.execute(
            "INSERT INTO tasks (id,type,title,content,data_json,status,source_id,author,access_level) VALUES ('60000000-0000-4000-a000-000000000002','standalone_task','Broken','Broken',?,'pending',?,'owner','internal')",
            (json.dumps(broken), valid["decision"]["source_id"]),
        )
    assert HandoffStore(database).next()["task_id"] == valid["task_id"]


def test_next_skips_legacy_handoff_with_invalid_json_types(tmp_path):
    database = temporary_database(tmp_path)
    valid = HandoffStore(database).create_approved(payload())
    malformed = {
        "priority": [],
        "project_id": [],
        "handoff": {
            "kind": "codex_engineering",
            "goal": "Malformed",
            "scope": ["Malformed"],
            "constraints": ["Malformed"],
            "acceptance": ["Malformed"],
            "source": "Malformed",
            "source_id": valid["decision"]["source_id"],
            "decision_candidate_id": valid["decision"]["candidate_id"],
            "decision_semantic_key": valid["decision"]["semantic_key"],
            "project_id": [],
        },
    }
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO tasks (id,type,title,content,data_json,status,source_id,author,access_level) VALUES ('60000000-0000-4000-a000-000000000003','standalone_task','Malformed','Malformed',?,'pending',?,'owner','internal')",
            (json.dumps(malformed), valid["decision"]["source_id"]),
        )
    assert HandoffStore(database).next()["task_id"] == valid["task_id"]

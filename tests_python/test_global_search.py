from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path
from uuid import uuid4

from metrichit_os.global_search import MAX_RESULTS, normalize, search
from metrichit_os.knowledge_store import KnowledgeStore


def database(tmp_path: Path) -> Path:
    path = tmp_path / "search.sqlite"
    subprocess.run(["node", "scripts/init-memory.mjs", str(path)], check=True, capture_output=True, text=True)
    return path


def source(connection: sqlite3.Connection) -> str:
    value = str(uuid4())
    connection.execute("INSERT INTO sources (id,type,title,content,author) VALUES (?,?,?,?,?)", (value, "test", "Source", "x", "owner"))
    return value


def test_normalize_searches_russian_casefold_and_yo(tmp_path: Path) -> None:
    db = database(tmp_path)
    store = KnowledgeStore(db)
    entry = store.add(kind="artem", topic="Ёлка", text="ПРОВЕРИТЬ РЕГИОН")

    results = search(db, query="елка")

    assert normalize(" ЁЛКА ") == "елка"
    assert [(item["type"], item["id"]) for item in results] == [("artem", entry["id"])]


def test_searches_title_text_and_tags_and_applies_filters(tmp_path: Path) -> None:
    db = database(tmp_path)
    store = KnowledgeStore(db)
    title = store.add(kind="artem", topic="Маркер", text="другое", tags="seo")
    text = store.add(kind="idea", topic="другое", text="маркер в тексте")
    tags = store.add(kind="idea", topic="другое", text="другое", tags="маркер")

    results = search(db, query="маркер")

    assert {item["id"] for item in results} == {title["id"], text["id"], tags["id"]}
    assert {item["id"] for item in search(db, query="маркер", item_type="idea")} == {text["id"], tags["id"]}


def test_ranking_snippets_deduplication_and_limit(tmp_path: Path) -> None:
    db = database(tmp_path)
    store = KnowledgeStore(db)
    exact = store.add(kind="artem", topic="точный", text="текст")
    contains = store.add(kind="idea", topic="до точный после", text="текст")
    body = store.add(kind="idea", topic="другое", text="начало " + ("x" * 120) + " точный рядом")
    ranked_before = search(db, query="точный")
    with sqlite3.connect(db) as connection:
        source_id = source(connection)
        for number in range(55):
            connection.execute(
                "INSERT INTO documents (id,type,title,content,data_json,status,author) VALUES (?,?,?,?,?,'active','owner')",
                (str(uuid4()), "memory_document", f"точный документ {number}", "body", "{}"),
            )
        connection.execute(
            "INSERT INTO documents (id,type,title,content,data_json,status,author) VALUES (?,?,?,?,?,'archived','owner')",
            (str(uuid4()), "memory_document", "точный архив", "x", "{}"),
        )

    results = search(db, query="точный")

    assert [item["id"] for item in ranked_before[:3]] == [exact["id"], contains["id"], body["id"]]
    assert "точный рядом" in next(item["snippet"] for item in ranked_before if item["id"] == body["id"])
    assert len(results) == MAX_RESULTS
    assert len({(item["type"], item["id"]) for item in results}) == len(results)
    assert all(item["title"] != "точный архив" for item in results)


def test_search_covers_tasks_facts_decisions_and_documents(tmp_path: Path) -> None:
    db = database(tmp_path)
    store = KnowledgeStore(db)
    entry = store.add(kind="artem", topic="Task", text="needle")
    store.to_task(entry_id=str(entry["id"]))
    with sqlite3.connect(db) as connection:
        source_id = source(connection)
        connection.execute("INSERT INTO memory_items (id,type,semantic_key,title,content,source_id,author) VALUES (?,?,?,?,?,?,?)", (str(uuid4()), "fact", "needle.fact", "Fact", "needle", source_id, "owner"))
        connection.execute("INSERT INTO decisions (id,type,title,content,source_id,author) VALUES (?,?,?,?,?,?)", (str(uuid4()), "decision", "Decision", "needle", source_id, "owner"))
        connection.execute("INSERT INTO documents (id,type,title,content,data_json,status,author) VALUES (?,?,?,?,?,'active','owner')", (str(uuid4()), "memory_document", "Document", "needle", "{}"))

    kinds = {item["type"] for item in search(db, query="needle")}

    assert {"artem", "task", "fact", "decision", "document"} <= kinds
    assert {item["type"] for item in search(db, query="needle", status="open")} == {"task"}
    assert {item["type"] for item in search(db, query="needle", status="active")} == {
        "artem", "fact", "decision", "document"
    }
    assert search(db, query="") == []


def test_invalid_knowledge_metadata_does_not_break_other_search_results(tmp_path: Path) -> None:
    db = database(tmp_path)
    with sqlite3.connect(db) as connection:
        connection.execute(
            "INSERT INTO documents (id,type,title,content,data_json,status,author) VALUES (?,?,?,?,?,'active','owner')",
            (str(uuid4()), "knowledge_entry", "legacy", "needle", None),
        )
        connection.execute(
            "INSERT INTO documents (id,type,title,content,data_json,status,author) VALUES (?,?,?,?,?,'active','owner')",
            (str(uuid4()), "memory_document", "document", "needle", "{}"),
        )

    assert [item["type"] for item in search(db, query="needle")] == ["document"]

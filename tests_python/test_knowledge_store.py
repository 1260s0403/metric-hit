from __future__ import annotations

import hashlib
import json
import subprocess
import sys

import pytest

from metrichit_os import cli
from metrichit_os.config import MEMORY_DATABASE
from metrichit_os.knowledge_store import KnowledgeStore


def temporary_database(tmp_path):
    database = tmp_path / "memory.sqlite"
    subprocess.run(["node", "scripts/init-memory.mjs", str(database)], check=True, capture_output=True, text=True)
    return database


def command(*arguments: str):
    return subprocess.run(
        [sys.executable, "-m", "metrichit_os", *arguments],
        check=True, capture_output=True, text=True, encoding="utf-8",
    )


def test_adds_both_kinds_and_keeps_existing_entries(tmp_path):
    database = temporary_database(tmp_path)
    store = KnowledgeStore(database)
    first = store.add(kind="artem", text="Проверить интент", topic="SEO", tags="seo,пф", author="Артём")
    second = store.add(
        kind="idea", text="Собрать FAQ", topic="Контент", source="owner-note", status="converted_to_task",
    )
    again = store.add(kind="artem", text="Проверить интент", topic="SEO")

    assert first["kind"] == "artem_recommendation"
    assert first["tags"] == ["seo", "пф"]
    assert second["kind"] == "owner_idea"
    assert second["status"] == "converted_to_task"
    assert len(store.list(kind="artem")) == 2
    assert {entry["id"] for entry in store.list(kind="artem")} == {first["id"], again["id"]}


def test_filters_and_searches_by_kind(tmp_path):
    database = temporary_database(tmp_path)
    store = KnowledgeStore(database)
    artem = store.add(kind="artem", text="Проверить коммерческий интент", topic="Яндекс")
    store.add(kind="idea", text="Проверить формат рубрики", topic="Контент")

    assert [entry["id"] for entry in store.list(kind="artem")] == [artem["id"]]
    assert [entry["id"] for entry in store.search(kind="artem", query="коммерческий")] == [artem["id"]]
    assert store.search(kind="idea", query="коммерческий") == []


def test_cli_outputs_stable_utf8_json_and_rejects_invalid_kind(tmp_path):
    database = temporary_database(tmp_path)
    added = json.loads(command(
        "knowledge-add", "--db", str(database), "--kind", "artem",
        "--text", "Рекомендация", "--topic", "ПФ", "--tags", "пф,seo",
    ).stdout)
    listed = json.loads(command(
        "knowledge-list", "--db", str(database), "--kind", "artem", "--limit", "20",
    ).stdout)
    found = json.loads(command(
        "knowledge-search", "--db", str(database), "--kind", "artem", "--query", "Рекомендация",
    ).stdout)

    assert listed == [added] == found
    rejected = subprocess.run(
        [sys.executable, "-m", "metrichit_os", "knowledge-list", "--db", str(database), "--kind", "wrong"],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert rejected.returncode == 2
    assert json.loads(rejected.stdout)["error"] == "ValueError"


def test_cli_stdin_preserves_utf8_multiline_text_and_validates_input_mode(tmp_path):
    database = temporary_database(tmp_path)
    text = "Первая строка\n\nПоследняя строка\n"
    result = subprocess.run(
        [
            sys.executable, "-m", "metrichit_os", "knowledge-add", "--db", str(database),
            "--kind", "idea", "--topic", "Многострочный ввод", "--stdin",
        ],
        input=text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    assert json.loads(result.stdout)["text"] == text

    for arguments in (
        ["knowledge-add", "--db", str(database), "--kind", "idea", "--topic", "Тема"],
        [
            "knowledge-add", "--db", str(database), "--kind", "idea", "--topic", "Тема",
            "--text", "Текст", "--stdin",
        ],
    ):
        rejected = subprocess.run(
            [sys.executable, "-m", "metrichit_os", *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert rejected.returncode == 2
        assert json.loads(rejected.stdout)["error"] == "ValueError"


def test_working_memory_database_is_not_changed_by_temp_database_tests(tmp_path):
    before = hashlib.sha256(MEMORY_DATABASE.read_bytes()).hexdigest()
    database = temporary_database(tmp_path)
    KnowledgeStore(database).add(kind="idea", text="Не трогать рабочую БД", topic="Тест")
    assert hashlib.sha256(MEMORY_DATABASE.read_bytes()).hexdigest() == before

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from metrichit_os.knowledge_store import KnowledgeError, KnowledgeStore
from metrichit_os.operator_panel import create_operator_app
from metrichit_os.project_scope import DEFAULT_PROJECT_ID, YADRO_DEVELOPMENT_PROJECT_ID
from metrichit_os.project_store import ProjectStore


def initialized(tmp_path: Path) -> Path:
    path = tmp_path / "scope.sqlite"
    subprocess.run(["node", "scripts/init-memory.mjs", str(path)], check=True, capture_output=True)
    return path


def test_default_projects_and_one_level_parent_validation(tmp_path: Path) -> None:
    path = initialized(tmp_path)
    projects = ProjectStore(path)
    listed = {item["id"]: item for item in projects.list()}
    assert listed[DEFAULT_PROJECT_ID]["name"] == "MetricHit"
    assert listed[DEFAULT_PROJECT_ID]["default_for_new"] is True
    assert listed[YADRO_DEVELOPMENT_PROJECT_ID]["name"] == "Развитие Ядра"

    metric_child, _ = projects.create(name="SEO", description="MetricHit SEO", parent_project_id=DEFAULT_PROJECT_ID)
    core_child, _ = projects.create(name="Инфраструктура", description="Core", parent_project_id=YADRO_DEVELOPMENT_PROJECT_ID)
    assert metric_child["scope_type"] == "subproject"
    projects.validate_assignment(DEFAULT_PROJECT_ID, str(metric_child["id"]), required=True)
    with pytest.raises(KnowledgeError, match="belong"):
        projects.validate_assignment(DEFAULT_PROJECT_ID, str(core_child["id"]), required=True)
    with pytest.raises((KnowledgeError, sqlite3.IntegrityError)):
        projects.create(name="Forbidden nesting", description="x", parent_project_id=str(metric_child["id"]))


def test_new_objects_default_to_metrichit_and_reject_cross_project_child(tmp_path: Path) -> None:
    path = initialized(tmp_path)
    projects, knowledge = ProjectStore(path), KnowledgeStore(path)
    child, _ = projects.create(name="Core child", description="x", parent_project_id=YADRO_DEVELOPMENT_PROJECT_ID)
    idea = knowledge.add(kind="idea", topic="Idea", text="Text")
    task = knowledge.create_task(title="Task", description="Text")
    converted = knowledge.to_task(entry_id=str(idea["id"]))
    assert idea["project_id"] == task["project_id"] == converted["project_id"] == DEFAULT_PROJECT_ID
    with pytest.raises(KnowledgeError, match="belong"):
        projects.validate_assignment(DEFAULT_PROJECT_ID, str(child["id"]), required=True)
    scoped = knowledge.create_task(title="Core scoped", description="x", project_id=YADRO_DEVELOPMENT_PROJECT_ID, subproject_id=str(child["id"]))
    child_summary = next(item for item in projects.list() if item["id"] == child["id"])
    assert child_summary["open_tasks"] == 1
    assert projects.detail(str(child["id"]))["tasks"][0]["id"] == scoped["id"]
    with sqlite3.connect(path) as db, pytest.raises(sqlite3.IntegrityError, match="requires project scope"):
        db.execute(
            "INSERT INTO tasks(id,type,title,content,data_json,status,author,access_level) VALUES(?, 'standalone_task','No scope','x','{}','pending','owner','internal')",
            ("90000000-0000-4000-a000-000000000001",),
        )


def test_panel_defaults_scope_and_protects_invalid_scope_actions(tmp_path: Path) -> None:
    path = initialized(tmp_path)
    app = create_operator_app(path)
    client = TestClient(app)
    token = json.loads(client.get("/").text.split('<script id="operator-panel-startup" type="application/json">', 1)[1].split("</script>", 1)[0])["token"]
    headers = {"X-Operator-Token": token}
    created = client.post("/api/entries", headers=headers, json={"kind": "idea", "topic": "Scoped", "text": "Text"})
    assert created.status_code == 201 and created.json()["project_id"] == DEFAULT_PROJECT_ID
    assert client.post("/api/tasks", json={"title": "No token", "description": "x"}).status_code == 403
    invalid = client.post("/api/tasks", headers=headers, json={"title": "Bad", "description": "x", "project_id": YADRO_DEVELOPMENT_PROJECT_ID, "subproject_id": DEFAULT_PROJECT_ID})
    assert invalid.status_code == 400


def test_cli_defaults_new_knowledge_to_metrichit_and_validates_child(tmp_path: Path) -> None:
    path = initialized(tmp_path)
    child, _ = ProjectStore(path).create(name="Core CLI", description="x", parent_project_id=YADRO_DEVELOPMENT_PROJECT_ID)
    created = subprocess.run(
        [sys.executable, "-m", "metrichit_os", "knowledge-add", "--db", str(path), "--kind", "artem", "--topic", "CLI", "--text", "Text"],
        check=True, capture_output=True, text=True, encoding="utf-8",
    )
    assert json.loads(created.stdout)["project_id"] == DEFAULT_PROJECT_ID
    invalid = subprocess.run(
        [sys.executable, "-m", "metrichit_os", "knowledge-add", "--db", str(path), "--kind", "idea", "--topic", "Bad", "--text", "Text", "--project-id", DEFAULT_PROJECT_ID, "--subproject-id", str(child["id"])],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert invalid.returncode == 2 and "belong" in invalid.stdout


def test_migration_keeps_legacy_objects_and_audit_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite"
    migrations = Path("data/database/migrations")
    with sqlite3.connect(path) as db:
        for migration in sorted(migrations.glob("00[1-8]_*.sql")):
            sql = migration.read_text(encoding="utf-8")
            db.executescript(sql)
            db.execute(
                "INSERT INTO schema_migrations(version,name,checksum) VALUES(?,?,?)",
                (int(migration.name.split("_", 1)[0]), migration.name, hashlib.sha256(migration.read_bytes()).hexdigest()),
            )
        db.execute(
            "INSERT INTO tasks(id,type,title,content,data_json,status,author,access_level) VALUES(?, 'standalone_task','Legacy','legacy','{\"priority\":\"normal\"}','pending','owner','internal')",
            ("90000000-0000-4000-a000-000000000002",),
        )
        before = db.execute("SELECT data_json,version FROM tasks WHERE title='Legacy'").fetchone()
        audit_before = db.execute("SELECT count(*) FROM audit_log").fetchone()[0]
    subprocess.run(["node", "scripts/init-memory.mjs", str(path)], check=True, capture_output=True)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT data_json,version FROM tasks WHERE title='Legacy'").fetchone() == before
        assert db.execute("SELECT count(*) FROM audit_log").fetchone()[0] == audit_before
        assert db.execute("SELECT max(version) FROM schema_migrations").fetchone()[0] == 9
    subprocess.run(["node", "scripts/init-memory.mjs", str(path)], check=True, capture_output=True)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM documents WHERE type='project' AND id IN (?,?)", (DEFAULT_PROJECT_ID, YADRO_DEVELOPMENT_PROJECT_ID)).fetchone()[0] == 2

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from metrichit_os.activity import list_activity_many
from metrichit_os.knowledge_store import KnowledgeError, KnowledgeStore
from metrichit_os.operator_panel import create_operator_app
from metrichit_os.project_scope import DEFAULT_PROJECT_ID, YADRO_CONTROL_PLANE_PROJECT_ID
from metrichit_os.project_storage import ProjectStorage
from metrichit_os.project_store import ProjectStore
from metrichit_os.runtime import RoutedKnowledgeStore, RoutedMemoryReviewStore, RuntimeDatabases


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
    assert listed[YADRO_CONTROL_PLANE_PROJECT_ID]["name"] == "Ядро"
    assert listed[YADRO_CONTROL_PLANE_PROJECT_ID]["scope_type"] == "control_plane"
    assert listed[DEFAULT_PROJECT_ID]["scope_type"] == "managed_project"

    metric_child, _ = projects.create(name="SEO", description="MetricHit SEO", parent_project_id=DEFAULT_PROJECT_ID)
    core_child, _ = projects.create(name="Инфраструктура", description="Core", parent_project_id=YADRO_CONTROL_PLANE_PROJECT_ID)
    assert metric_child["scope_type"] == "subproject"
    projects.validate_assignment(DEFAULT_PROJECT_ID, str(metric_child["id"]), required=True)
    with pytest.raises(KnowledgeError, match="belong"):
        projects.validate_assignment(DEFAULT_PROJECT_ID, str(core_child["id"]), required=True)
    with pytest.raises((KnowledgeError, sqlite3.IntegrityError)):
        projects.create(name="Forbidden nesting", description="x", parent_project_id=str(metric_child["id"]))


def test_new_objects_default_to_metrichit_and_reject_cross_project_child(tmp_path: Path) -> None:
    path = initialized(tmp_path)
    projects, knowledge = ProjectStore(path), KnowledgeStore(path)
    child, _ = projects.create(name="Core child", description="x", parent_project_id=YADRO_CONTROL_PLANE_PROJECT_ID)
    idea = knowledge.add(kind="idea", topic="Idea", text="Text")
    task = knowledge.create_task(title="Task", description="Text")
    converted = knowledge.to_task(entry_id=str(idea["id"]))
    assert idea["project_id"] == task["project_id"] == converted["project_id"] == DEFAULT_PROJECT_ID
    with pytest.raises(KnowledgeError, match="belong"):
        projects.validate_assignment(DEFAULT_PROJECT_ID, str(child["id"]), required=True)
    scoped = knowledge.create_task(title="Core scoped", description="x", project_id=YADRO_CONTROL_PLANE_PROJECT_ID, subproject_id=str(child["id"]))
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
    invalid = client.post("/api/tasks", headers=headers, json={"title": "Bad", "description": "x", "project_id": YADRO_CONTROL_PLANE_PROJECT_ID, "subproject_id": DEFAULT_PROJECT_ID})
    assert invalid.status_code == 400


def test_cli_defaults_new_knowledge_to_metrichit_and_validates_child(tmp_path: Path) -> None:
    path = initialized(tmp_path)
    child, _ = ProjectStore(path).create(name="Core CLI", description="x", parent_project_id=YADRO_CONTROL_PLANE_PROJECT_ID)
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


def test_migration_keeps_legacy_scope_and_records_only_targeted_role_audit(tmp_path: Path) -> None:
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
        db.execute(
            "INSERT INTO tasks(id,type,title,content,data_json,status,author,access_level) VALUES(?, 'knowledge_task','задачи на 17.08',?,'{\"priority\":\"normal\"}','pending','owner','internal')",
            (
                "a1023db2-32d7-4286-b635-03c27fef6a35",
                "Другая задача\nРазделение: ядро - самостоятельный проект. а метрикхит это подпроект в нем",
            ),
        )
        before = db.execute("SELECT data_json,version FROM tasks WHERE title='Legacy'").fetchone()
        audit_before = db.execute("SELECT count(*) FROM audit_log").fetchone()[0]
    subprocess.run(["node", "scripts/init-memory.mjs", str(path)], check=True, capture_output=True)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT data_json,version FROM tasks WHERE title='Legacy'").fetchone() == before
        assert db.execute("SELECT count(*) FROM audit_log").fetchone()[0] == audit_before + 3
        assert db.execute("SELECT max(version) FROM schema_migrations").fetchone()[0] == 11
        corrected = db.execute(
            "SELECT content,data_json FROM tasks WHERE id='a1023db2-32d7-4286-b635-03c27fef6a35'"
        ).fetchone()
        assert "а не подпроект" in corrected[0]
        assert corrected[1] == '{"priority":"normal"}'
    subprocess.run(["node", "scripts/init-memory.mjs", str(path)], check=True, capture_output=True)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM documents WHERE type='project' AND id IN (?,?)", (DEFAULT_PROJECT_ID, YADRO_CONTROL_PLANE_PROJECT_ID)).fetchone()[0] == 2


def _managed_database(root: Path, project_id: str) -> Path:
    directory = root / project_id
    directory.mkdir(parents=True)
    path = directory / "project.sqlite"
    subprocess.run(["node", "scripts/init-memory.mjs", str(path)], check=True, capture_output=True)
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE project_storage_metadata ("
            "singleton INTEGER PRIMARY KEY CHECK(singleton=1),"
            "project_id TEXT NOT NULL UNIQUE,storage_format INTEGER NOT NULL)"
        )
        db.execute("INSERT INTO project_storage_metadata VALUES(1,?,1)", (project_id,))
    return path


def test_generic_runtime_routes_two_managed_projects_and_transfer(tmp_path: Path, monkeypatch) -> None:
    central = initialized(tmp_path / "central")
    second, _ = ProjectStore(central).create(name="Second test project", description="fixture only")
    second_id = str(second["id"])
    storage_root = tmp_path / "projects"
    metrichit = _managed_database(storage_root, DEFAULT_PROJECT_ID)
    second_database = _managed_database(storage_root, second_id)
    with sqlite3.connect(central) as source, sqlite3.connect(second_database) as target:
        row = source.execute(
            "SELECT id,type,title,content,data_json,status,author,created_at,updated_at,access_level,version "
            "FROM documents WHERE id=?",
            (second_id,),
        ).fetchone()
        target.execute(
            "INSERT INTO documents(id,type,title,content,data_json,status,author,created_at,updated_at,access_level,version) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            row,
        )
    monkeypatch.setattr(
        "metrichit_os.runtime.verify_metrichit_runtime_storage",
        lambda source, target: {"cutover": True},
    )

    databases = RuntimeDatabases.resolve(
        central, project_paths=(metrichit, second_database)
    )
    store = RoutedKnowledgeStore(databases)
    projects = ProjectStore(central, tuple(path for _, path in databases.projects))

    first_idea = store.add(
        kind="idea", topic="First isolated idea", text="MetricHit only",
        project_id=DEFAULT_PROJECT_ID,
    )
    second_idea = store.add(
        kind="idea", topic="Second isolated idea", text="Second only",
        project_id=second_id,
    )
    first_task = store.create_task(
        title="First isolated task", description="MetricHit only",
        project_id=DEFAULT_PROJECT_ID,
    )
    second_task = store.to_task(
        entry_id=str(second_idea["id"]), project_id=second_id
    )
    core_task = store.create_task(
        title="Control task", description="Central only",
        project_id=YADRO_CONTROL_PLANE_PROJECT_ID,
    )

    expected = {
        metrichit: ({str(first_idea["id"])}, {str(first_task["id"])}),
        second_database: ({str(second_idea["id"])}, {str(second_task["id"])}),
        central: (set(), {str(core_task["id"])}),
    }
    for path, (document_ids, task_ids) in expected.items():
        with sqlite3.connect(path) as db:
            actual_documents = {
                row[0] for row in db.execute(
                    "SELECT id FROM documents WHERE id IN (?,?)",
                    (first_idea["id"], second_idea["id"]),
                )
            }
            actual_tasks = {
                row[0] for row in db.execute(
                    "SELECT id FROM tasks WHERE id IN (?,?,?)",
                    (first_task["id"], second_task["id"], core_task["id"]),
                )
            }
            assert actual_documents == document_ids
            assert actual_tasks == task_ids
            assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert db.execute("PRAGMA foreign_key_check").fetchone() is None

    assert {item["id"] for item in store.list_all(kind="idea")} >= {
        first_idea["id"], second_idea["id"],
    }
    assert first_idea["id"] in {item["id"] for item in projects.detail(DEFAULT_PROJECT_ID)["ideas"]}
    assert second_idea["id"] in {item["id"] for item in projects.detail(second_id)["ideas"]}
    assert databases.path_for_scope(YADRO_CONTROL_PLANE_PROJECT_ID) == central.resolve()
    with pytest.raises(KnowledgeError, match="canonical UUID"):
        databases.path_for_scope("not-a-project")
    with pytest.raises(KnowledgeError, match="active top-level"):
        databases.path_for_scope("90000000-0000-4000-a000-000000000099")
    missing, _ = ProjectStore(central).create(name="Missing storage", description="fixture only")
    with pytest.raises(KnowledgeError, match="storage is not available"):
        databases.path_for_scope(str(missing["id"]))

    activity_projects = {
        item["project_id"]
        for item in list_activity_many(databases.read_paths)["items"]
        if item["target_id"] in {
            first_idea["id"], second_idea["id"], first_task["id"], second_task["id"],
        }
    }
    assert activity_projects == {DEFAULT_PROJECT_ID, second_id}

    candidate_ids = (
        "91000000-0000-4000-a000-000000000001",
        "92000000-0000-4000-a000-000000000002",
    )
    for index, (path, candidate_id) in enumerate(
        ((metrichit, candidate_ids[0]), (second_database, candidate_ids[1])), start=1
    ):
        source_id = f"{index}3000000-0000-4000-a000-00000000000{index}"
        with sqlite3.connect(path) as db:
            db.execute(
                "INSERT INTO sources(id,type,title,content,author) VALUES(?, 'test', ?, 'fixture', 'owner')",
                (source_id, f"Project source {index}"),
            )
            db.execute(
                "INSERT INTO memory_candidates(id,type,semantic_key,title,content,source_id,author) "
                "VALUES(?, 'fact', ?, ?, 'fixture', ?, 'owner')",
                (candidate_id, f"project.fixture.{index}", f"Project candidate {index}", source_id),
            )
    memory = RoutedMemoryReviewStore(databases, tmp_path / "unused-context.md")
    assert {item["id"] for item in memory.candidates()} >= set(candidate_ids)
    assert memory.reject(candidate_ids[1], "fixture isolation")["status"] == "rejected"
    with sqlite3.connect(metrichit) as db:
        assert db.execute(
            "SELECT status FROM memory_candidates WHERE id=?", (candidate_ids[0],)
        ).fetchone()[0] == "pending"
    with sqlite3.connect(second_database) as db:
        assert db.execute(
            "SELECT status FROM memory_candidates WHERE id=?", (candidate_ids[1],)
        ).fetchone()[0] == "rejected"

    package = tmp_path / "second-project.zip"
    exported = ProjectStorage(storage_root).export_package(second_id, package)
    imported = ProjectStorage(tmp_path / "imported").import_package(package)
    repeated = ProjectStorage(tmp_path / "imported").import_package(package)
    assert exported["projectId"] == imported["projectId"] == second_id
    assert imported["imported"] is True and repeated["imported"] is False

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from metrichit_os.database import sha256_file
from metrichit_os.project_migration import build_migration_plan, migration_plan_summary
from metrichit_os.project_scope import DEFAULT_PROJECT_ID, YADRO_CONTROL_PLANE_PROJECT_ID


CORE_RECORD = "10000000-0000-4000-a000-000000000001"
METRIC_RECORD = "10000000-0000-4000-a000-000000000002"
UNSCOPED_RECORD = "10000000-0000-4000-a000-000000000003"
CONFLICT_RECORD = "10000000-0000-4000-a000-000000000004"
SUBPROJECT_ID = "10000000-0000-4000-a000-000000000005"


def _database(path: Path) -> None:
    with sqlite3.connect(path) as db:
        db.executescript("""
        CREATE TABLE documents(id TEXT PRIMARY KEY,type TEXT,title TEXT,content TEXT,data_json TEXT,source_id TEXT);
        CREATE TABLE tasks(id TEXT PRIMARY KEY,type TEXT,title TEXT,content TEXT,data_json TEXT,source_id TEXT);
        CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,name TEXT);
        """)
        projects = [
            (YADRO_CONTROL_PLANE_PROJECT_ID, {"scope_type": "control_plane"}),
            (DEFAULT_PROJECT_ID, {"scope_type": "managed_project"}),
            (SUBPROJECT_ID, {"scope_type": "subproject", "parent_project_id": DEFAULT_PROJECT_ID}),
        ]
        for project_id, metadata in projects:
            db.execute("INSERT INTO documents VALUES(?, 'project', 'secret project title', 'secret content', ?, NULL)", (project_id, json.dumps(metadata)))
        db.execute("INSERT INTO tasks VALUES(?, 'task', 'secret core title', 'secret core content', ?, NULL)", (CORE_RECORD, json.dumps({"project_id": YADRO_CONTROL_PLANE_PROJECT_ID})))
        db.execute("INSERT INTO tasks VALUES(?, 'task', 'secret metric title', 'secret metric content', ?, NULL)", (METRIC_RECORD, json.dumps({"project_id": DEFAULT_PROJECT_ID})))
        db.execute("INSERT INTO tasks VALUES(?, 'task', 'secret legacy title', 'secret legacy content', '{}', NULL)", (UNSCOPED_RECORD,))
        db.execute("INSERT INTO tasks VALUES(?, 'task', 'secret conflict title', 'secret conflict content', ?, NULL)", (CONFLICT_RECORD, json.dumps({"project_id": YADRO_CONTROL_PLANE_PROJECT_ID, "subproject_id": SUBPROJECT_ID})))
        db.execute("INSERT INTO schema_migrations VALUES(1, 'secret migration name')")


def test_planner_classifies_explicit_scope_fails_closed_and_is_deterministic(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite"
    _database(path)
    before = sha256_file(path)
    first = build_migration_plan(path)
    second = build_migration_plan(path)
    assert first == second
    assert first["manifestSha256"] == second["manifestSha256"]
    assert sha256_file(path) == before
    records = {item["id"]: item for item in first["records"]}
    assert records[CORE_RECORD]["classification"] == "core"
    assert records[METRIC_RECORD]["classification"] == "managed_project"
    assert records[METRIC_RECORD]["projectId"] == DEFAULT_PROJECT_ID
    assert records[UNSCOPED_RECORD]["classification"] == "unresolved"
    assert "legacy_unscoped" in records[UNSCOPED_RECORD]["reasons"]
    assert records[CONFLICT_RECORD]["classification"] == "unresolved"
    assert "conflicting_project_links" in records[CONFLICT_RECORD]["reasons"]
    assert first["readyToMigrate"] is False


def test_plan_and_summary_do_not_leak_content(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite"
    _database(path)
    rendered = json.dumps(build_migration_plan(path), ensure_ascii=False)
    summary = json.dumps(migration_plan_summary(build_migration_plan(path)), ensure_ascii=False)
    assert "secret" not in rendered
    assert "secret" not in summary
    assert "records" not in migration_plan_summary(build_migration_plan(path))
    assert migration_plan_summary(build_migration_plan(path))["countsByEntity"]
    assert migration_plan_summary(build_migration_plan(path))["unresolvedByEntity"]

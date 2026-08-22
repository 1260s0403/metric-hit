from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from metrichit_os.database import sha256_file
from metrichit_os.project_migration import (
    OWNERSHIP_BATCH_KEY,
    _audit_id,
    apply_approved_ownership_batch,
    build_migration_plan,
    migration_plan_summary,
)
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


def _ownership_database(path: Path) -> None:
    with sqlite3.connect(path) as db:
        db.executescript("""
        CREATE TABLE memory_candidates(id TEXT PRIMARY KEY,type TEXT,data_json TEXT,source_id TEXT,author TEXT,updated_at TEXT,version INTEGER);
        CREATE TABLE decisions(id TEXT PRIMARY KEY,type TEXT,data_json TEXT,source_id TEXT,author TEXT,updated_at TEXT,version INTEGER);
        CREATE TABLE tasks(id TEXT PRIMARY KEY,type TEXT,data_json TEXT,source_id TEXT,author TEXT,updated_at TEXT,version INTEGER);
        CREATE TABLE audit_log(
          id TEXT PRIMARY KEY,type TEXT,title TEXT,content TEXT,data_json TEXT,status TEXT DEFAULT 'recorded',
          source_id TEXT,author TEXT,created_at TEXT,updated_at TEXT,valid_at TEXT,access_level TEXT,
          version INTEGER,entity_type TEXT,entity_id TEXT,action TEXT
        );
        CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,name TEXT);
        INSERT INTO schema_migrations VALUES(1,'initial');
        """)
        counters = {
            "editorial_rule": 10, "commercial_terms": 3, "official_channel": 2,
            "official_resource": 2, "product_fact": 6, "publication_state": 6,
            "ai_policy": 4,
        }
        index = 1
        for entity_type, count in counters.items():
            for _ in range(count):
                entity_id = f"20000000-0000-4000-a000-{index:012d}"
                db.execute(
                    "INSERT INTO memory_candidates VALUES(?,?, '{}',NULL,'owner','2026-08-22T00:00:00Z',1)",
                    (entity_id, entity_type),
                )
                index += 1
        db.execute("INSERT INTO decisions VALUES('30000000-0000-4000-a000-000000000001','editorial_policy','{}',NULL,'owner','2026-08-22T00:00:00Z',1)")
        db.execute("INSERT INTO tasks VALUES('40000000-0000-4000-a000-000000000001','analytics_implementation','{}',NULL,'owner','2026-08-22T00:00:00Z',1)")
        db.execute("INSERT INTO tasks VALUES('40000000-0000-4000-a000-000000000002','standalone_task','{}',NULL,'owner','2026-08-22T00:00:00Z',1)")


def _apply(path: Path, tmp_path: Path, rollback_name: str = "rollback.json") -> dict[str, object]:
    backup = tmp_path / "verified-backup"
    backup.mkdir(exist_ok=True)
    (backup / "test-manifest.json").write_text("{}", encoding="utf-8")
    plan = build_migration_plan(path)
    return apply_approved_ownership_batch(
        path,
        expected_source_sha256=plan["sourceSha256"],
        expected_manifest_sha256=plan["manifestSha256"],
        rollback_manifest_path=tmp_path / rollback_name,
        verified_backup_set=backup,
    )


def test_approved_ownership_batch_applies_exact_31_4_and_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite"
    _ownership_database(path)
    result = _apply(path, tmp_path)
    assert result["applied"] == 35
    with sqlite3.connect(path) as db:
        immutable_candidates = db.execute(
            "SELECT count(*) FROM memory_candidates WHERE data_json='{}' AND version=1"
        ).fetchone()[0]
        untouched = db.execute(
            "SELECT data_json,version FROM tasks WHERE type='standalone_task'"
        ).fetchone()
        audits = db.execute(
            "SELECT count(*) FROM audit_log WHERE json_extract(data_json,'$.batchKey')=?", (OWNERSHIP_BATCH_KEY,)
        ).fetchone()[0]
    plan = build_migration_plan(path)
    metric = sum(record.get("projectId") == DEFAULT_PROJECT_ID for record in plan["records"])
    core = sum(record["classification"] == "core" for record in plan["records"])
    assert (immutable_candidates, metric, core, untouched, audits) == (33, 62, 9, ("{}", 1), 35)
    repeated = _apply(path, tmp_path, "unused.json")
    assert repeated["applied"] == 0 and repeated["alreadyApplied"] == 35
    assert not (tmp_path / "unused.json").exists()


def test_approved_ownership_batch_guards_mismatch_and_rolls_back_transaction(tmp_path: Path) -> None:
    mismatch = tmp_path / "mismatch.sqlite"
    _ownership_database(mismatch)
    backup = tmp_path / "verified-backup"
    backup.mkdir()
    (backup / "test-manifest.json").write_text("{}", encoding="utf-8")
    plan = build_migration_plan(mismatch)
    try:
        apply_approved_ownership_batch(
            mismatch, expected_source_sha256="0" * 64, expected_manifest_sha256=plan["manifestSha256"],
            rollback_manifest_path=tmp_path / "mismatch.json", verified_backup_set=backup,
        )
    except RuntimeError as error:
        assert "source SHA-256 guard mismatch" in str(error)
    else:
        raise AssertionError("source mismatch must fail closed")

    first_id = "30000000-0000-4000-a000-000000000001"
    conflict_id = _audit_id("decisions", first_id, DEFAULT_PROJECT_ID)
    with sqlite3.connect(mismatch) as db:
        db.execute(
            "INSERT INTO audit_log(id,type,title,data_json,author,created_at,updated_at,access_level,version,entity_type,entity_id,action) "
            "VALUES(?, 'other','other','{}','owner','x','x','restricted',1,'other',?,'update')",
            (conflict_id, first_id),
        )
    plan = build_migration_plan(mismatch)
    try:
        apply_approved_ownership_batch(
            mismatch, expected_source_sha256=plan["sourceSha256"], expected_manifest_sha256=plan["manifestSha256"],
            rollback_manifest_path=tmp_path / "rollback-after-conflict.json", verified_backup_set=backup,
        )
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("audit collision must roll back the whole transaction")
    with sqlite3.connect(mismatch) as db:
        assert db.execute(
            "SELECT count(*) FROM audit_log WHERE json_extract(data_json,'$.batchKey')=?", (OWNERSHIP_BATCH_KEY,)
        ).fetchone()[0] == 0

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from metrichit_os import project_migration
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


def test_primary_relations_override_stale_derived_links_but_not_confirmed_memory(tmp_path: Path) -> None:
    path = tmp_path / "relation-precedence.sqlite"
    source_id = "11000000-0000-4000-a000-000000000001"
    task_id = "11000000-0000-4000-a000-000000000002"
    candidate_id = "11000000-0000-4000-a000-000000000003"
    with sqlite3.connect(path) as db:
        db.executescript("""
        CREATE TABLE sources(id TEXT PRIMARY KEY,type TEXT,data_json TEXT);
        CREATE TABLE tasks(id TEXT PRIMARY KEY,type TEXT,data_json TEXT,source_id TEXT);
        CREATE TABLE memory_candidates(id TEXT PRIMARY KEY,type TEXT,data_json TEXT,source_id TEXT);
        CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,name TEXT);
        INSERT INTO schema_migrations VALUES(1,'initial');
        """)
        db.execute(
            "INSERT INTO sources VALUES(?, 'owner_decision', ?)",
            (source_id, json.dumps({"project_id": YADRO_CONTROL_PLANE_PROJECT_ID})),
        )
        db.execute(
            "INSERT INTO tasks VALUES(?, 'standalone_task', ?, ?)",
            (task_id, json.dumps({"project_id": DEFAULT_PROJECT_ID}), source_id),
        )
        db.execute(
            "INSERT INTO memory_candidates VALUES(?, 'decision', ?, ?)",
            (candidate_id, json.dumps({"project_id": DEFAULT_PROJECT_ID}), source_id),
        )

    records = {record["id"]: record for record in build_migration_plan(path)["records"]}
    assert records[source_id]["classification"] == "core"
    assert records[task_id]["classification"] == "core"
    assert records[candidate_id]["classification"] == "managed_project"


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


def _decision_ownership_database(path: Path, entity_ids: list[str], special_id: str) -> None:
    with sqlite3.connect(path) as db:
        db.executescript("""
        CREATE TABLE memory_candidates(
          id TEXT PRIMARY KEY,type TEXT,semantic_key TEXT,title TEXT,data_json TEXT,
          source_id TEXT,author TEXT,updated_at TEXT,version INTEGER
        );
        CREATE TABLE tasks(id TEXT PRIMARY KEY,type TEXT,data_json TEXT,source_id TEXT,author TEXT,updated_at TEXT,version INTEGER);
        CREATE TABLE audit_log(
          id TEXT PRIMARY KEY,type TEXT,title TEXT,content TEXT,data_json TEXT,status TEXT DEFAULT 'recorded',
          source_id TEXT,author TEXT,created_at TEXT,updated_at TEXT,valid_at TEXT,access_level TEXT,
          version INTEGER,entity_type TEXT,entity_id TEXT,action TEXT
        );
        CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,name TEXT);
        INSERT INTO schema_migrations VALUES(1,'initial');
        INSERT INTO tasks VALUES('90000000-0000-4000-a000-000000000001','outside_scope','{}',NULL,'owner','x',1);
        """)
        for index, entity_id in enumerate(entity_ids):
            metadata = (
                {"project_id": project_migration.DECISION_OWNERSHIP_SPECIAL_INVALID_PROJECT_ID, "contract": True}
                if entity_id == special_id else {"payload": index}
            )
            db.execute(
                "INSERT INTO memory_candidates VALUES(?, 'decision', ?, ?, ?, NULL, 'owner', 'x', 1)",
                (
                    entity_id,
                    "architecture.project_storage_foundation" if entity_id == special_id else f"decision.{index}",
                    f"Decision {index}",
                    json.dumps(metadata, sort_keys=True),
                ),
            )


def test_decision_ownership_batch_exact_selector_idempotency_audit_and_rollback(
    tmp_path: Path, monkeypatch,
) -> None:
    special_id = "50000000-0000-4000-a000-000000000000"
    entity_ids = [special_id] + [f"50000000-0000-4000-a000-{index:012d}" for index in range(1, 62)]
    metric_ids = frozenset(entity_ids[1:8])
    target_digest = project_migration._decision_target_ids_sha256(entity_ids)
    monkeypatch.setattr(project_migration, "DECISION_OWNERSHIP_SPECIAL_ID", special_id)
    monkeypatch.setattr(project_migration, "DECISION_OWNERSHIP_METRICHIT_IDS", metric_ids)
    monkeypatch.setattr(
        project_migration, "DECISION_OWNERSHIP_METRICHIT_KEYS",
        {entity_id: f"decision.{index}" for index, entity_id in enumerate(entity_ids) if entity_id in metric_ids},
    )
    monkeypatch.setattr(project_migration, "DECISION_OWNERSHIP_TARGET_IDS_SHA256", target_digest)
    path = tmp_path / "legacy.sqlite"
    _decision_ownership_database(path, entity_ids, special_id)
    before_plan = build_migration_plan(path)
    before_unresolved = {
        (record["table"], record["id"])
        for record in before_plan["records"] if record["classification"] == "unresolved"
    }
    with sqlite3.connect(path) as db:
        original = db.execute(
            "SELECT id,data_json,updated_at,version FROM memory_candidates ORDER BY id"
        ).fetchall()
    backup = tmp_path / "verified-backup"
    backup.mkdir()
    (backup / "test-manifest.json").write_text("{}", encoding="utf-8")
    rollback = tmp_path / "rollback.json"
    result = project_migration.apply_approved_decision_ownership_batch(
        path,
        expected_source_sha256=before_plan["sourceSha256"],
        expected_manifest_sha256=before_plan["manifestSha256"],
        rollback_manifest_path=rollback,
        verified_backup_set=backup,
    )
    assert result["applied"] == 62
    assert result["approvedSplit"] == {"ordinaryCore": 54, "metricHit": 7, "specialCore": 1}
    assert result["unchangedNonTargetUnresolved"] == 1
    rollback_data = json.loads(rollback.read_text(encoding="utf-8"))
    assert len(rollback_data["rows"]) == 62
    assert rollback_data["targetIdsSha256"] == target_digest
    with sqlite3.connect(path) as db:
        assert db.execute(
            "SELECT id,data_json,updated_at,version FROM memory_candidates ORDER BY id"
        ).fetchall() == original
        audit_rows = db.execute(
            "SELECT type,data_json FROM audit_log WHERE json_extract(data_json,'$.batchKey')=?",
            (project_migration.DECISION_OWNERSHIP_BATCH_KEY,),
        ).fetchall()
    assert len(audit_rows) == 62
    corrections = [json.loads(data) for audit_type, data in audit_rows if audit_type == "project_scope_metadata_correction"]
    assert len(corrections) == 1
    assert corrections[0]["entityId"] == special_id
    assert corrections[0]["correction"]["invalidValue"] == "canonical_lowercase_uuid_v4"
    after_plan = build_migration_plan(path)
    after_unresolved = {
        (record["table"], record["id"])
        for record in after_plan["records"] if record["classification"] == "unresolved"
    }
    assert after_unresolved == before_unresolved - {("memory_candidates", entity_id) for entity_id in entity_ids}
    repeated = project_migration.apply_approved_decision_ownership_batch(
        path,
        expected_source_sha256="ignored-after-completion",
        expected_manifest_sha256="ignored-after-completion",
        rollback_manifest_path=tmp_path / "unused.json",
        verified_backup_set=backup,
    )
    assert repeated["applied"] == 0 and repeated["alreadyApplied"] == 62
    assert not (tmp_path / "unused.json").exists()


def test_decision_ownership_batch_rejects_selector_drift_before_writes(tmp_path: Path, monkeypatch) -> None:
    special_id = "60000000-0000-4000-a000-000000000000"
    entity_ids = [special_id] + [f"60000000-0000-4000-a000-{index:012d}" for index in range(1, 62)]
    monkeypatch.setattr(project_migration, "DECISION_OWNERSHIP_SPECIAL_ID", special_id)
    monkeypatch.setattr(project_migration, "DECISION_OWNERSHIP_METRICHIT_IDS", frozenset(entity_ids[1:8]))
    monkeypatch.setattr(project_migration, "DECISION_OWNERSHIP_TARGET_IDS_SHA256", "0" * 64)
    path = tmp_path / "drift.sqlite"
    _decision_ownership_database(path, entity_ids, special_id)
    backup = tmp_path / "verified-backup"
    backup.mkdir()
    (backup / "test-manifest.json").write_text("{}", encoding="utf-8")
    plan = build_migration_plan(path)
    try:
        project_migration.apply_approved_decision_ownership_batch(
            path,
            expected_source_sha256=plan["sourceSha256"],
            expected_manifest_sha256=plan["manifestSha256"],
            rollback_manifest_path=tmp_path / "rollback.json",
            verified_backup_set=backup,
        )
    except RuntimeError as error:
        assert "selector ID set mismatch" in str(error)
    else:
        raise AssertionError("selector drift must fail closed")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM audit_log").fetchone()[0] == 0
    assert not (tmp_path / "rollback.json").exists()


def _final_ownership_database(
    path: Path,
    *,
    source_ids: list[str],
    knowledge_ids: list[str],
    project_ids: list[str],
    task_id: str,
) -> None:
    with sqlite3.connect(path) as db:
        db.executescript("""
        CREATE TABLE sources(
          id TEXT PRIMARY KEY,type TEXT,title TEXT,content TEXT,data_json TEXT,status TEXT,
          author TEXT,created_at TEXT,updated_at TEXT,valid_at TEXT,access_level TEXT,version INTEGER
        );
        CREATE TABLE documents(
          id TEXT PRIMARY KEY,type TEXT,title TEXT,content TEXT,data_json TEXT,status TEXT,
          source_id TEXT,author TEXT,created_at TEXT,updated_at TEXT,valid_at TEXT,access_level TEXT,version INTEGER
        );
        CREATE TABLE tasks(
          id TEXT PRIMARY KEY,type TEXT,title TEXT,content TEXT,data_json TEXT,status TEXT,
          source_id TEXT,author TEXT,created_at TEXT,updated_at TEXT,valid_at TEXT,access_level TEXT,version INTEGER
        );
        CREATE TABLE memory_candidates(
          id TEXT PRIMARY KEY,type TEXT,data_json TEXT,source_id TEXT,author TEXT,updated_at TEXT,version INTEGER
        );
        CREATE TABLE audit_log(
          id TEXT PRIMARY KEY,type TEXT,title TEXT,content TEXT,data_json TEXT,status TEXT DEFAULT 'recorded',
          source_id TEXT,author TEXT,created_at TEXT,updated_at TEXT,valid_at TEXT,access_level TEXT,
          version INTEGER,entity_type TEXT,entity_id TEXT,action TEXT
        );
        CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,name TEXT);
        INSERT INTO schema_migrations VALUES(1,'initial');
        """)
        for index, source_id in enumerate(source_ids):
            source_type = "chat_summary_file" if index < 3 else "owner_decision"
            db.execute(
                "INSERT INTO sources VALUES(?,?,?,'secret source','{}','active','owner','x','x',NULL,'internal',1)",
                (source_id, source_type, f"Source {index}"),
            )
        for index, knowledge_id in enumerate(knowledge_ids):
            metadata = {"project_id": project_ids[0]} if index == 0 else {"kind": "owner_idea"}
            db.execute(
                "INSERT INTO documents VALUES(?,'knowledge_entry',?,'secret knowledge',?,'active',NULL,'owner',"
                "'x','x',NULL,'internal',1)",
                (knowledge_id, f"Knowledge {index}", json.dumps(metadata)),
            )
        project_metadata = [
            {"kind": "project"},
            {
                "kind": "project",
                "scope_type": "subproject",
                "parent_project_id": YADRO_CONTROL_PLANE_PROJECT_ID,
            },
            {
                "kind": "project",
                "scope_type": "subproject",
                "parent_project_id": YADRO_CONTROL_PLANE_PROJECT_ID,
            },
        ]
        for index, project_id in enumerate(project_ids):
            db.execute(
                "INSERT INTO documents VALUES(?,'project',?,'secret project',?,'active',NULL,'owner',"
                "'x','x',NULL,'internal',1)",
                (project_id, f"Project {index}", json.dumps(project_metadata[index])),
            )
        db.execute(
            "INSERT INTO tasks VALUES(?,'standalone_task','Legacy task','secret task','{}','cancelled',NULL,"
            "'owner','x','x',NULL,'internal',1)",
            (task_id,),
        )
        knowledge_task_id = "70000000-0000-4000-a000-000000000001"
        db.execute(
            "INSERT INTO tasks VALUES(?,'knowledge_task','Knowledge task','secret task',?,'pending',NULL,"
            "'owner','x','x',NULL,'internal',1)",
            (knowledge_task_id, json.dumps({"knowledge_entry_id": knowledge_ids[1]})),
        )
        db.execute(
            "INSERT INTO memory_candidates VALUES(?, 'decision', ?, ?, 'owner', 'x', 1)",
            (
                "71000000-0000-4000-a000-000000000001",
                json.dumps({"project_id": DEFAULT_PROJECT_ID}),
                source_ids[-1],
            ),
        )
        for index in range(255):
            audit_id = f"80000000-0000-4000-a000-{index:012d}"
            db.execute(
                "INSERT INTO audit_log(id,type,title,data_json,author,created_at,updated_at,access_level,version,"
                "entity_type,entity_id,action) VALUES(?,'task_change','Task changed','{}','owner','x','x',"
                "'restricted',1,'task',?,'update')",
                (audit_id, knowledge_task_id),
            )


def _configure_final_batch(monkeypatch, plan: dict[str, object]) -> list[dict[str, str]]:
    unresolved = [record for record in plan["records"] if record["classification"] == "unresolved"]
    source_records = [record for record in unresolved if record["table"] == "sources"]
    knowledge_records = [
        record for record in unresolved
        if record["table"] == "documents" and record["entityType"] == "knowledge_entry"
    ]
    project_records = [
        record for record in unresolved
        if record["table"] == "documents" and record["entityType"] == "project"
    ]
    task = next(record for record in unresolved if record["entityType"] == "standalone_task")
    metric_sources = frozenset(record["id"] for record in source_records[:9])
    monkeypatch.setattr(project_migration, "FINAL_OWNERSHIP_METRICHIT_SOURCE_IDS", metric_sources)
    monkeypatch.setattr(project_migration, "FINAL_OWNERSHIP_STANDALONE_TASK_ID", task["id"])
    structural_knowledge = next(record for record in knowledge_records if record["reasons"] == ["unknown_project_role"])
    monkeypatch.setattr(
        project_migration,
        "FINAL_OWNERSHIP_STRUCTURAL_KNOWLEDGE_ID",
        structural_knowledge["id"],
    )
    control_knowledge = next(
        record for record in knowledge_records
        if record["id"] != structural_knowledge["id"]
    )
    monkeypatch.setattr(
        project_migration,
        "FINAL_OWNERSHIP_CONTROL_KNOWLEDGE_ID",
        control_knowledge["id"],
    )
    project_ids = [record["id"] for record in project_records]
    unknown_project = next(record["id"] for record in project_records if record["reasons"] == ["unknown_project_role"])
    invalid_projects = sorted(
        record["id"] for record in project_records if record["reasons"] == ["invalid_subproject_parent"]
    )
    monkeypatch.setattr(project_migration, "FINAL_OWNERSHIP_PROJECT_CORRECTIONS", {
        unknown_project: (
            {
                "field": "scope_type", "invalidValue": None, "newValue": "subproject",
                "reason": "legacy test project was missing its subproject role",
            },
            {
                "field": "parent_project_id", "invalidValue": None,
                "newValue": DEFAULT_PROJECT_ID,
                "reason": "legacy test project was missing its MetricHit parent",
            },
        ),
        **{
            project_id: ({
                "field": "parent_project_id",
                "invalidValue": YADRO_CONTROL_PLANE_PROJECT_ID,
                "newValue": DEFAULT_PROJECT_ID,
                "reason": "subprojects belong under the managed MetricHit project, not the control plane",
            },)
            for project_id in invalid_projects
        },
    })
    source_targets = [
        {
            "table": "sources", "entityType": record["entityType"], "id": record["id"],
            "projectId": DEFAULT_PROJECT_ID if record["id"] in metric_sources else YADRO_CONTROL_PLANE_PROJECT_ID,
        }
        for record in source_records
    ]
    knowledge_targets = [
        {
            "table": "documents", "entityType": "knowledge_entry", "id": record["id"],
            "projectId": DEFAULT_PROJECT_ID,
        }
        for record in knowledge_records
    ]
    project_targets = [
        {
            "table": "documents", "entityType": "project", "id": record["id"],
            "projectId": DEFAULT_PROJECT_ID,
        }
        for record in project_records
    ]
    task_target = {
        "table": "tasks", "entityType": "standalone_task", "id": task["id"],
        "projectId": DEFAULT_PROJECT_ID,
    }
    targets = [*source_targets, *knowledge_targets, *project_targets, task_target]
    monkeypatch.setattr(
        project_migration, "FINAL_OWNERSHIP_SOURCE_IDS_SHA256",
        project_migration._final_target_ids_sha256(source_targets),
    )
    monkeypatch.setattr(
        project_migration, "FINAL_OWNERSHIP_KNOWLEDGE_IDS_SHA256",
        project_migration._final_target_ids_sha256(knowledge_targets),
    )
    monkeypatch.setattr(
        project_migration, "FINAL_OWNERSHIP_PROJECT_IDS_SHA256",
        project_migration._final_target_ids_sha256(project_targets),
    )
    monkeypatch.setattr(
        project_migration, "FINAL_OWNERSHIP_TARGET_IDS_SHA256",
        project_migration._final_target_ids_sha256(targets),
    )
    monkeypatch.setattr(
        project_migration, "FINAL_OWNERSHIP_ASSIGNMENTS_SHA256",
        project_migration._final_assignments_sha256(targets),
    )
    corrected_targets = [
        {
            **target,
            "projectId": (
                YADRO_CONTROL_PLANE_PROJECT_ID
                if target["id"] == control_knowledge["id"]
                else target["projectId"]
            ),
        }
        for target in targets
    ]
    monkeypatch.setattr(
        project_migration, "FINAL_OWNERSHIP_CORRECTED_ASSIGNMENTS_SHA256",
        project_migration._final_assignments_sha256(corrected_targets),
    )
    return targets


def test_final_ownership_batch_resolves_all_348_with_inheritance_and_is_idempotent(
    tmp_path: Path, monkeypatch,
) -> None:
    source_ids = [f"50000000-0000-4000-a000-{index:012d}" for index in range(71)]
    knowledge_ids = [f"60000000-0000-4000-a000-{index:012d}" for index in range(17)]
    project_ids = [
        "61000000-0000-4000-a000-000000000001",
        "61000000-0000-4000-a000-000000000002",
        "61000000-0000-4000-a000-000000000003",
    ]
    task_id = "62000000-0000-4000-a000-000000000001"
    path = tmp_path / "legacy.sqlite"
    _final_ownership_database(
        path,
        source_ids=source_ids,
        knowledge_ids=knowledge_ids,
        project_ids=project_ids,
        task_id=task_id,
    )
    before = build_migration_plan(path)
    assert before["counts"]["unresolved"] == 348
    targets = _configure_final_batch(monkeypatch, before)
    with sqlite3.connect(path) as db:
        original = {
            (target["table"], target["id"]): db.execute(
                f'SELECT data_json,updated_at,version FROM "{target["table"]}" WHERE id=?',
                (target["id"],),
            ).fetchone()
            for target in targets
        }
    backup = tmp_path / "verified-backup"
    backup.mkdir()
    (backup / "test-manifest.json").write_text("{}", encoding="utf-8")
    rollback = tmp_path / "rollback.json"
    result = project_migration.apply_approved_final_ownership_batch(
        path,
        expected_source_sha256=before["sourceSha256"],
        expected_manifest_sha256=before["manifestSha256"],
        rollback_manifest_path=rollback,
        verified_backup_set=backup,
    )
    assert result["applied"] == 93
    assert result["resolvedUnresolved"] == 348
    assert result["readyToMigrate"] is True
    assert result["counts"]["unresolved"] == 0
    rollback_data = json.loads(rollback.read_text(encoding="utf-8"))
    assert len(rollback_data["rows"]) == 92
    assert rollback_data["targetIdsSha256"] == project_migration.FINAL_OWNERSHIP_TARGET_IDS_SHA256
    with sqlite3.connect(path) as db:
        assert db.execute(
            "SELECT count(*) FROM audit_log WHERE json_extract(data_json,'$.batchKey')=?",
            (project_migration.FINAL_OWNERSHIP_BATCH_KEY,),
        ).fetchone()[0] == 92
        assert db.execute(
            "SELECT count(*) FROM audit_log WHERE json_extract(data_json,'$.batchKey')=?",
            (project_migration.FINAL_OWNERSHIP_CORRECTION_BATCH_KEY,),
        ).fetchone()[0] == 1
        for target in targets:
            assert db.execute(
                f'SELECT data_json,updated_at,version FROM "{target["table"]}" WHERE id=?',
                (target["id"],),
            ).fetchone() == original[(target["table"], target["id"])]
    after = build_migration_plan(path)
    records = {(record["table"], record["id"]): record for record in after["records"]}
    assert records[("tasks", "70000000-0000-4000-a000-000000000001")]["classification"] == "core"
    assert records[("memory_candidates", "71000000-0000-4000-a000-000000000001")]["classification"] == "managed_project"
    assert all(record["classification"] != "unresolved" for record in after["records"])
    repeated = project_migration.apply_approved_final_ownership_batch(
        path,
        expected_source_sha256="ignored-after-completion",
        expected_manifest_sha256="ignored-after-completion",
        rollback_manifest_path=tmp_path / "unused.json",
        verified_backup_set=backup,
    )
    assert repeated["applied"] == 0 and repeated["alreadyApplied"] == 93
    assert not (tmp_path / "unused.json").exists()


def test_final_ownership_batch_rejects_assignment_hash_drift_before_writes(
    tmp_path: Path, monkeypatch,
) -> None:
    source_ids = [f"51000000-0000-4000-a000-{index:012d}" for index in range(71)]
    knowledge_ids = [f"63000000-0000-4000-a000-{index:012d}" for index in range(17)]
    project_ids = [
        "64000000-0000-4000-a000-000000000001",
        "64000000-0000-4000-a000-000000000002",
        "64000000-0000-4000-a000-000000000003",
    ]
    task_id = "65000000-0000-4000-a000-000000000001"
    path = tmp_path / "legacy.sqlite"
    _final_ownership_database(
        path,
        source_ids=source_ids,
        knowledge_ids=knowledge_ids,
        project_ids=project_ids,
        task_id=task_id,
    )
    plan = build_migration_plan(path)
    _configure_final_batch(monkeypatch, plan)
    monkeypatch.setattr(project_migration, "FINAL_OWNERSHIP_ASSIGNMENTS_SHA256", "0" * 64)
    backup = tmp_path / "verified-backup"
    backup.mkdir()
    (backup / "test-manifest.json").write_text("{}", encoding="utf-8")
    try:
        project_migration.apply_approved_final_ownership_batch(
            path,
            expected_source_sha256=plan["sourceSha256"],
            expected_manifest_sha256=plan["manifestSha256"],
            rollback_manifest_path=tmp_path / "rollback.json",
            verified_backup_set=backup,
        )
    except RuntimeError as error:
        assert "assignment split mismatch" in str(error)
    else:
        raise AssertionError("assignment drift must fail closed")
    with sqlite3.connect(path) as db:
        assert db.execute(
            "SELECT count(*) FROM audit_log WHERE json_extract(data_json,'$.batchKey')=?",
            (project_migration.FINAL_OWNERSHIP_BATCH_KEY,),
        ).fetchone()[0] == 0
    assert not (tmp_path / "rollback.json").exists()

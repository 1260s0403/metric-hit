from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from .database import read_only_database, sha256_file
from .project_scope import DEFAULT_PROJECT_ID, YADRO_CONTROL_PLANE_PROJECT_ID


PLAN_SCHEMA_VERSION = 1
OWNERSHIP_BATCH_VERSION = 1
OWNERSHIP_BATCH_KEY = "approved-project-ownership-2026-08-22-v1"
DECISION_OWNERSHIP_BATCH_KEY = "approved-decision-ownership-2026-08-22-v2"
DECISION_OWNERSHIP_TARGET_IDS_SHA256 = "a1cde640339df73dc41a44672d3df1e263e231f5acbc50aa4abb1f9a3cbf59fe"
DECISION_OWNERSHIP_SPECIAL_ID = "eef8ad32-e84d-45ea-ab3e-cbb53695c268"
DECISION_OWNERSHIP_SPECIAL_INVALID_PROJECT_ID = "canonical_lowercase_uuid_v4"
DECISION_OWNERSHIP_METRICHIT_IDS = frozenset({
    "2ee09a09-26f1-49b5-a015-dc4414196b68",
    "50c17c61-948f-41c0-a2be-af68fa1c8a37",
    "8b8dd140-c03a-42f7-a7c0-a964cb92de24",
    "944424ed-f5fb-40af-a7c2-82a5f5e978f0",
    "bc74082f-f78f-46ad-accb-cc8336f512d2",
    "c32a89d3-b34d-4970-a4c3-76e23514ec1f",
    "d912991a-53bf-476e-a2c2-f09c6c5f7f08",
})
DECISION_OWNERSHIP_METRICHIT_KEYS = {
    "2ee09a09-26f1-49b5-a015-dc4414196b68": "content.editorial_directness_policy",
    "50c17c61-948f-41c0-a2be-af68fa1c8a37": "editorial.longform_separate_workstream",
    "8b8dd140-c03a-42f7-a7c0-a964cb92de24": "editorial.mvp_speed_and_scalability_policy",
    "944424ed-f5fb-40af-a7c2-82a5f5e978f0": "editorial.mvp_speed_and_scalability_policy",
    "bc74082f-f78f-46ad-accb-cc8336f512d2": "operations.marketing_skills_evaluation_and_installation",
    "c32a89d3-b34d-4970-a4c3-76e23514ec1f": "naming.landing_vs_account",
    "d912991a-53bf-476e-a2c2-f09c6c5f7f08": "product.landing_development_integration",
}
CLASS_CORE = "core"
CLASS_PROJECT = "managed_project"
CLASS_UNRESOLVED = "unresolved"
SYSTEM_TABLES = {"schema_migrations"}
RELATION_COLUMNS = {
    "source_id",
    "document_id",
    "candidate_id",
    "existing_memory_item_id",
    "target_memory_item_id",
    "entity_id",
}

APPROVED_OWNERSHIP_ASSIGNMENTS = {
    DEFAULT_PROJECT_ID: {
        ("memory_candidates", "editorial_rule"): 10,
        ("memory_candidates", "commercial_terms"): 3,
        ("memory_candidates", "official_channel"): 2,
        ("memory_candidates", "official_resource"): 2,
        ("memory_candidates", "product_fact"): 6,
        ("memory_candidates", "publication_state"): 6,
        ("decisions", "editorial_policy"): 1,
        ("tasks", "analytics_implementation"): 1,
    },
    YADRO_CONTROL_PLANE_PROJECT_ID: {
        ("memory_candidates", "ai_policy"): 4,
    },
}


def _metadata(value: object) -> dict[str, Any]:
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except (ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _signal(project_id: str, projects: dict[str, dict[str, Any]]) -> tuple[str, str | None, str]:
    project = projects.get(project_id)
    if not project:
        return CLASS_UNRESOLVED, None, "unknown_project_link"
    role = project["role"]
    if role == "control_plane":
        return CLASS_CORE, None, "explicit_control_plane_link"
    if role == "managed_project":
        return CLASS_PROJECT, project_id, "explicit_managed_project_link"
    if role == "subproject":
        parent = project.get("parent")
        parent_project = projects.get(parent)
        if not parent_project or parent_project["role"] != "managed_project":
            return CLASS_UNRESOLVED, None, "invalid_subproject_parent"
        return CLASS_PROJECT, parent, "explicit_subproject_link"
    return CLASS_UNRESOLVED, None, "unknown_project_role"


def _classification(signals: list[tuple[str, str | None, str]]) -> tuple[str, str | None, list[str]]:
    resolved = {(kind, project_id) for kind, project_id, _ in signals if kind != CLASS_UNRESOLVED}
    unresolved_reasons = {reason for kind, _, reason in signals if kind == CLASS_UNRESOLVED}
    reasons = sorted({reason for _, _, reason in signals})
    if unresolved_reasons or len(resolved) > 1:
        if len(resolved) > 1:
            reasons.append("conflicting_project_links")
        return CLASS_UNRESOLVED, None, sorted(set(reasons))
    if len(resolved) == 1:
        kind, project_id = next(iter(resolved))
        return kind, project_id, reasons
    return CLASS_UNRESOLVED, None, ["legacy_unscoped"]


def build_migration_plan(database_path: Path) -> dict[str, Any]:
    source_path = database_path.resolve()
    source_hash_before = sha256_file(source_path)
    with read_only_database(source_path) as connection:
        tables = [
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        rows: list[dict[str, Any]] = []
        projects: dict[str, dict[str, Any]] = {}
        for table in tables:
            columns = [row["name"] for row in connection.execute(f'PRAGMA table_info("{table}")')]
            stable_column = "id" if "id" in columns else "version" if "version" in columns else columns[0]
            selected = [stable_column]
            for name in ("type", "data_json", *sorted(RELATION_COLUMNS)):
                if name in columns and name not in selected:
                    selected.append(name)
            query = ",".join(f'"{name}"' for name in selected)
            for row in connection.execute(f'SELECT {query} FROM "{table}" ORDER BY "{stable_column}"'):
                item = {name: row[name] for name in selected}
                record = {
                    "table": table,
                    "entityType": str(item.get("type") or table),
                    "id": str(item[stable_column]),
                    "metadata": _metadata(item.get("data_json")),
                    "relations": {name: str(item[name]) for name in RELATION_COLUMNS if item.get(name)},
                }
                rows.append(record)
                if table == "documents" and item.get("type") == "project":
                    metadata = record["metadata"]
                    projects[record["id"]] = {
                        "role": metadata.get("scope_type"),
                        "parent": metadata.get("parent_project_id"),
                    }

    known_roles = {
        YADRO_CONTROL_PLANE_PROJECT_ID: "control_plane",
        DEFAULT_PROJECT_ID: "managed_project",
    }
    for project_id, role in known_roles.items():
        # These stable roles are the existing system contract. Legacy project
        # rows may predate the structured scope_type field.
        projects[project_id] = {"role": role, "parent": None}

    by_id: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        by_id.setdefault(row["id"], []).append(index)

    ownership_events: dict[tuple[str, str], list[str]] = {}
    metadata_corrections: dict[tuple[str, str, str], set[str]] = {}
    for row in rows:
        metadata = row["metadata"]
        if row["table"] == "audit_log" and row["entityType"] in {
            "project_scope_assignment", "project_scope_metadata_correction",
        }:
            table = metadata.get("table")
            entity_id = metadata.get("entityId")
            project_id = metadata.get("project_id")
            if isinstance(table, str) and isinstance(entity_id, str) and isinstance(project_id, str):
                ownership_events.setdefault((table, entity_id), []).append(project_id)
            correction = metadata.get("correction")
            if row["entityType"] == "project_scope_metadata_correction" and isinstance(correction, dict):
                field = correction.get("field")
                invalid_value = correction.get("invalidValue")
                if all(isinstance(value, str) for value in (table, entity_id, field, invalid_value)):
                    metadata_corrections.setdefault((table, entity_id, field), set()).add(invalid_value)

    results: list[tuple[str, str | None, list[str]]] = []
    for row in rows:
        signals: list[tuple[str, str | None, str]] = []
        if row["table"] in SYSTEM_TABLES:
            signals.append((CLASS_CORE, None, "core_system_table"))
        if row["table"] == "documents" and row["entityType"] == "project":
            signals.append(_signal(row["id"], projects))
        metadata = row["metadata"]
        if metadata.get("project_id") and str(metadata["project_id"]) not in metadata_corrections.get(
            (row["table"], row["id"], "project_id"), set()
        ):
            signals.append(_signal(str(metadata["project_id"]), projects))
        if metadata.get("subproject_id"):
            signals.append(_signal(str(metadata["subproject_id"]), projects))
        for project_id in ownership_events.get((row["table"], row["id"]), []):
            signals.append(_signal(project_id, projects))
        results.append(_classification(signals))

    # Explicit foreign-key/entity relationships may inherit ownership. Iterate to
    # a fixed point, but never infer ownership from titles or content.
    for _ in range(len(rows) + 1):
        changed = False
        next_results = list(results)
        for index, row in enumerate(rows):
            signals: list[tuple[str, str | None, str]] = []
            current = results[index]
            if current[0] != CLASS_UNRESOLVED or current[2] != ["legacy_unscoped"]:
                signals.append((current[0], current[1], current[2][0]))
            for column, target_id in sorted(row["relations"].items()):
                for target_index in by_id.get(target_id, []):
                    target = results[target_index]
                    if target[0] != CLASS_UNRESOLVED:
                        signals.append((target[0], target[1], f"explicit_relation:{column}"))
            candidate = _classification(signals)
            if candidate != current:
                next_results[index] = candidate
                changed = True
        results = next_results
        if not changed:
            break

    records = []
    for row, (classification, project_id, reasons) in zip(rows, results, strict=True):
        record = {
            "table": row["table"],
            "entityType": row["entityType"],
            "id": row["id"],
            "classification": classification,
            "reasons": reasons,
        }
        if project_id:
            record["projectId"] = project_id
        records.append(record)
    records.sort(key=lambda item: (item["table"], item["entityType"], item["id"]))
    counts = Counter(item["classification"] for item in records)
    unresolved = Counter(reason for item in records if item["classification"] == CLASS_UNRESOLVED for reason in item["reasons"])
    by_entity = Counter((item["table"], item["entityType"], item["classification"]) for item in records)
    unresolved_by_entity = Counter(
        (item["table"], item["entityType"], reason)
        for item in records
        if item["classification"] == CLASS_UNRESOLVED
        for reason in item["reasons"]
    )
    payload = {
        "schemaVersion": PLAN_SCHEMA_VERSION,
        "sourceSha256": source_hash_before,
        "readyToMigrate": counts[CLASS_UNRESOLVED] == 0,
        "counts": {key: counts[key] for key in (CLASS_CORE, CLASS_PROJECT, CLASS_UNRESOLVED)},
        "unresolvedCategories": dict(sorted(unresolved.items())),
        "countsByEntity": [
            {"table": table, "entityType": entity_type, "classification": classification, "count": count}
            for (table, entity_type, classification), count in sorted(by_entity.items())
        ],
        "unresolvedByEntity": [
            {"table": table, "entityType": entity_type, "category": category, "count": count}
            for (table, entity_type, category), count in sorted(unresolved_by_entity.items())
        ],
        "records": records,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["manifestSha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if sha256_file(source_path) != source_hash_before:
        raise RuntimeError("source database changed during read-only planning")
    return payload


def migration_plan_summary(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": plan["schemaVersion"],
        "sourceSha256": plan["sourceSha256"],
        "manifestSha256": plan["manifestSha256"],
        "readyToMigrate": plan["readyToMigrate"],
        "counts": plan["counts"],
        "unresolvedCategories": plan["unresolvedCategories"],
        "countsByEntity": plan["countsByEntity"],
        "unresolvedByEntity": plan["unresolvedByEntity"],
    }


def _audit_id(table: str, entity_id: str, project_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"metrichit:{OWNERSHIP_BATCH_KEY}:{table}:{entity_id}:{project_id}"))


def _decision_audit_id(entity_id: str, project_id: str) -> str:
    return str(uuid5(
        NAMESPACE_URL,
        f"metrichit:{DECISION_OWNERSHIP_BATCH_KEY}:memory_candidates:{entity_id}:{project_id}",
    ))


def _approved_targets(plan: dict[str, Any]) -> list[dict[str, str]]:
    records = {
        (record["table"], record["entityType"]): []
        for record in plan["records"]
    }
    for record in plan["records"]:
        key = (record["table"], record["entityType"])
        if record["classification"] == CLASS_UNRESOLVED and record["reasons"] == ["legacy_unscoped"]:
            records.setdefault(key, []).append(record["id"])
    targets: list[dict[str, str]] = []
    for project_id, selectors in APPROVED_OWNERSHIP_ASSIGNMENTS.items():
        for (table, entity_type), expected_count in selectors.items():
            ids = sorted(records.get((table, entity_type), []))
            if len(ids) != expected_count:
                raise RuntimeError(
                    f"approved selector mismatch for {table}/{entity_type}: "
                    f"expected {expected_count}, found {len(ids)}"
                )
            targets.extend(
                {"table": table, "entityType": entity_type, "id": entity_id, "projectId": project_id}
                for entity_id in ids
            )
    if len(targets) != 35:
        raise RuntimeError(f"approved assignment total mismatch: expected 35, found {len(targets)}")
    return sorted(targets, key=lambda item: (item["table"], item["entityType"], item["id"]))


def _completed_batch(connection: sqlite3.Connection) -> list[dict[str, str]] | None:
    rows = connection.execute(
        "SELECT id,data_json FROM audit_log WHERE json_extract(data_json,'$.batchKey')=? ORDER BY id",
        (OWNERSHIP_BATCH_KEY,),
    ).fetchall()
    if not rows:
        return None
    if len(rows) != 35:
        raise RuntimeError(f"partial ownership batch detected: expected 35 audit rows, found {len(rows)}")
    targets: list[dict[str, str]] = []
    allowed_tables = {table for selectors in APPROVED_OWNERSHIP_ASSIGNMENTS.values() for table, _ in selectors}
    for row in rows:
        data = json.loads(row["data_json"])
        table, entity_id, project_id = data["table"], data["entityId"], data["project_id"]
        if table not in allowed_tables or row["id"] != _audit_id(table, entity_id, project_id):
            raise RuntimeError("ownership batch contains an unexpected or invalid audit row")
        target = connection.execute(f'SELECT type FROM "{table}" WHERE id=?', (entity_id,)).fetchone()
        if target is None:
            raise RuntimeError(f"ownership batch audit does not match {table}/{entity_id}")
        targets.append({"table": table, "entityType": target["type"], "id": entity_id, "projectId": project_id})
    actual = Counter((item["projectId"], item["table"], item["entityType"]) for item in targets)
    expected = Counter({
        (project_id, table, entity_type): count
        for project_id, selectors in APPROVED_OWNERSHIP_ASSIGNMENTS.items()
        for (table, entity_type), count in selectors.items()
    })
    if actual != expected:
        raise RuntimeError("completed ownership batch does not match the approved 31/4 selectors")
    return sorted(targets, key=lambda item: (item["table"], item["entityType"], item["id"]))


def apply_approved_ownership_batch(
    database_path: Path,
    *,
    expected_source_sha256: str,
    expected_manifest_sha256: str,
    rollback_manifest_path: Path,
    verified_backup_set: Path,
) -> dict[str, Any]:
    """Apply the owner-approved 31/4 legacy ownership batch exactly once."""
    source_path = database_path.resolve()
    backup_path = verified_backup_set.resolve()
    if not backup_path.is_dir() or len(list(backup_path.glob("*-manifest.json"))) != 1:
        raise RuntimeError("verified backup set is missing or incomplete")

    connection = sqlite3.connect(source_path)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        completed = _completed_batch(connection)
        if completed is not None:
            return {
                "batchKey": OWNERSHIP_BATCH_KEY,
                "applied": 0,
                "alreadyApplied": 35,
                "auditRows": 35,
                "sourceSha256": sha256_file(source_path),
            }
    finally:
        connection.close()

    plan = build_migration_plan(source_path)
    if plan["sourceSha256"] != expected_source_sha256:
        raise RuntimeError("source SHA-256 guard mismatch")
    if plan["manifestSha256"] != expected_manifest_sha256:
        raise RuntimeError("migration plan manifest guard mismatch")
    targets = _approved_targets(plan)

    rollback_path = rollback_manifest_path.resolve()
    rollback_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(source_path)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        if sha256_file(source_path) != expected_source_sha256:
            raise RuntimeError("source changed before ownership transaction")
        rollback_rows: list[dict[str, Any]] = []
        for target in targets:
            row = connection.execute(
                f'SELECT type,data_json,source_id,author,updated_at,version FROM "{target["table"]}" WHERE id=?',
                (target["id"],),
            ).fetchone()
            if row is None or row["type"] != target["entityType"]:
                raise RuntimeError(f"target changed before apply: {target['table']}/{target['id']}")
            metadata = _metadata(row["data_json"])
            if metadata.get("project_id") or metadata.get("subproject_id"):
                raise RuntimeError(f"target is no longer legacy-unscoped: {target['table']}/{target['id']}")
            rollback_rows.append({
                **target,
                "oldDataJson": row["data_json"],
                "oldUpdatedAt": row["updated_at"],
                "oldVersion": row["version"],
                "auditId": _audit_id(target["table"], target["id"], target["projectId"]),
            })

        rollback_document = {
            "schemaVersion": OWNERSHIP_BATCH_VERSION,
            "batchKey": OWNERSHIP_BATCH_KEY,
            "sourceSha256": expected_source_sha256,
            "planManifestSha256": expected_manifest_sha256,
            "verifiedBackupSet": str(backup_path),
            "rows": rollback_rows,
            "restoreMethod": "restore the verified full backup set; audit_log is append-only",
        }
        rollback_json = json.dumps(rollback_document, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        if rollback_path.exists():
            if rollback_path.read_text(encoding="utf-8-sig") != rollback_json:
                raise RuntimeError("existing rollback manifest does not match the approved batch")
        else:
            with rollback_path.open("x", encoding="utf-8") as destination:
                destination.write(rollback_json)

        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        for target, old in zip(targets, rollback_rows, strict=True):
            audit_data = {
                "batchKey": OWNERSHIP_BATCH_KEY,
                "table": target["table"],
                "entityId": target["id"],
                "project_id": target["projectId"],
                "old": {"project_id": None},
                "new": {"project_id": target["projectId"]},
            }
            connection.execute(
                "INSERT INTO audit_log (id,type,title,data_json,source_id,author,created_at,updated_at,"
                "access_level,version,entity_type,entity_id,action) "
                "VALUES (?,?,?,?,?,?,?,?,'restricted',1,?,?, 'update')",
                (
                    old["auditId"], "project_scope_assignment", "Project ownership assigned",
                    json.dumps(audit_data, ensure_ascii=False, sort_keys=True), None,
                    "owner", now, now, target["entityType"], target["id"],
                ),
            )
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("SQLite integrity_check failed")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    after = build_migration_plan(source_path)
    unresolved_before = {
        (record["table"], record["id"])
        for record in plan["records"]
        if record["classification"] == CLASS_UNRESOLVED
    }
    selected = {(target["table"], target["id"]) for target in targets}
    unresolved_after = {
        (record["table"], record["id"])
        for record in after["records"]
        if record["classification"] == CLASS_UNRESOLVED
    }
    if unresolved_after != unresolved_before - selected:
        raise RuntimeError("post-apply unresolved set differs outside approved targets")
    expected_counts = {
        CLASS_CORE: plan["counts"][CLASS_CORE] + 8,
        CLASS_PROJECT: plan["counts"][CLASS_PROJECT] + 62,
        CLASS_UNRESOLVED: plan["counts"][CLASS_UNRESOLVED] - 35,
    }
    if after["counts"] != expected_counts:
        raise RuntimeError(f"post-apply totals mismatch: {after['counts']}")
    return {
        "batchKey": OWNERSHIP_BATCH_KEY,
        "applied": 35,
        "alreadyApplied": 0,
        "auditRows": 35,
        "rollbackManifest": str(rollback_path),
        "sourceSha256Before": expected_source_sha256,
        "sourceSha256After": after["sourceSha256"],
        "planManifestSha256After": after["manifestSha256"],
        "counts": after["counts"],
        "unresolvedCategories": after["unresolvedCategories"],
    }


def _decision_target_ids_sha256(entity_ids: list[str]) -> str:
    payload = "\n".join(sorted(entity_ids)) + "\n"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _approved_decision_targets(plan: dict[str, Any]) -> list[dict[str, str]]:
    records = [
        record for record in plan["records"]
        if record["table"] == "memory_candidates"
        and record["entityType"] == "decision"
        and record["classification"] == CLASS_UNRESOLVED
    ]
    entity_ids = [record["id"] for record in records]
    if len(entity_ids) != 62:
        raise RuntimeError(f"approved decision selector mismatch: expected 62, found {len(entity_ids)}")
    if _decision_target_ids_sha256(entity_ids) != DECISION_OWNERSHIP_TARGET_IDS_SHA256:
        raise RuntimeError("approved decision selector ID set mismatch")
    by_id = {record["id"]: record for record in records}
    special = by_id.get(DECISION_OWNERSHIP_SPECIAL_ID)
    if special is None or special["reasons"] != ["unknown_project_link"]:
        raise RuntimeError("special project-storage decision no longer has the approved invalid-link state")
    ordinary = [record for record in records if record["id"] != DECISION_OWNERSHIP_SPECIAL_ID]
    if any(record["reasons"] != ["legacy_unscoped"] for record in ordinary):
        raise RuntimeError("ordinary approved decision target is no longer legacy-unscoped")
    if not DECISION_OWNERSHIP_METRICHIT_IDS < set(entity_ids):
        raise RuntimeError("approved MetricHit decision ID set is incomplete")
    targets = []
    for record in records:
        project_id = (
            DEFAULT_PROJECT_ID
            if record["id"] in DECISION_OWNERSHIP_METRICHIT_IDS
            else YADRO_CONTROL_PLANE_PROJECT_ID
        )
        targets.append({
            "table": "memory_candidates",
            "entityType": "decision",
            "id": record["id"],
            "projectId": project_id,
        })
    actual = Counter(target["projectId"] for target in targets)
    if actual != Counter({YADRO_CONTROL_PLANE_PROJECT_ID: 55, DEFAULT_PROJECT_ID: 7}):
        raise RuntimeError("approved decision split does not match 54 core / 7 MetricHit / 1 special core")
    return sorted(targets, key=lambda item: item["id"])


def _completed_decision_batch(connection: sqlite3.Connection) -> list[dict[str, str]] | None:
    rows = connection.execute(
        "SELECT id,type,data_json,entity_type,entity_id FROM audit_log "
        "WHERE json_extract(data_json,'$.batchKey')=? ORDER BY id",
        (DECISION_OWNERSHIP_BATCH_KEY,),
    ).fetchall()
    if not rows:
        return None
    if len(rows) != 62:
        raise RuntimeError(f"partial decision ownership batch detected: expected 62 audit rows, found {len(rows)}")
    targets: list[dict[str, str]] = []
    for row in rows:
        data = json.loads(row["data_json"])
        entity_id = data.get("entityId")
        project_id = data.get("project_id")
        if not isinstance(entity_id, str) or not isinstance(project_id, str):
            raise RuntimeError("decision ownership batch contains invalid audit metadata")
        expected_type = (
            "project_scope_metadata_correction"
            if entity_id == DECISION_OWNERSHIP_SPECIAL_ID
            else "project_scope_assignment"
        )
        if (
            data.get("table") != "memory_candidates"
            or row["type"] != expected_type
            or row["entity_type"] != "decision"
            or row["entity_id"] != entity_id
            or row["id"] != _decision_audit_id(entity_id, project_id)
        ):
            raise RuntimeError("decision ownership batch contains an unexpected or invalid audit row")
        if entity_id == DECISION_OWNERSHIP_SPECIAL_ID and data.get("correction") != {
            "field": "project_id",
            "invalidValue": DECISION_OWNERSHIP_SPECIAL_INVALID_PROJECT_ID,
            "reason": "storage contract descriptor was not an ownership relation",
        }:
            raise RuntimeError("special decision correction audit is incomplete")
        target = connection.execute(
            "SELECT type FROM memory_candidates WHERE id=?", (entity_id,),
        ).fetchone()
        if target is None or target["type"] != "decision":
            raise RuntimeError(f"decision ownership audit does not match memory_candidates/{entity_id}")
        targets.append({
            "table": "memory_candidates", "entityType": "decision",
            "id": entity_id, "projectId": project_id,
        })
    entity_ids = [target["id"] for target in targets]
    if _decision_target_ids_sha256(entity_ids) != DECISION_OWNERSHIP_TARGET_IDS_SHA256:
        raise RuntimeError("completed decision ownership batch target set mismatch")
    actual = Counter(target["projectId"] for target in targets)
    if actual != Counter({YADRO_CONTROL_PLANE_PROJECT_ID: 55, DEFAULT_PROJECT_ID: 7}):
        raise RuntimeError("completed decision ownership batch split mismatch")
    return sorted(targets, key=lambda item: item["id"])


def apply_approved_decision_ownership_batch(
    database_path: Path,
    *,
    expected_source_sha256: str,
    expected_manifest_sha256: str,
    rollback_manifest_path: Path,
    verified_backup_set: Path,
) -> dict[str, Any]:
    """Apply the owner-approved 54 core / 7 MetricHit / 1 corrected core decision batch."""
    source_path = database_path.resolve()
    backup_path = verified_backup_set.resolve()
    if not backup_path.is_dir() or len(list(backup_path.glob("*-manifest.json"))) != 1:
        raise RuntimeError("verified backup set is missing or incomplete")

    connection = sqlite3.connect(source_path)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        completed = _completed_decision_batch(connection)
        if completed is not None:
            return {
                "batchKey": DECISION_OWNERSHIP_BATCH_KEY,
                "applied": 0,
                "alreadyApplied": 62,
                "auditRows": 62,
                "sourceSha256": sha256_file(source_path),
            }
    finally:
        connection.close()

    plan = build_migration_plan(source_path)
    if plan["sourceSha256"] != expected_source_sha256:
        raise RuntimeError("source SHA-256 guard mismatch")
    if plan["manifestSha256"] != expected_manifest_sha256:
        raise RuntimeError("migration plan manifest guard mismatch")
    targets = _approved_decision_targets(plan)
    unresolved_before = {
        (record["table"], record["id"])
        for record in plan["records"]
        if record["classification"] == CLASS_UNRESOLVED
    }

    rollback_path = rollback_manifest_path.resolve()
    rollback_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(source_path)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        if sha256_file(source_path) != expected_source_sha256:
            raise RuntimeError("source changed before decision ownership transaction")
        rollback_rows: list[dict[str, Any]] = []
        for target in targets:
            row = connection.execute(
                "SELECT type,semantic_key,title,data_json,source_id,author,updated_at,version "
                "FROM memory_candidates WHERE id=?",
                (target["id"],),
            ).fetchone()
            if row is None or row["type"] != "decision":
                raise RuntimeError(f"target changed before apply: memory_candidates/{target['id']}")
            metadata = _metadata(row["data_json"])
            if target["id"] == DECISION_OWNERSHIP_SPECIAL_ID:
                if (
                    row["semantic_key"] != "architecture.project_storage_foundation"
                    or metadata.get("project_id") != DECISION_OWNERSHIP_SPECIAL_INVALID_PROJECT_ID
                    or metadata.get("subproject_id")
                ):
                    raise RuntimeError("special project-storage decision metadata changed before apply")
            else:
                if metadata.get("project_id") or metadata.get("subproject_id"):
                    raise RuntimeError(f"target is no longer legacy-unscoped: memory_candidates/{target['id']}")
                expected_key = DECISION_OWNERSHIP_METRICHIT_KEYS.get(target["id"])
                if expected_key is not None and row["semantic_key"] != expected_key:
                    raise RuntimeError(f"MetricHit decision semantic key changed: {target['id']}")
            rollback_rows.append({
                **target,
                "semanticKey": row["semantic_key"],
                "title": row["title"],
                "oldDataJson": row["data_json"],
                "oldUpdatedAt": row["updated_at"],
                "oldVersion": row["version"],
                "auditId": _decision_audit_id(target["id"], target["projectId"]),
            })

        rollback_document = {
            "schemaVersion": OWNERSHIP_BATCH_VERSION,
            "batchKey": DECISION_OWNERSHIP_BATCH_KEY,
            "approvedSplit": {"ordinaryCore": 54, "metricHit": 7, "specialCore": 1},
            "targetIdsSha256": DECISION_OWNERSHIP_TARGET_IDS_SHA256,
            "sourceSha256": expected_source_sha256,
            "planManifestSha256": expected_manifest_sha256,
            "verifiedBackupSet": str(backup_path),
            "rows": rollback_rows,
            "restoreMethod": "restore the verified full backup set; audit_log is append-only",
        }
        rollback_json = json.dumps(rollback_document, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        if rollback_path.exists():
            if rollback_path.read_text(encoding="utf-8-sig") != rollback_json:
                raise RuntimeError("existing rollback manifest does not match the approved decision batch")
        else:
            with rollback_path.open("x", encoding="utf-8") as destination:
                destination.write(rollback_json)

        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        for target, old in zip(targets, rollback_rows, strict=True):
            special = target["id"] == DECISION_OWNERSHIP_SPECIAL_ID
            audit_data: dict[str, Any] = {
                "batchKey": DECISION_OWNERSHIP_BATCH_KEY,
                "table": "memory_candidates",
                "entityId": target["id"],
                "project_id": target["projectId"],
                "old": {"project_id": DECISION_OWNERSHIP_SPECIAL_INVALID_PROJECT_ID if special else None},
                "new": {"project_id": target["projectId"]},
            }
            if special:
                audit_data["correction"] = {
                    "field": "project_id",
                    "invalidValue": DECISION_OWNERSHIP_SPECIAL_INVALID_PROJECT_ID,
                    "reason": "storage contract descriptor was not an ownership relation",
                }
            connection.execute(
                "INSERT INTO audit_log (id,type,title,data_json,source_id,author,created_at,updated_at,"
                "access_level,version,entity_type,entity_id,action) "
                "VALUES (?,?,?,?,?,?,?,?,'restricted',1,'decision',?,'update')",
                (
                    old["auditId"],
                    "project_scope_metadata_correction" if special else "project_scope_assignment",
                    "Project ownership metadata corrected" if special else "Project ownership assigned",
                    json.dumps(audit_data, ensure_ascii=False, sort_keys=True),
                    None, "owner", now, now, target["id"],
                ),
            )
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("SQLite integrity_check failed")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    after = build_migration_plan(source_path)
    selected = {(target["table"], target["id"]) for target in targets}
    unresolved_after = {
        (record["table"], record["id"])
        for record in after["records"]
        if record["classification"] == CLASS_UNRESOLVED
    }
    if unresolved_after != unresolved_before - selected:
        raise RuntimeError("post-apply unresolved set differs outside approved decision targets")
    expected_counts = {
        CLASS_CORE: plan["counts"][CLASS_CORE] + 110,
        CLASS_PROJECT: plan["counts"][CLASS_PROJECT] + 14,
        CLASS_UNRESOLVED: plan["counts"][CLASS_UNRESOLVED] - 62,
    }
    if after["counts"] != expected_counts:
        raise RuntimeError(f"post-apply decision ownership totals mismatch: {after['counts']}")
    connection = sqlite3.connect(source_path)
    connection.row_factory = sqlite3.Row
    try:
        for old in rollback_rows:
            current = connection.execute(
                "SELECT data_json,updated_at,version FROM memory_candidates WHERE id=?", (old["id"],),
            ).fetchone()
            if current is None or dict(current) != {
                "data_json": old["oldDataJson"],
                "updated_at": old["oldUpdatedAt"],
                "version": old["oldVersion"],
            }:
                raise RuntimeError(f"approved decision content changed: {old['id']}")
    finally:
        connection.close()
    return {
        "batchKey": DECISION_OWNERSHIP_BATCH_KEY,
        "applied": 62,
        "alreadyApplied": 0,
        "auditRows": 62,
        "approvedSplit": {"ordinaryCore": 54, "metricHit": 7, "specialCore": 1},
        "targetIdsSha256": DECISION_OWNERSHIP_TARGET_IDS_SHA256,
        "unchangedNonTargetUnresolved": len(unresolved_after),
        "rollbackManifest": str(rollback_path),
        "sourceSha256Before": expected_source_sha256,
        "sourceSha256After": after["sourceSha256"],
        "planManifestSha256After": after["manifestSha256"],
        "counts": after["counts"],
        "unresolvedCategories": after["unresolvedCategories"],
    }

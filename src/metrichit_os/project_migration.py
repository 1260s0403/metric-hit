from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from .config import MEMORY_MIGRATIONS
from .database import read_only_database, sha256_file
from .editorial_domain import (
    EDITORIAL_SCHEMA_OBJECTS,
    EditorialDomainError,
    check_editorial_domain,
)
from .project_scope import DEFAULT_PROJECT_ID, YADRO_CONTROL_PLANE_PROJECT_ID
from .project_storage import ProjectStorage, STORAGE_FORMAT_VERSION


PLAN_SCHEMA_VERSION = 1
MATERIALIZATION_SCHEMA_VERSION = 1
MATERIALIZATION_KEY = "metrichit-managed-project-materialization-2026-08-26-v1"
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
FINAL_OWNERSHIP_BATCH_KEY = "approved-final-project-ownership-2026-08-26-v3"
FINAL_OWNERSHIP_CORRECTION_BATCH_KEY = "approved-final-project-ownership-correction-2026-08-26-v3.1"
FINAL_OWNERSHIP_TARGET_IDS_SHA256 = "9acce728383c9066f486a38e4aea791f64043651b0053cc28f5545258abe46ab"
FINAL_OWNERSHIP_ASSIGNMENTS_SHA256 = "f6c4e2e4b36cf4fe742e052b9bb455041612eeec26e52434a0f63e04799f31d8"
FINAL_OWNERSHIP_CORRECTED_ASSIGNMENTS_SHA256 = "7ab5054bc0f4218a3c41e24ad00540b0f298f855896e773954d542e5f378f2f6"
FINAL_OWNERSHIP_SOURCE_IDS_SHA256 = "bf59be16e2e8aaee17df3d760b5a5dd23486d2b0b09b678490dc5683d305e20a"
FINAL_OWNERSHIP_KNOWLEDGE_IDS_SHA256 = "21e99549580797cbfcb4b45fcf542c858284ce9c1c22725e5e2180f8eae42a3f"
FINAL_OWNERSHIP_PROJECT_IDS_SHA256 = "5870af1c7443e0bfc234e57fb685de06ccc35782d56f8e5d99857d128212d48a"
FINAL_OWNERSHIP_STANDALONE_TASK_ID = "1773d5fd-9fd5-4ab9-b568-a59106287845"
FINAL_OWNERSHIP_STRUCTURAL_KNOWLEDGE_ID = "aa28a8f1-2188-49d3-9ec3-c22f8282a49a"
FINAL_OWNERSHIP_CONTROL_KNOWLEDGE_ID = "ea8722c8-73f8-4003-8676-67b406716c82"
FINAL_OWNERSHIP_METRICHIT_SOURCE_IDS = frozenset({
    "4fb09122-805c-4784-a79a-34d884f1cca8",
    "908c2b14-987f-419e-abfa-24165e4d7d4e",
    "9d7eb16f-fcf3-4302-a797-0806924f3dc4",
    "afb285ef-dbd6-482d-a093-8638121ef060",
    "b99c8f36-4e0e-47c8-aa91-0a82ec83554e",
    "bb433168-fda4-4cb6-a68a-483d27991324",
    "bec53592-d2f7-4222-ad41-63921103014d",
    "c7016a42-e293-4f3c-a44e-1fb4739719f3",
    "d70f80b2-a61d-4272-a1e1-16d23b8d4828",
})
FINAL_OWNERSHIP_PROJECT_CORRECTIONS = {
    "1f4ee35b-0415-4d37-8c2e-77566ee50bc6": (
        {
            "field": "scope_type",
            "invalidValue": None,
            "newValue": "subproject",
            "reason": "legacy test project was missing its subproject role",
        },
        {
            "field": "parent_project_id",
            "invalidValue": None,
            "newValue": DEFAULT_PROJECT_ID,
            "reason": "legacy test project was missing its MetricHit parent",
        },
    ),
    "56ed934a-0741-4e16-97fa-e7e8068b4ddb": (
        {
            "field": "parent_project_id",
            "invalidValue": YADRO_CONTROL_PLANE_PROJECT_ID,
            "newValue": DEFAULT_PROJECT_ID,
            "reason": "subprojects belong under the managed MetricHit project, not the control plane",
        },
    ),
    "dbc46e2c-cd45-476b-bce6-d1bae716c063": (
        {
            "field": "parent_project_id",
            "invalidValue": YADRO_CONTROL_PLANE_PROJECT_ID,
            "newValue": DEFAULT_PROJECT_ID,
            "reason": "subprojects belong under the managed MetricHit project, not the control plane",
        },
    ),
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
SCOPE_COLUMNS = {"scope_id", "requested_scope_id", "resolved_scope_id"}
METADATA_RELATION_FIELDS = {"knowledge_entry_id"}
TARGET_METADATA_RELATION_FIELDS = {
    "knowledge_entry_id", "parent_project_id", "project_id", "subproject_id",
}
TARGET_METADATA_TABLES = {"project_storage_metadata", "project_migration_manifest"}


def _migration_schema_object_names(path: Path) -> frozenset[str]:
    with sqlite3.connect(":memory:") as connection:
        connection.executescript(path.read_text(encoding="utf-8"))
        return frozenset(
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%' AND sql IS NOT NULL"
            )
        )


STRUCTURED_MEMORY_SCHEMA_OBJECTS = _migration_schema_object_names(
    MEMORY_MIGRATIONS / "011_structured_memory.sql"
)

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


def _scope_signal(
    scope_id: str,
    scopes: dict[str, dict[str, str | None]],
) -> tuple[str, str | None, str]:
    visited: set[str] = set()
    current = scope_id
    while current and current not in visited:
        visited.add(current)
        if current == "scope:core":
            return CLASS_CORE, None, "explicit_core_scope"
        if current == "scope:project:metrichit":
            return CLASS_PROJECT, DEFAULT_PROJECT_ID, "explicit_metrichit_scope"
        scope = scopes.get(current)
        if not scope:
            return CLASS_UNRESOLVED, None, "unknown_scope_link"
        current = scope.get("parent")
    return CLASS_UNRESOLVED, None, "invalid_scope_hierarchy"


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
        scopes: dict[str, dict[str, str | None]] = {}
        for table in tables:
            columns = [row["name"] for row in connection.execute(f'PRAGMA table_info("{table}")')]
            stable_column = "id" if "id" in columns else "version" if "version" in columns else columns[0]
            selected = [stable_column]
            for name in ("type", "data_json", "scope_kind", "parent_scope_id", *sorted(RELATION_COLUMNS | SCOPE_COLUMNS)):
                if name in columns and name not in selected:
                    selected.append(name)
            query = ",".join(f'"{name}"' for name in selected)
            for row in connection.execute(f'SELECT {query} FROM "{table}" ORDER BY "{stable_column}"'):
                item = {name: row[name] for name in selected}
                metadata = _metadata(item.get("data_json"))
                relations = {name: str(item[name]) for name in RELATION_COLUMNS | SCOPE_COLUMNS if item.get(name)}
                relations.update({
                    f"data_json.{name}": str(metadata[name])
                    for name in METADATA_RELATION_FIELDS
                    if metadata.get(name)
                })
                record = {
                    "table": table,
                    "entityType": str(item.get("type") or table),
                    "id": str(item[stable_column]),
                    "metadata": metadata,
                    "relations": relations,
                }
                rows.append(record)
                if table == "documents" and item.get("type") == "project":
                    metadata = record["metadata"]
                    projects[record["id"]] = {
                        "role": metadata.get("scope_type"),
                        "parent": metadata.get("parent_project_id"),
                    }
                if table == "scope_passports":
                    scopes[record["id"]] = {
                        "kind": str(item.get("scope_kind") or ""),
                        "parent": str(item["parent_scope_id"]) if item.get("parent_scope_id") else None,
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

    ownership_events: dict[tuple[str, str], list[tuple[str, str]]] = {}
    invalid_assignment_audit_ids: set[str] = set()
    metadata_corrections: dict[tuple[str, str, str], set[str | None]] = {}
    metadata_overrides: dict[tuple[str, str, str], list[tuple[str | None, str | None]]] = {}
    for row in rows:
        metadata = row["metadata"]
        if row["table"] == "audit_log" and row["entityType"] in {
            "project_scope_assignment", "project_scope_assignment_correction",
            "project_scope_metadata_correction",
        }:
            table = metadata.get("table")
            entity_id = metadata.get("entityId")
            project_id = metadata.get("project_id")
            if isinstance(table, str) and isinstance(entity_id, str) and isinstance(project_id, str):
                ownership_events.setdefault((table, entity_id), []).append((row["id"], project_id))
            correction_items: list[dict[str, Any]] = []
            correction = metadata.get("correction")
            corrections = metadata.get("corrections")
            if isinstance(correction, dict):
                correction_items.append(correction)
            if isinstance(corrections, list):
                correction_items.extend(item for item in corrections if isinstance(item, dict))
            if row["entityType"] == "project_scope_assignment_correction":
                for item in correction_items:
                    invalid_audit_id = item.get("invalidAuditId")
                    if item.get("field") == "project_scope_assignment" and isinstance(invalid_audit_id, str):
                        invalid_assignment_audit_ids.add(invalid_audit_id)
            if row["entityType"] == "project_scope_metadata_correction":
                for item in correction_items:
                    field = item.get("field")
                    invalid_value = item.get("invalidValue")
                    if (
                        isinstance(table, str)
                        and isinstance(entity_id, str)
                        and isinstance(field, str)
                        and (isinstance(invalid_value, str) or invalid_value is None)
                    ):
                        key = (table, entity_id, field)
                        metadata_corrections.setdefault(key, set()).add(invalid_value)
                        if "newValue" in item:
                            new_value = item.get("newValue")
                            if isinstance(new_value, str) or new_value is None:
                                metadata_overrides.setdefault(key, []).append((invalid_value, new_value))

    for project_id, project in projects.items():
        for field, project_key in (("scope_type", "role"), ("parent_project_id", "parent")):
            overrides = metadata_overrides.get(("documents", project_id, field), [])
            applicable = {new for invalid, new in overrides if project[project_key] == invalid}
            if len(applicable) == 1:
                project[project_key] = applicable.pop()

    results: list[tuple[str, str | None, list[str]]] = []
    for row in rows:
        signals: list[tuple[str, str | None, str]] = []
        if row["table"] in SYSTEM_TABLES:
            signals.append((CLASS_CORE, None, "core_system_table"))
        if row["table"] == "documents" and row["entityType"] == "project":
            signals.append(_signal(row["id"], projects))
        metadata = row["metadata"]
        if metadata.get("belongs_to") == "central_core":
            signals.append((CLASS_CORE, None, "explicit_control_plane_metadata"))
        if row["table"] == "scope_passports":
            signals.append(_scope_signal(row["id"], scopes))
        for column in sorted(SCOPE_COLUMNS):
            scope_id = row["relations"].get(column)
            if scope_id:
                signals.append(_scope_signal(scope_id, scopes))
        if row["table"] == "scope_routing_audit" and not any(
            row["relations"].get(column) for column in SCOPE_COLUMNS
        ):
            signals.append((CLASS_CORE, None, "routing_control_plane_record"))
        if metadata.get("project_id") and str(metadata["project_id"]) not in metadata_corrections.get(
            (row["table"], row["id"], "project_id"), set()
        ):
            signals.append(_signal(str(metadata["project_id"]), projects))
        if metadata.get("subproject_id"):
            signals.append(_signal(str(metadata["subproject_id"]), projects))
        for audit_id, project_id in ownership_events.get((row["table"], row["id"]), []):
            if audit_id not in invalid_assignment_audit_ids:
                signals.append(_signal(project_id, projects))
        results.append(_classification(signals))

    # Explicit foreign-key/entity relationships may inherit ownership. Iterate to
    # a fixed point, but never infer ownership from titles or content.
    base_results = list(results)
    for _ in range(len(rows) + 1):
        changed = False
        next_results = list(results)
        for index, row in enumerate(rows):
            relation_signals: list[tuple[str, str | None, str]] = []
            current = results[index]
            base = base_results[index]
            for column, target_id in sorted(row["relations"].items()):
                for target_index in by_id.get(target_id, []):
                    target = results[target_index]
                    if target[0] != CLASS_UNRESOLVED:
                        relation_signals.append((target[0], target[1], f"explicit_relation:{column}"))
            if row["table"] == "memory_candidates" and base[0] != CLASS_UNRESOLVED:
                # An approved memory item is itself the authoritative business
                # assertion. Its provenance source does not override a prior,
                # explicitly confirmed project assignment.
                signals = [(base[0], base[1], reason) for reason in base[2]]
            elif relation_signals and (
                row["table"] in {"tasks", "document_versions", "audit_log"}
                or (row["table"] == "documents" and row["entityType"] != "project")
            ):
                # Derived records inherit their primary source/document/entity.
                # This intentionally supersedes stale embedded project links.
                signals = relation_signals
            else:
                signals = []
                if base[0] != CLASS_UNRESOLVED or base[2] != ["legacy_unscoped"]:
                    signals.extend((base[0], base[1], reason) for reason in base[2])
                signals.extend(relation_signals)
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


def _final_target_ids_sha256(targets: list[dict[str, str]]) -> str:
    payload = "".join(
        f"{target['table']}\t{target['id']}\n"
        for target in sorted(targets, key=lambda item: (item["table"], item["id"]))
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _final_assignments_sha256(targets: list[dict[str, str]]) -> str:
    payload = "".join(
        f"{target['table']}\t{target['id']}\t{target['projectId']}\n"
        for target in sorted(targets, key=lambda item: (item["table"], item["id"]))
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _final_audit_id(table: str, entity_id: str, project_id: str) -> str:
    return str(uuid5(
        NAMESPACE_URL,
        f"metrichit:{FINAL_OWNERSHIP_BATCH_KEY}:{table}:{entity_id}:{project_id}",
    ))


def _final_correction_audit_id() -> str:
    return str(uuid5(
        NAMESPACE_URL,
        f"metrichit:{FINAL_OWNERSHIP_CORRECTION_BATCH_KEY}:documents:"
        f"{FINAL_OWNERSHIP_CONTROL_KNOWLEDGE_ID}:{YADRO_CONTROL_PLANE_PROJECT_ID}",
    ))


def _corrected_final_targets(targets: list[dict[str, str]]) -> list[dict[str, str]]:
    corrected = [
        {
            **target,
            "projectId": (
                YADRO_CONTROL_PLANE_PROJECT_ID
                if target["table"] == "documents" and target["id"] == FINAL_OWNERSHIP_CONTROL_KNOWLEDGE_ID
                else target["projectId"]
            ),
        }
        for target in targets
    ]
    if sum(
        target["table"] == "documents" and target["id"] == FINAL_OWNERSHIP_CONTROL_KNOWLEDGE_ID
        for target in targets
    ) != 1:
        raise RuntimeError("final control-plane knowledge correction target is missing")
    if _final_assignments_sha256(corrected) != FINAL_OWNERSHIP_CORRECTED_ASSIGNMENTS_SHA256:
        raise RuntimeError("corrected final ownership assignment split mismatch")
    if Counter(target["projectId"] for target in corrected) != Counter({
        YADRO_CONTROL_PLANE_PROJECT_ID: 63,
        DEFAULT_PROJECT_ID: 29,
    }):
        raise RuntimeError("corrected final ownership split does not match 63 core / 29 MetricHit")
    return corrected


def _final_unknown_role_project_id() -> str:
    matches = [
        entity_id
        for entity_id, corrections in FINAL_OWNERSHIP_PROJECT_CORRECTIONS.items()
        if any(
            correction["field"] == "scope_type" and correction["invalidValue"] is None
            for correction in corrections
        )
    ]
    if len(matches) != 1:
        raise RuntimeError("final project correction set must contain exactly one missing-role project")
    return matches[0]


def _approved_final_targets(plan: dict[str, Any]) -> list[dict[str, str]]:
    unresolved = [record for record in plan["records"] if record["classification"] == CLASS_UNRESOLVED]
    if len(unresolved) != 348:
        raise RuntimeError(f"final ownership unresolved selector mismatch: expected 348, found {len(unresolved)}")

    source_records = [record for record in unresolved if record["table"] == "sources"]
    if len(source_records) != 71:
        raise RuntimeError(f"final source selector mismatch: expected 71, found {len(source_records)}")
    source_targets = [
        {
            "table": "sources",
            "entityType": record["entityType"],
            "id": record["id"],
            "projectId": (
                DEFAULT_PROJECT_ID
                if record["id"] in FINAL_OWNERSHIP_METRICHIT_SOURCE_IDS
                else YADRO_CONTROL_PLANE_PROJECT_ID
            ),
        }
        for record in source_records
    ]
    if _final_target_ids_sha256(source_targets) != FINAL_OWNERSHIP_SOURCE_IDS_SHA256:
        raise RuntimeError("final source selector ID set mismatch")
    if Counter(record["entityType"] for record in source_records) != Counter({
        "owner_decision": 68,
        "chat_summary_file": 3,
    }):
        raise RuntimeError("final source selector type split mismatch")
    if not FINAL_OWNERSHIP_METRICHIT_SOURCE_IDS < {record["id"] for record in source_records}:
        raise RuntimeError("final MetricHit source ID set is incomplete")

    knowledge_records = [
        record for record in unresolved
        if record["table"] == "documents" and record["entityType"] == "knowledge_entry"
    ]
    knowledge_targets = [
        {
            "table": "documents",
            "entityType": "knowledge_entry",
            "id": record["id"],
            "projectId": DEFAULT_PROJECT_ID,
        }
        for record in knowledge_records
    ]
    if len(knowledge_targets) != 17:
        raise RuntimeError(f"final knowledge selector mismatch: expected 17, found {len(knowledge_targets)}")
    if _final_target_ids_sha256(knowledge_targets) != FINAL_OWNERSHIP_KNOWLEDGE_IDS_SHA256:
        raise RuntimeError("final knowledge selector ID set mismatch")
    knowledge_reasons = Counter(tuple(record["reasons"]) for record in knowledge_records)
    if knowledge_reasons != Counter({("legacy_unscoped",): 16, ("unknown_project_role",): 1}):
        raise RuntimeError("final knowledge selector structural categories changed")
    if not any(
        record["id"] == FINAL_OWNERSHIP_STRUCTURAL_KNOWLEDGE_ID
        and record["reasons"] == ["unknown_project_role"]
        for record in knowledge_records
    ):
        raise RuntimeError("structural knowledge target changed")

    project_records = [
        record for record in unresolved
        if record["table"] == "documents" and record["entityType"] == "project"
    ]
    project_targets = [
        {
            "table": "documents",
            "entityType": "project",
            "id": record["id"],
            "projectId": DEFAULT_PROJECT_ID,
        }
        for record in project_records
    ]
    if len(project_targets) != 3:
        raise RuntimeError(f"final project correction selector mismatch: expected 3, found {len(project_targets)}")
    if _final_target_ids_sha256(project_targets) != FINAL_OWNERSHIP_PROJECT_IDS_SHA256:
        raise RuntimeError("final project correction selector ID set mismatch")
    project_reasons = {record["id"]: record["reasons"] for record in project_records}
    expected_project_reasons = {
        entity_id: (
            ["unknown_project_role"]
            if any(
                correction["field"] == "scope_type" and correction["invalidValue"] is None
                for correction in corrections
            )
            else ["invalid_subproject_parent"]
        )
        for entity_id, corrections in FINAL_OWNERSHIP_PROJECT_CORRECTIONS.items()
    }
    if project_reasons != expected_project_reasons:
        raise RuntimeError("final project correction categories changed")

    task = next(
        (
            record for record in unresolved
            if record["table"] == "tasks" and record["id"] == FINAL_OWNERSHIP_STANDALONE_TASK_ID
        ),
        None,
    )
    if task is None or task["entityType"] != "standalone_task" or task["reasons"] != ["legacy_unscoped"]:
        raise RuntimeError("final standalone task target changed")
    task_target = {
        "table": "tasks",
        "entityType": "standalone_task",
        "id": task["id"],
        "projectId": DEFAULT_PROJECT_ID,
    }

    targets = sorted(
        [*source_targets, *knowledge_targets, *project_targets, task_target],
        key=lambda item: (item["table"], item["entityType"], item["id"]),
    )
    if len(targets) != 92 or _final_target_ids_sha256(targets) != FINAL_OWNERSHIP_TARGET_IDS_SHA256:
        raise RuntimeError("final ownership target ID set mismatch")
    if _final_assignments_sha256(targets) != FINAL_OWNERSHIP_ASSIGNMENTS_SHA256:
        raise RuntimeError("final ownership assignment split mismatch")
    if Counter(target["projectId"] for target in targets) != Counter({
        YADRO_CONTROL_PLANE_PROJECT_ID: 62,
        DEFAULT_PROJECT_ID: 30,
    }):
        raise RuntimeError("final ownership split does not match 62 core / 30 MetricHit")
    return targets


def _completed_final_batch(connection: sqlite3.Connection) -> list[dict[str, str]] | None:
    rows = connection.execute(
        "SELECT id,type,data_json,entity_type,entity_id FROM audit_log "
        "WHERE json_extract(data_json,'$.batchKey')=? ORDER BY id",
        (FINAL_OWNERSHIP_BATCH_KEY,),
    ).fetchall()
    if not rows:
        return None
    if len(rows) != 92:
        raise RuntimeError(f"partial final ownership batch detected: expected 92 audit rows, found {len(rows)}")
    targets: list[dict[str, str]] = []
    for row in rows:
        data = json.loads(row["data_json"])
        table = data.get("table")
        entity_id = data.get("entityId")
        project_id = data.get("project_id")
        if table not in {"sources", "documents", "tasks"} or not all(
            isinstance(value, str) for value in (entity_id, project_id)
        ):
            raise RuntimeError("final ownership batch contains invalid audit metadata")
        target = connection.execute(f'SELECT type FROM "{table}" WHERE id=?', (entity_id,)).fetchone()
        if target is None:
            raise RuntimeError(f"final ownership audit does not match {table}/{entity_id}")
        expected_type = (
            "project_scope_metadata_correction"
            if entity_id in FINAL_OWNERSHIP_PROJECT_CORRECTIONS
            else "project_scope_assignment"
        )
        if (
            row["type"] != expected_type
            or row["entity_type"] != target["type"]
            or row["entity_id"] != entity_id
            or row["id"] != _final_audit_id(table, entity_id, project_id)
        ):
            raise RuntimeError("final ownership batch contains an unexpected or invalid audit row")
        expected_corrections = FINAL_OWNERSHIP_PROJECT_CORRECTIONS.get(entity_id)
        if expected_corrections is not None and data.get("corrections") != list(expected_corrections):
            raise RuntimeError("final project structural correction audit is incomplete")
        targets.append({
            "table": table,
            "entityType": target["type"],
            "id": entity_id,
            "projectId": project_id,
        })
    if _final_target_ids_sha256(targets) != FINAL_OWNERSHIP_TARGET_IDS_SHA256:
        raise RuntimeError("completed final ownership batch target set mismatch")
    if _final_assignments_sha256(targets) != FINAL_OWNERSHIP_ASSIGNMENTS_SHA256:
        raise RuntimeError("completed final ownership batch assignment split mismatch")
    return sorted(targets, key=lambda item: (item["table"], item["entityType"], item["id"]))


def _completed_final_correction(connection: sqlite3.Connection) -> bool:
    rows = connection.execute(
        "SELECT id,type,data_json,entity_type,entity_id FROM audit_log "
        "WHERE json_extract(data_json,'$.batchKey')=? ORDER BY id",
        (FINAL_OWNERSHIP_CORRECTION_BATCH_KEY,),
    ).fetchall()
    if not rows:
        return False
    if len(rows) != 1:
        raise RuntimeError(f"partial final ownership correction detected: expected 1 audit row, found {len(rows)}")
    row = rows[0]
    data = json.loads(row["data_json"])
    correction = data.get("correction")
    expected_invalid_audit_id = _final_audit_id(
        "documents", FINAL_OWNERSHIP_CONTROL_KNOWLEDGE_ID, DEFAULT_PROJECT_ID,
    )
    if (
        row["id"] != _final_correction_audit_id()
        or row["type"] != "project_scope_assignment_correction"
        or row["entity_type"] != "knowledge_entry"
        or row["entity_id"] != FINAL_OWNERSHIP_CONTROL_KNOWLEDGE_ID
        or data.get("table") != "documents"
        or data.get("entityId") != FINAL_OWNERSHIP_CONTROL_KNOWLEDGE_ID
        or data.get("project_id") != YADRO_CONTROL_PLANE_PROJECT_ID
        or not isinstance(correction, dict)
        or correction.get("field") != "project_scope_assignment"
        or correction.get("invalidAuditId") != expected_invalid_audit_id
        or correction.get("invalidValue") != DEFAULT_PROJECT_ID
        or correction.get("newValue") != YADRO_CONTROL_PLANE_PROJECT_ID
    ):
        raise RuntimeError("final ownership correction audit is unexpected or incomplete")
    return True


def _apply_final_ownership_correction(
    source_path: Path,
    *,
    expected_source_sha256: str,
    expected_manifest_sha256: str,
    rollback_manifest_path: Path,
    verified_backup_set: Path,
    completed_targets: list[dict[str, str]],
) -> dict[str, Any]:
    corrected_targets = _corrected_final_targets(completed_targets)
    connection = sqlite3.connect(source_path)
    connection.row_factory = sqlite3.Row
    try:
        if _completed_final_correction(connection):
            return {"applied": 0, "alreadyApplied": 1, "rollbackManifest": None}
    finally:
        connection.close()

    plan = build_migration_plan(source_path)
    if plan["sourceSha256"] != expected_source_sha256:
        raise RuntimeError("source SHA-256 guard mismatch before final ownership correction")
    if plan["manifestSha256"] != expected_manifest_sha256:
        raise RuntimeError("migration plan manifest guard mismatch before final ownership correction")

    initial_target = next(
        target for target in completed_targets
        if target["table"] == "documents" and target["id"] == FINAL_OWNERSHIP_CONTROL_KNOWLEDGE_ID
    )
    if initial_target["projectId"] != DEFAULT_PROJECT_ID:
        raise RuntimeError("final ownership correction does not match the original assignment")
    invalid_audit_id = _final_audit_id("documents", FINAL_OWNERSHIP_CONTROL_KNOWLEDGE_ID, DEFAULT_PROJECT_ID)
    correction_audit_id = _final_correction_audit_id()
    rollback_path = rollback_manifest_path.resolve()
    correction_rollback_path = rollback_path.with_name(f"{rollback_path.stem}-correction{rollback_path.suffix}")

    connection = sqlite3.connect(source_path)
    connection.row_factory = sqlite3.Row
    try:
        target_row = connection.execute(
            "SELECT type,data_json,updated_at,version FROM documents WHERE id=?",
            (FINAL_OWNERSHIP_CONTROL_KNOWLEDGE_ID,),
        ).fetchone()
        original_audit = connection.execute(
            "SELECT type,data_json,entity_type,entity_id FROM audit_log WHERE id=?",
            (invalid_audit_id,),
        ).fetchone()
        if target_row is None or target_row["type"] != "knowledge_entry" or original_audit is None:
            raise RuntimeError("final ownership correction target or original audit is missing")
        original_data = json.loads(original_audit["data_json"])
        if (
            original_audit["type"] != "project_scope_assignment"
            or original_audit["entity_type"] != "knowledge_entry"
            or original_audit["entity_id"] != FINAL_OWNERSHIP_CONTROL_KNOWLEDGE_ID
            or original_data.get("batchKey") != FINAL_OWNERSHIP_BATCH_KEY
            or original_data.get("project_id") != DEFAULT_PROJECT_ID
        ):
            raise RuntimeError("original final ownership audit changed before correction")
        target_snapshot = dict(target_row)
    finally:
        connection.close()

    correction = {
        "field": "project_scope_assignment",
        "invalidAuditId": invalid_audit_id,
        "invalidValue": DEFAULT_PROJECT_ID,
        "newValue": YADRO_CONTROL_PLANE_PROJECT_ID,
        "reason": "system architecture, local tooling, and Codex workflow knowledge belongs to the control plane",
    }
    rollback_document = {
        "schemaVersion": OWNERSHIP_BATCH_VERSION,
        "batchKey": FINAL_OWNERSHIP_CORRECTION_BATCH_KEY,
        "correctedAssignmentsSha256": FINAL_OWNERSHIP_CORRECTED_ASSIGNMENTS_SHA256,
        "invalidAuditId": invalid_audit_id,
        "correctionAuditId": correction_audit_id,
        "sourceSha256": expected_source_sha256,
        "planManifestSha256": expected_manifest_sha256,
        "verifiedBackupSet": str(verified_backup_set.resolve()),
        "target": {
            "table": "documents",
            "entityType": "knowledge_entry",
            "id": FINAL_OWNERSHIP_CONTROL_KNOWLEDGE_ID,
            "oldProjectId": DEFAULT_PROJECT_ID,
            "newProjectId": YADRO_CONTROL_PLANE_PROJECT_ID,
            "oldDataJson": target_snapshot["data_json"],
            "oldUpdatedAt": target_snapshot["updated_at"],
            "oldVersion": target_snapshot["version"],
        },
        "restoreMethod": "restore the verified full backup set; audit_log is append-only",
    }
    rollback_json = json.dumps(rollback_document, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if correction_rollback_path.exists():
        if correction_rollback_path.read_text(encoding="utf-8-sig") != rollback_json:
            raise RuntimeError("existing correction rollback manifest does not match the approved correction")
    else:
        with correction_rollback_path.open("x", encoding="utf-8") as destination:
            destination.write(rollback_json)

    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    audit_data = {
        "batchKey": FINAL_OWNERSHIP_CORRECTION_BATCH_KEY,
        "table": "documents",
        "entityId": FINAL_OWNERSHIP_CONTROL_KNOWLEDGE_ID,
        "project_id": YADRO_CONTROL_PLANE_PROJECT_ID,
        "basis": "canonical control-plane boundary for system architecture, local tooling, and Codex workflow",
        "old": {"project_id": DEFAULT_PROJECT_ID},
        "new": {"project_id": YADRO_CONTROL_PLANE_PROJECT_ID},
        "correction": correction,
    }
    connection = sqlite3.connect(source_path)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        if sha256_file(source_path) != expected_source_sha256:
            raise RuntimeError("source changed before final ownership correction transaction")
        if _completed_final_correction(connection):
            raise RuntimeError("final ownership correction appeared during transaction")
        connection.execute(
            "INSERT INTO audit_log (id,type,title,data_json,source_id,author,created_at,updated_at,"
            "access_level,version,entity_type,entity_id,action) "
            "VALUES (?,?,?,?,?,?,?,?,'restricted',1,'knowledge_entry',?,'update')",
            (
                correction_audit_id,
                "project_scope_assignment_correction",
                "Project ownership assignment corrected",
                json.dumps(audit_data, ensure_ascii=False, sort_keys=True),
                None,
                "owner",
                now,
                now,
                FINAL_OWNERSHIP_CONTROL_KNOWLEDGE_ID,
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

    connection = sqlite3.connect(source_path)
    connection.row_factory = sqlite3.Row
    try:
        current = connection.execute(
            "SELECT type,data_json,updated_at,version FROM documents WHERE id=?",
            (FINAL_OWNERSHIP_CONTROL_KNOWLEDGE_ID,),
        ).fetchone()
        if current is None or dict(current) != target_snapshot:
            raise RuntimeError("final ownership correction changed source content")
    finally:
        connection.close()
    return {
        "applied": 1,
        "alreadyApplied": 0,
        "rollbackManifest": str(correction_rollback_path),
        "correctedTargets": corrected_targets,
    }


def apply_approved_final_ownership_batch(
    database_path: Path,
    *,
    expected_source_sha256: str,
    expected_manifest_sha256: str,
    rollback_manifest_path: Path,
    verified_backup_set: Path,
) -> dict[str, Any]:
    """Resolve the owner-approved final 348 legacy records through 92 exact roots."""
    source_path = database_path.resolve()
    backup_path = verified_backup_set.resolve()
    if not backup_path.is_dir() or len(list(backup_path.glob("*-manifest.json"))) != 1:
        raise RuntimeError("verified backup set is missing or incomplete")

    connection = sqlite3.connect(source_path)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        completed = _completed_final_batch(connection)
        completed_correction = _completed_final_correction(connection)
    finally:
        connection.close()
    if completed is not None:
        corrected_targets = _corrected_final_targets(completed)
        correction_result: dict[str, Any]
        if completed_correction:
            correction_result = {"applied": 0, "alreadyApplied": 1, "rollbackManifest": None}
        else:
            before_correction = build_migration_plan(source_path)
            if before_correction["sourceSha256"] != expected_source_sha256:
                raise RuntimeError("source SHA-256 guard mismatch before final ownership correction")
            if before_correction["manifestSha256"] != expected_manifest_sha256:
                raise RuntimeError("migration plan manifest guard mismatch before final ownership correction")
            correction_result = _apply_final_ownership_correction(
                source_path,
                expected_source_sha256=before_correction["sourceSha256"],
                expected_manifest_sha256=before_correction["manifestSha256"],
                rollback_manifest_path=rollback_manifest_path,
                verified_backup_set=backup_path,
                completed_targets=completed,
            )
        after = build_migration_plan(source_path)
        if not after["readyToMigrate"] or after["counts"][CLASS_UNRESOLVED] != 0:
            raise RuntimeError("completed final ownership batch no longer yields a migration-ready plan")
        after_by_key = {(record["table"], record["id"]): record for record in after["records"]}
        if any(
            after_by_key[(target["table"], target["id"])]["classification"]
            != (CLASS_CORE if target["projectId"] == YADRO_CONTROL_PLANE_PROJECT_ID else CLASS_PROJECT)
            for target in corrected_targets
        ):
            raise RuntimeError("corrected final ownership classification differs from the approved split")
        return {
            "batchKey": FINAL_OWNERSHIP_BATCH_KEY,
            "correctionBatchKey": FINAL_OWNERSHIP_CORRECTION_BATCH_KEY,
            "applied": correction_result["applied"],
            "alreadyApplied": 92 + correction_result["alreadyApplied"],
            "auditRows": 93,
            "directRoots": 92,
            "correctionRows": 1,
            "approvedSplit": {"controlPlaneRoots": 63, "metricHitRoots": 29},
            "targetIdsSha256": FINAL_OWNERSHIP_TARGET_IDS_SHA256,
            "assignmentsSha256": FINAL_OWNERSHIP_CORRECTED_ASSIGNMENTS_SHA256,
            "correctionRollbackManifest": correction_result["rollbackManifest"],
            "sourceSha256": after["sourceSha256"],
            "planManifestSha256": after["manifestSha256"],
            "readyToMigrate": True,
            "counts": after["counts"],
        }

    plan = build_migration_plan(source_path)
    if plan["sourceSha256"] != expected_source_sha256:
        raise RuntimeError("source SHA-256 guard mismatch")
    if plan["manifestSha256"] != expected_manifest_sha256:
        raise RuntimeError("migration plan manifest guard mismatch")
    targets = _approved_final_targets(plan)
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
            raise RuntimeError("source changed before final ownership transaction")
        rollback_rows: list[dict[str, Any]] = []
        for target in targets:
            row = connection.execute(
                f'SELECT type,data_json,updated_at,version FROM "{target["table"]}" WHERE id=?',
                (target["id"],),
            ).fetchone()
            if row is None or row["type"] != target["entityType"]:
                raise RuntimeError(f"final target changed before apply: {target['table']}/{target['id']}")
            metadata = _metadata(row["data_json"])
            corrections = FINAL_OWNERSHIP_PROJECT_CORRECTIONS.get(target["id"])
            if corrections is not None:
                for correction in corrections:
                    if metadata.get(correction["field"]) != correction["invalidValue"]:
                        raise RuntimeError(f"project structural metadata changed: {target['id']}")
            elif target["id"] == FINAL_OWNERSHIP_STRUCTURAL_KNOWLEDGE_ID:
                if (
                    metadata.get("project_id") != _final_unknown_role_project_id()
                    or metadata.get("subproject_id")
                ):
                    raise RuntimeError("structural knowledge project link changed")
            elif metadata.get("project_id") or metadata.get("subproject_id"):
                raise RuntimeError(f"final target is no longer legacy-unscoped: {target['table']}/{target['id']}")
            rollback_rows.append({
                **target,
                "oldDataJson": row["data_json"],
                "oldUpdatedAt": row["updated_at"],
                "oldVersion": row["version"],
                "auditId": _final_audit_id(target["table"], target["id"], target["projectId"]),
            })

        rollback_document = {
            "schemaVersion": OWNERSHIP_BATCH_VERSION,
            "batchKey": FINAL_OWNERSHIP_BATCH_KEY,
            "approvedSplit": {"controlPlaneRoots": 62, "metricHitRoots": 30},
            "resolvesUnresolved": 348,
            "targetIdsSha256": FINAL_OWNERSHIP_TARGET_IDS_SHA256,
            "assignmentsSha256": FINAL_OWNERSHIP_ASSIGNMENTS_SHA256,
            "sourceSha256": expected_source_sha256,
            "planManifestSha256": expected_manifest_sha256,
            "verifiedBackupSet": str(backup_path),
            "rows": rollback_rows,
            "restoreMethod": "restore the verified full backup set; audit_log is append-only",
        }
        rollback_json = json.dumps(rollback_document, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        if rollback_path.exists():
            if rollback_path.read_text(encoding="utf-8-sig") != rollback_json:
                raise RuntimeError("existing rollback manifest does not match the approved final batch")
        else:
            with rollback_path.open("x", encoding="utf-8") as destination:
                destination.write(rollback_json)

        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        for target, old in zip(targets, rollback_rows, strict=True):
            corrections = FINAL_OWNERSHIP_PROJECT_CORRECTIONS.get(target["id"])
            if target["table"] == "sources":
                basis = "canonical source boundary"
            elif target["entityType"] == "knowledge_entry":
                basis = "MetricHit business, content, or marketing knowledge"
            elif target["entityType"] == "standalone_task":
                basis = "legacy owner task in the MetricHit default project contour"
            else:
                basis = "legacy project structure corrected to the MetricHit subproject boundary"
            audit_data: dict[str, Any] = {
                "batchKey": FINAL_OWNERSHIP_BATCH_KEY,
                "table": target["table"],
                "entityId": target["id"],
                "project_id": target["projectId"],
                "basis": basis,
                "old": {"project_id": None},
                "new": {"project_id": target["projectId"]},
            }
            if corrections is not None:
                audit_data["corrections"] = list(corrections)
            connection.execute(
                "INSERT INTO audit_log (id,type,title,data_json,source_id,author,created_at,updated_at,"
                "access_level,version,entity_type,entity_id,action) "
                "VALUES (?,?,?,?,?,?,?,?,'restricted',1,?,?, 'update')",
                (
                    old["auditId"],
                    "project_scope_metadata_correction" if corrections is not None else "project_scope_assignment",
                    "Project ownership metadata corrected" if corrections is not None else "Project ownership assigned",
                    json.dumps(audit_data, ensure_ascii=False, sort_keys=True),
                    None,
                    "owner",
                    now,
                    now,
                    target["entityType"],
                    target["id"],
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

    before_correction = build_migration_plan(source_path)
    correction_result = _apply_final_ownership_correction(
        source_path,
        expected_source_sha256=before_correction["sourceSha256"],
        expected_manifest_sha256=before_correction["manifestSha256"],
        rollback_manifest_path=rollback_path,
        verified_backup_set=backup_path,
        completed_targets=targets,
    )
    after = build_migration_plan(source_path)
    unresolved_after = {
        (record["table"], record["id"])
        for record in after["records"]
        if record["classification"] == CLASS_UNRESOLVED
    }
    if unresolved_after or not after["readyToMigrate"]:
        raise RuntimeError(f"final ownership batch left {len(unresolved_after)} unresolved records")
    corrected_targets = _corrected_final_targets(targets)
    after_by_key = {(record["table"], record["id"]): record for record in after["records"]}
    if any(
        after_by_key[(target["table"], target["id"])]["classification"]
        != (CLASS_CORE if target["projectId"] == YADRO_CONTROL_PLANE_PROJECT_ID else CLASS_PROJECT)
        for target in corrected_targets
    ):
        raise RuntimeError("final ownership target classification differs from the approved split")
    if len(after["records"]) != len(plan["records"]) + 93:
        raise RuntimeError("final ownership audit row count changed unexpectedly")
    if len(unresolved_before) != 348:
        raise RuntimeError("final ownership original unresolved set changed unexpectedly")
    connection = sqlite3.connect(source_path)
    connection.row_factory = sqlite3.Row
    try:
        for old in rollback_rows:
            current = connection.execute(
                f'SELECT data_json,updated_at,version FROM "{old["table"]}" WHERE id=?',
                (old["id"],),
            ).fetchone()
            if current is None or dict(current) != {
                "data_json": old["oldDataJson"],
                "updated_at": old["oldUpdatedAt"],
                "version": old["oldVersion"],
            }:
                raise RuntimeError(f"final ownership target content changed: {old['table']}/{old['id']}")
    finally:
        connection.close()
    return {
        "batchKey": FINAL_OWNERSHIP_BATCH_KEY,
        "correctionBatchKey": FINAL_OWNERSHIP_CORRECTION_BATCH_KEY,
        "applied": 92 + correction_result["applied"],
        "alreadyApplied": 0,
        "auditRows": 93,
        "directRoots": 92,
        "correctionRows": 1,
        "approvedSplit": {"controlPlaneRoots": 63, "metricHitRoots": 29},
        "resolvedUnresolved": 348,
        "targetIdsSha256": FINAL_OWNERSHIP_TARGET_IDS_SHA256,
        "assignmentsSha256": FINAL_OWNERSHIP_CORRECTED_ASSIGNMENTS_SHA256,
        "rollbackManifest": str(rollback_path),
        "correctionRollbackManifest": correction_result["rollbackManifest"],
        "sourceSha256Before": expected_source_sha256,
        "sourceSha256After": after["sourceSha256"],
        "planManifestSha256After": after["manifestSha256"],
        "readyToMigrate": after["readyToMigrate"],
        "counts": after["counts"],
        "unresolvedCategories": after["unresolvedCategories"],
    }


def _json_sha256(value: object) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _ids_sha256(ids: list[str]) -> str:
    return hashlib.sha256(("\n".join(ids) + "\n").encode("utf-8")).hexdigest()


def _json_sql_value(value: object) -> object:
    if isinstance(value, bytes):
        return {"sqliteBlobHex": value.hex()}
    return value


def _table_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    columns = [row["name"] for row in connection.execute(f'PRAGMA table_info("{table}")')]
    if not columns:
        raise RuntimeError(f"source table has no columns: {table}")
    return columns


def _stable_column(columns: list[str]) -> str:
    return "id" if "id" in columns else "version" if "version" in columns else columns[0]


def _schema_objects(connection: sqlite3.Connection) -> list[dict[str, str]]:
    rows = connection.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' AND sql IS NOT NULL ORDER BY type,name"
    ).fetchall()
    return [
        {"type": row["type"], "name": row["name"], "table": row["tbl_name"], "sql": row["sql"]}
        for row in rows
    ]


def _read_row(
    connection: sqlite3.Connection,
    table: str,
    stable_column: str,
    entity_id: str,
) -> sqlite3.Row:
    row = connection.execute(
        f'SELECT * FROM "{table}" WHERE "{stable_column}"=?', (entity_id,)
    ).fetchone()
    if row is None:
        raise RuntimeError(f"planned source row is missing: {table}/{entity_id}")
    return row


def _backup_manifest_for_source(
    backup_set: Path,
    expected_source_sha256: str,
    *,
    expected_existing_target_sha256: str | None = None,
) -> dict[str, Any]:
    backup_path = backup_set.resolve()
    if not backup_path.is_dir() or not re.fullmatch(r"MetricHit-backup-\d{8}T\d{6}Z", backup_path.name):
        raise RuntimeError("verified backup set path is invalid or incomplete")
    manifest_path = backup_path / f"{backup_path.name}-manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError("verified backup set manifest is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if manifest.get("formatVersion") != 4 or manifest.get("backupId") != backup_path.name:
        raise RuntimeError("verified backup set does not use the exact-source format")
    components = manifest.get("components")
    if not isinstance(components, list) or len(components) != 2:
        raise RuntimeError("verified backup set component inventory is invalid")
    roles: set[str] = set()
    for component in components:
        if not isinstance(component, dict):
            raise RuntimeError("verified backup set component is invalid")
        role, name = component.get("role"), component.get("name")
        if role in roles or role not in {"workspace-archive", "git-bundle"}:
            raise RuntimeError("verified backup set component role is invalid")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9._-]+", name):
            raise RuntimeError("verified backup set component name is unsafe")
        component_path = backup_path / name
        if (
            not component_path.is_file()
            or component_path.stat().st_size != component.get("size")
            or sha256_file(component_path) != component.get("sha256")
        ):
            raise RuntimeError(f"verified backup component mismatch: {role}")
        roles.add(role)
    central = manifest.get("centralDatabase")
    if not isinstance(central, dict):
        raise RuntimeError("verified backup set lacks the central database guard")
    if (
        central.get("path") != "data/database/metrichit.db"
        or central.get("method") != "sqlite-online-backup"
        or central.get("integrity") != "ok"
        or central.get("sourceSha256") != expected_source_sha256
        or not re.fullmatch(r"[0-9a-f]{64}", str(central.get("sha256", "")))
        or not isinstance(central.get("size"), int)
        or central["size"] <= 0
    ):
        raise RuntimeError("verified backup set does not match the guarded source database")
    projects = manifest.get("projectStorages")
    if not isinstance(projects, dict) or projects.get("root") != "data/projects":
        raise RuntimeError("verified backup set lacks the project inventory")
    inventory = projects.get("inventory")
    if not isinstance(inventory, list) or projects.get("count") != len(inventory):
        raise RuntimeError("verified backup project inventory is invalid")
    target_items = [
        item for item in inventory
        if isinstance(item, dict) and item.get("projectId") == DEFAULT_PROJECT_ID
    ]
    if expected_existing_target_sha256 is None:
        if target_items:
            raise RuntimeError("verified pre-migration backup unexpectedly contains the MetricHit target")
    elif (
        len(target_items) != 1
        or target_items[0].get("path")
        != f"data/projects/{DEFAULT_PROJECT_ID}/project.sqlite"
        or not re.fullmatch(r"[0-9a-f]{64}", str(target_items[0].get("sha256", "")))
        or not isinstance(target_items[0].get("size"), int)
        or target_items[0]["size"] <= 0
        or target_items[0].get("storageFormat") != STORAGE_FORMAT_VERSION
        or target_items[0].get("integrity") != "ok"
    ):
        raise RuntimeError("verified replacement backup does not contain the guarded MetricHit target")
    return {
        "backupId": backup_path.name,
        "path": str(backup_path),
        "manifest": str(manifest_path),
        "centralSnapshotSha256": central["sha256"],
        "centralSourceSha256": central["sourceSha256"],
        "projectStorageCount": len(inventory),
        "existingTargetSourceSha256": expected_existing_target_sha256,
        "projectSnapshotSha256": target_items[0]["sha256"] if target_items else None,
    }


def _primary_record_keys(plan: dict[str, Any]) -> set[tuple[str, str]]:
    return {
        (record["table"], record["id"])
        for record in plan["records"]
        if record["classification"] == CLASS_PROJECT
        and record.get("projectId") == DEFAULT_PROJECT_ID
    }


def _foreign_key_dependencies(
    connection: sqlite3.Connection,
    plan: dict[str, Any],
    primary: set[tuple[str, str]],
) -> set[tuple[str, str]]:
    plan_by_key = {(record["table"], record["id"]): record for record in plan["records"]}
    selected = set(primary)
    dependencies: set[tuple[str, str]] = set()
    for _ in range(len(plan["records"]) + 1):
        changed = False
        for table, entity_id in sorted(selected):
            columns = _table_columns(connection, table)
            stable = _stable_column(columns)
            row = _read_row(connection, table, stable, entity_id)
            for foreign_key in connection.execute(f'PRAGMA foreign_key_list("{table}")'):
                target_table = foreign_key["table"]
                from_column = foreign_key["from"]
                target_column = foreign_key["to"]
                value = row[from_column]
                if value is None:
                    continue
                target_columns = _table_columns(connection, target_table)
                target_stable = _stable_column(target_columns)
                if target_column != target_stable:
                    raise RuntimeError(
                        f"unsupported non-stable foreign key: {table}.{from_column} -> {target_table}.{target_column}"
                    )
                target = connection.execute(
                    f'SELECT "{target_stable}" FROM "{target_table}" WHERE "{target_column}"=?',
                    (value,),
                ).fetchone()
                if target is None:
                    raise RuntimeError(f"source foreign key is broken: {table}/{entity_id}/{from_column}")
                key = (target_table, str(target[target_stable]))
                if key in selected:
                    continue
                record = plan_by_key.get(key)
                if record is None or record["classification"] != CLASS_CORE:
                    raise RuntimeError(
                        f"MetricHit row depends on a non-core external project row: {table}/{entity_id}/{from_column}"
                    )
                selected.add(key)
                dependencies.add(key)
                changed = True
        if not changed:
            return dependencies
    raise RuntimeError("foreign-key dependency closure did not converge")


def _effective_metadata_corrections(
    connection: sqlite3.Connection,
    selected: set[tuple[str, str]],
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    corrections: dict[tuple[str, str], list[dict[str, Any]]] = {}
    if ("audit_log",) not in {
        (row["name"],)
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }:
        return corrections
    for row in connection.execute(
        "SELECT id,data_json FROM audit_log WHERE type='project_scope_metadata_correction' ORDER BY id"
    ):
        data = _metadata(row["data_json"])
        key = (data.get("table"), data.get("entityId"))
        if key not in selected:
            continue
        items = data.get("corrections")
        if not isinstance(items, list):
            item = data.get("correction")
            items = [item] if isinstance(item, dict) else []
        for item in items:
            if not isinstance(item, dict) or "newValue" not in item or not isinstance(item.get("field"), str):
                continue
            corrections.setdefault(key, []).append({
                "auditId": row["id"],
                "field": item["field"],
                "invalidValue": item.get("invalidValue"),
                "newValue": item.get("newValue"),
            })
    return corrections


def _apply_effective_corrections(
    table: str,
    entity_id: str,
    columns: list[str],
    values: list[object],
    corrections: dict[tuple[str, str], list[dict[str, Any]]],
) -> tuple[list[object], list[dict[str, Any]]]:
    applied: list[dict[str, Any]] = []
    items = corrections.get((table, entity_id), [])
    if not items:
        return values, applied
    if "data_json" not in columns:
        raise RuntimeError(f"metadata correction targets a row without data_json: {table}/{entity_id}")
    index = columns.index("data_json")
    metadata = _metadata(values[index])
    for item in items:
        field = item["field"]
        if metadata.get(field) != item["invalidValue"]:
            raise RuntimeError(f"audited metadata correction no longer matches source: {table}/{entity_id}/{field}")
        metadata[field] = item["newValue"]
        applied.append({"table": table, "id": entity_id, **item})
    values[index] = json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return values, applied


def _record_set(
    connection: sqlite3.Connection,
    keys: set[tuple[str, str]],
    corrections: dict[tuple[str, str], list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], dict[str, list[tuple[object, ...]]], list[dict[str, Any]]]:
    tables: list[dict[str, Any]] = []
    rows_by_table: dict[str, list[tuple[object, ...]]] = {}
    applied: list[dict[str, Any]] = []
    for table in sorted({table for table, _ in keys}):
        columns = _table_columns(connection, table)
        stable = _stable_column(columns)
        ids = sorted(entity_id for candidate_table, entity_id in keys if candidate_table == table)
        source_payload: list[list[object]] = []
        target_payload: list[list[object]] = []
        copied_rows: list[tuple[object, ...]] = []
        for entity_id in ids:
            row = _read_row(connection, table, stable, entity_id)
            source_values = [row[column] for column in columns]
            target_values, row_applied = _apply_effective_corrections(
                table, entity_id, columns, list(source_values), corrections
            )
            source_payload.append([_json_sql_value(value) for value in source_values])
            target_payload.append([_json_sql_value(value) for value in target_values])
            copied_rows.append(tuple(target_values))
            applied.extend(row_applied)
        rows_by_table[table] = copied_rows
        tables.append({
            "table": table,
            "columns": columns,
            "count": len(ids),
            "ids": ids,
            "idsSha256": _ids_sha256(ids),
            "sourceRowsSha256": _json_sha256({"columns": columns, "rows": source_payload}),
            "targetRowsSha256": _json_sha256({"columns": columns, "rows": target_payload}),
        })
    return tables, rows_by_table, applied


def _validate_relationship_closure(
    rows_by_category: list[dict[str, list[tuple[object, ...]]]],
    table_columns: dict[str, list[str]],
) -> None:
    copied_ids: set[str] = set()
    copied_project_ids: set[str] = set()
    for rows_by_table in rows_by_category:
        for table, rows in rows_by_table.items():
            columns = table_columns[table]
            stable = _stable_column(columns)
            stable_index = columns.index(stable)
            for row in rows:
                copied_ids.add(str(row[stable_index]))
                if table == "documents" and "type" in columns and row[columns.index("type")] == "project":
                    copied_project_ids.add(str(row[stable_index]))
    for rows_by_table in rows_by_category:
        for table, rows in rows_by_table.items():
            columns = table_columns[table]
            stable = _stable_column(columns)
            stable_index = columns.index(stable)
            for row in rows:
                entity_id = str(row[stable_index])
                if "data_json" not in columns:
                    continue
                metadata = _metadata(row[columns.index("data_json")])
                for field in TARGET_METADATA_RELATION_FIELDS:
                    target_id = metadata.get(field)
                    if not target_id:
                        continue
                    allowed = copied_project_ids if field in {"parent_project_id", "project_id", "subproject_id"} else copied_ids
                    if str(target_id) not in allowed:
                        raise RuntimeError(
                            f"target relationship closure is incomplete: {table}/{entity_id}/data_json.{field}"
                        )


def _write_exact_json(path: Path, payload: dict[str, Any]) -> None:
    destination = path.resolve()
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.read_text(encoding="utf-8-sig") != rendered:
            raise RuntimeError(f"existing migration artifact differs: {destination}")
        return
    with destination.open("x", encoding="utf-8") as output:
        output.write(rendered)


def _artifact_payload(artifact_type: str, body: dict[str, Any]) -> dict[str, Any]:
    payload = {"schemaVersion": MATERIALIZATION_SCHEMA_VERSION, "artifactType": artifact_type, **body}
    payload["artifactSha256"] = _json_sha256(payload)
    return payload


def _verify_materialized_target(
    target: Path,
    expected_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with read_only_database(target) as connection:
        integrity = [tuple(row) for row in connection.execute("PRAGMA integrity_check")]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != [("ok",)] or foreign_keys:
            raise RuntimeError("materialized project SQLite failed integrity or foreign-key checks")
        identity = connection.execute(
            "SELECT project_id,storage_format FROM project_storage_metadata WHERE singleton=1"
        ).fetchone()
        stored = connection.execute(
            "SELECT migration_key,schema_version,project_id,manifest_sha256,manifest_json "
            "FROM project_migration_manifest WHERE singleton=1"
        ).fetchone()
        if (
            identity is None
            or identity["project_id"] != DEFAULT_PROJECT_ID
            or identity["storage_format"] != STORAGE_FORMAT_VERSION
            or stored is None
            or stored["migration_key"] != MATERIALIZATION_KEY
            or stored["schema_version"] != MATERIALIZATION_SCHEMA_VERSION
            or stored["project_id"] != DEFAULT_PROJECT_ID
        ):
            raise RuntimeError("materialized project identity or manifest is invalid")
        manifest = json.loads(stored["manifest_json"])
        unhashed = dict(manifest)
        manifest_hash = unhashed.pop("manifestSha256", None)
        if manifest_hash != stored["manifest_sha256"] or _json_sha256(unhashed) != manifest_hash:
            raise RuntimeError("materialized project manifest hash mismatch")
        if expected_manifest is not None and manifest != expected_manifest:
            raise RuntimeError("existing project migration manifest differs from the guarded source")
        source_object_names = set(manifest["sourceSchema"]["objectNames"])
        all_target_objects = _schema_objects(connection)
        if {item["name"] for item in all_target_objects} != source_object_names | TARGET_METADATA_TABLES:
            raise RuntimeError("materialized target schema inventory mismatch")
        target_objects = [
            item for item in all_target_objects if item["name"] in source_object_names
        ]
        if _json_sha256(target_objects) != manifest["sourceSchema"]["sha256"]:
            raise RuntimeError("materialized source schema hash mismatch")
        expected_ids_by_table = {
            item["name"]: set()
            for item in target_objects
            if item["type"] == "table"
        }
        for category in manifest["recordSets"].values():
            for table_info in category["tables"]:
                table = table_info["table"]
                expected_ids_by_table[table].update(table_info["ids"])
                columns = table_info["columns"]
                stable = _stable_column(columns)
                payload: list[list[object]] = []
                for entity_id in table_info["ids"]:
                    row = _read_row(connection, table, stable, entity_id)
                    payload.append([_json_sql_value(row[column]) for column in columns])
                if (
                    len(payload) != table_info["count"]
                    or _ids_sha256(table_info["ids"]) != table_info["idsSha256"]
                    or _json_sha256({"columns": columns, "rows": payload}) != table_info["targetRowsSha256"]
                ):
                    raise RuntimeError(f"materialized record reconciliation failed: {table}")
        for table, expected_ids in expected_ids_by_table.items():
            columns = _table_columns(connection, table)
            stable = _stable_column(columns)
            actual_ids = {
                str(row[stable])
                for row in connection.execute(f'SELECT "{stable}" FROM "{table}"')
            }
            if actual_ids != expected_ids:
                raise RuntimeError(f"materialized record inventory mismatch: {table}")
        return manifest


def verify_metrichit_runtime_storage(
    source_path: Path,
    target_path: Path,
) -> dict[str, Any]:
    """Fail closed unless the mutable MetricHit runtime storage is compatible.

    The embedded materialization manifest remains the immutable cutover baseline.
    Runtime rows may evolve after cutover, so startup validates identity, schema,
    integrity and the legacy source schema without requiring either database to
    keep the cutover baseline's exact row inventory.
    """
    with read_only_database(target_path.resolve()) as connection:
        integrity = [tuple(row) for row in connection.execute("PRAGMA integrity_check")]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        identity = connection.execute(
            "SELECT project_id,storage_format FROM project_storage_metadata WHERE singleton=1"
        ).fetchone()
        stored = connection.execute(
            "SELECT migration_key,schema_version,project_id,manifest_sha256,manifest_json "
            "FROM project_migration_manifest WHERE singleton=1"
        ).fetchone()
        if integrity != [("ok",)] or foreign_keys:
            raise RuntimeError("MetricHit runtime storage failed integrity or foreign-key checks")
        if (
            identity is None
            or identity["project_id"] != DEFAULT_PROJECT_ID
            or identity["storage_format"] != STORAGE_FORMAT_VERSION
            or stored is None
            or stored["migration_key"] != MATERIALIZATION_KEY
            or stored["schema_version"] != MATERIALIZATION_SCHEMA_VERSION
            or stored["project_id"] != DEFAULT_PROJECT_ID
        ):
            raise RuntimeError("MetricHit runtime storage identity or manifest is invalid")
        manifest = json.loads(stored["manifest_json"])
        unhashed = dict(manifest)
        manifest_hash = unhashed.pop("manifestSha256", None)
        if manifest_hash != stored["manifest_sha256"] or _json_sha256(unhashed) != manifest_hash:
            raise RuntimeError("MetricHit runtime storage manifest hash mismatch")
        if manifest.get("cutover") is not True:
            raise RuntimeError("MetricHit runtime storage is not activated for cutover")
        source_names = set(manifest["sourceSchema"]["objectNames"])
        objects = _schema_objects(connection)
        object_names = {item["name"] for item in objects}
        baseline_names = source_names | TARGET_METADATA_TABLES
        editorial_names = EDITORIAL_SCHEMA_OBJECTS
        supported_names = baseline_names | STRUCTURED_MEMORY_SCHEMA_OBJECTS
        if object_names in (baseline_names, supported_names):
            pass
        elif object_names in (
            baseline_names | editorial_names,
            supported_names | editorial_names,
        ):
            try:
                check_editorial_domain(target_path)
            except EditorialDomainError as error:
                raise RuntimeError("MetricHit runtime editorial schema is invalid") from error
        else:
            raise RuntimeError("MetricHit runtime storage schema inventory mismatch")
        source_objects = [item for item in objects if item["name"] in source_names]
        if _json_sha256(source_objects) != manifest["sourceSchema"]["sha256"]:
            raise RuntimeError("MetricHit runtime storage schema hash mismatch")
    _verify_legacy_source_schema(source_path.resolve(), manifest)
    return manifest


def _verify_legacy_source_schema(source_path: Path, manifest: dict[str, Any]) -> None:
    with read_only_database(source_path) as source:
        objects = _schema_objects(source)
        baseline_names = set(manifest["sourceSchema"]["objectNames"])
        object_names = {item["name"] for item in objects}
        if object_names not in (
            baseline_names,
            baseline_names | STRUCTURED_MEMORY_SCHEMA_OBJECTS,
        ):
            raise RuntimeError("current legacy source schema differs from the materialized manifest")
        source_objects = [item for item in objects if item["name"] in baseline_names]
        if (
            _json_sha256(source_objects) != manifest["sourceSchema"]["sha256"]
            or [item["name"] for item in source_objects] != manifest["sourceSchema"]["objectNames"]
        ):
            raise RuntimeError("current legacy source schema differs from the materialized manifest")


def _reconcile_source_project_rows(source_path: Path, manifest: dict[str, Any]) -> None:
    current_plan = build_migration_plan(source_path)
    if not current_plan["readyToMigrate"] or current_plan["counts"][CLASS_UNRESOLVED] != 0:
        raise RuntimeError("current legacy source is no longer ready to migrate")
    with read_only_database(source_path) as source:
        source_objects = _schema_objects(source)
        if (
            _json_sha256(source_objects) != manifest["sourceSchema"]["sha256"]
            or [item["name"] for item in source_objects] != manifest["sourceSchema"]["objectNames"]
        ):
            raise RuntimeError("current legacy source schema differs from the materialized manifest")
        primary = _primary_record_keys(current_plan)
        dependencies = _foreign_key_dependencies(source, current_plan, primary)
        system = {
            (record["table"], record["id"])
            for record in current_plan["records"]
            if record["table"] in SYSTEM_TABLES
        }
        selected = primary | dependencies | system
        corrections = _effective_metadata_corrections(source, selected)
        primary_tables, primary_rows, primary_applied = _record_set(source, primary, corrections)
        dependency_tables, dependency_rows, dependency_applied = _record_set(
            source, dependencies, corrections
        )
        system_tables, system_rows, system_applied = _record_set(source, system, corrections)
        applied_corrections = sorted(
            [*primary_applied, *dependency_applied, *system_applied],
            key=lambda item: (item["table"], item["id"], item["field"], item["auditId"]),
        )
        table_columns = {
            table: _table_columns(source, table)
            for table in sorted({table for table, _ in selected})
        }
        _validate_relationship_closure(
            [primary_rows, dependency_rows, system_rows], table_columns
        )
    current_sets = {
        "primary": {"count": len(primary), "tables": primary_tables},
        "dependencies": {"count": len(dependencies), "tables": dependency_tables},
        "system": {"count": len(system), "tables": system_tables},
    }
    if current_sets != manifest["recordSets"] or applied_corrections != manifest["metadataCorrections"]:
        raise RuntimeError("current MetricHit source rows differ from the materialized manifest")


def materialize_metrichit_project(
    database_path: Path,
    *,
    expected_source_sha256: str,
    expected_manifest_sha256: str,
    verified_backup_set: Path,
    migration_manifest_path: Path,
    rollback_manifest_path: Path,
    project_storage_root: Path | None = None,
    replace_existing: bool = False,
    activate_runtime: bool = False,
) -> dict[str, Any]:
    """Atomically materialize the canonical MetricHit contour without changing legacy SQLite."""
    source_path = database_path.resolve()
    storage = ProjectStorage(project_storage_root) if project_storage_root is not None else ProjectStorage()
    location = storage.location(DEFAULT_PROJECT_ID)

    existing_target_sha256: str | None = None
    if location.database.exists() and not replace_existing:
        manifest = _verify_materialized_target(location.database)
        if (
            manifest["sourceSha256"] != expected_source_sha256
            or manifest["planManifestSha256"] != expected_manifest_sha256
        ):
            raise RuntimeError("existing MetricHit project SQLite differs from the guarded migration")
        backup = _backup_manifest_for_source(verified_backup_set, manifest["sourceSha256"])
        if manifest["verifiedBackup"]["backupId"] != backup["backupId"]:
            raise RuntimeError("existing MetricHit project SQLite uses a different verified backup")
        _reconcile_source_project_rows(source_path, manifest)
        target_sha256 = sha256_file(location.database)
        migration_artifact = _artifact_payload("project-migration-manifest", {
            "migration": manifest, "targetSha256": target_sha256,
        })
        rollback_artifact = _artifact_payload("project-migration-rollback", {
            "migrationKey": MATERIALIZATION_KEY,
            "projectId": DEFAULT_PROJECT_ID,
            "legacyDatabase": str(source_path),
            "legacySourceSha256": manifest["sourceSha256"],
            "targetDatabase": str(location.database),
            "targetSha256": target_sha256,
            "verifiedBackup": backup,
            "rollbackMethod": "with separate owner approval, remove only the newly materialized target; legacy remains the working source; restore the verified full backup set if broader recovery is required",
        })
        _write_exact_json(migration_manifest_path, migration_artifact)
        _write_exact_json(rollback_manifest_path, rollback_artifact)
        return {
            "migrationKey": MATERIALIZATION_KEY,
            "applied": 0,
            "alreadyMaterialized": 1,
            "projectId": DEFAULT_PROJECT_ID,
            "targetDatabase": str(location.database),
            "targetSha256": target_sha256,
            "counts": manifest["counts"],
            "manifestSha256": manifest["manifestSha256"],
            "migrationManifest": str(migration_manifest_path.resolve()),
            "rollbackManifest": str(rollback_manifest_path.resolve()),
        }

    if replace_existing:
        if not location.database.exists():
            raise RuntimeError("MetricHit target does not exist for guarded replacement")
        _verify_materialized_target(location.database)
        existing_target_sha256 = sha256_file(location.database)
    elif activate_runtime:
        raise RuntimeError("runtime activation requires guarded replacement of an existing target")

    source_hash_before = sha256_file(source_path)
    if source_hash_before != expected_source_sha256:
        raise RuntimeError("source SHA-256 guard mismatch")
    plan = build_migration_plan(source_path)
    if plan["manifestSha256"] != expected_manifest_sha256:
        raise RuntimeError("migration plan manifest guard mismatch")
    if not plan["readyToMigrate"] or plan["counts"][CLASS_UNRESOLVED] != 0:
        raise RuntimeError("migration plan is not ready to migrate")
    backup = _backup_manifest_for_source(
        verified_backup_set,
        expected_source_sha256,
        expected_existing_target_sha256=existing_target_sha256,
    )

    with read_only_database(source_path) as source:
        source_objects = _schema_objects(source)
        if any(item["name"] in TARGET_METADATA_TABLES for item in source_objects):
            raise RuntimeError("source schema conflicts with reserved project metadata tables")
        primary = _primary_record_keys(plan)
        dependencies = _foreign_key_dependencies(source, plan, primary)
        system = {
            (record["table"], record["id"])
            for record in plan["records"]
            if record["table"] in SYSTEM_TABLES
        }
        selected = primary | dependencies | system
        corrections = _effective_metadata_corrections(source, selected)
        primary_tables, primary_rows, primary_applied = _record_set(source, primary, corrections)
        dependency_tables, dependency_rows, dependency_applied = _record_set(source, dependencies, corrections)
        system_tables, system_rows, system_applied = _record_set(source, system, corrections)
        applied_corrections = sorted(
            [*primary_applied, *dependency_applied, *system_applied],
            key=lambda item: (item["table"], item["id"], item["field"], item["auditId"]),
        )
        table_columns = {
            table: _table_columns(source, table)
            for table in sorted({table for table, _ in selected})
        }
        _validate_relationship_closure(
            [primary_rows, dependency_rows, system_rows], table_columns
        )

    created_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    source_schema = {
        "objectCount": len(source_objects),
        "objectNames": [item["name"] for item in source_objects],
        "sha256": _json_sha256(source_objects),
    }
    record_sets = {
        "primary": {"count": len(primary), "tables": primary_tables},
        "dependencies": {"count": len(dependencies), "tables": dependency_tables},
        "system": {"count": len(system), "tables": system_tables},
    }
    manifest_without_hash: dict[str, Any] = {
        "schemaVersion": MATERIALIZATION_SCHEMA_VERSION,
        "migrationKey": MATERIALIZATION_KEY,
        "createdAt": created_at,
        "projectId": DEFAULT_PROJECT_ID,
        "storageFormat": STORAGE_FORMAT_VERSION,
        "sourceSha256": expected_source_sha256,
        "planSchemaVersion": plan["schemaVersion"],
        "planManifestSha256": expected_manifest_sha256,
        "verifiedBackup": backup,
        "sourceSchema": source_schema,
        "recordSets": record_sets,
        "metadataCorrections": applied_corrections,
        "counts": {
            "primary": len(primary),
            "dependencies": len(dependencies),
            "system": len(system),
            "totalCopied": len(primary | dependencies | system),
            "metadataCorrections": len(applied_corrections),
        },
        "legacyRuntimeState": "central-control-plane" if activate_runtime else "unchanged-working-source",
        "cutover": activate_runtime,
    }
    manifest = {**manifest_without_hash, "manifestSha256": _json_sha256(manifest_without_hash)}
    manifest_json = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    handle, staging_name = tempfile.mkstemp(prefix="metrichit-project-", suffix=".sqlite")
    os.close(handle)
    staging_path = Path(staging_name)
    try:
        target = sqlite3.connect(staging_path)
        target.row_factory = sqlite3.Row
        try:
            target.execute("PRAGMA foreign_keys = OFF")
            target.execute("BEGIN IMMEDIATE")
            tables = [item for item in source_objects if item["type"] == "table"]
            secondary = [item for item in source_objects if item["type"] != "table"]
            for item in tables:
                target.execute(item["sql"])
            target.execute(
                "CREATE TABLE project_storage_metadata ("
                "singleton INTEGER PRIMARY KEY CHECK (singleton = 1),"
                "project_id TEXT NOT NULL UNIQUE,"
                "storage_format INTEGER NOT NULL CHECK (storage_format = 1))"
            )
            target.execute(
                "INSERT INTO project_storage_metadata(singleton,project_id,storage_format) VALUES(1,?,?)",
                (DEFAULT_PROJECT_ID, STORAGE_FORMAT_VERSION),
            )
            target.execute(
                "CREATE TABLE project_migration_manifest ("
                "singleton INTEGER PRIMARY KEY CHECK (singleton = 1),"
                "migration_key TEXT NOT NULL UNIQUE,schema_version INTEGER NOT NULL,"
                "project_id TEXT NOT NULL,manifest_sha256 TEXT NOT NULL,"
                "manifest_json TEXT NOT NULL CHECK(json_valid(manifest_json)))"
            )
            for rows_by_table in (primary_rows, dependency_rows, system_rows):
                for table in sorted(rows_by_table):
                    columns = table_columns[table]
                    quoted = ",".join(f'"{column}"' for column in columns)
                    placeholders = ",".join("?" for _ in columns)
                    target.executemany(
                        f'INSERT INTO "{table}" ({quoted}) VALUES ({placeholders})',
                        rows_by_table[table],
                    )
            for item in secondary:
                target.execute(item["sql"])
            target.execute(
                "INSERT INTO project_migration_manifest VALUES(1,?,?,?,?,?)",
                (
                    MATERIALIZATION_KEY, MATERIALIZATION_SCHEMA_VERSION, DEFAULT_PROJECT_ID,
                    manifest["manifestSha256"], manifest_json,
                ),
            )
            foreign_keys = target.execute("PRAGMA foreign_key_check").fetchall()
            integrity = [tuple(row) for row in target.execute("PRAGMA integrity_check")]
            if foreign_keys or integrity != [("ok",)]:
                raise RuntimeError("new project SQLite failed integrity or foreign-key checks")
            target.commit()
        except Exception:
            target.rollback()
            raise
        finally:
            target.close()
        _verify_materialized_target(staging_path, manifest)
        if sha256_file(source_path) != expected_source_sha256:
            raise RuntimeError("legacy source changed during project materialization")
        plan_after = build_migration_plan(source_path)
        if plan_after["manifestSha256"] != expected_manifest_sha256:
            raise RuntimeError("migration plan changed during project materialization")
        location.directory.parent.mkdir(parents=True, exist_ok=True)
        location.directory.mkdir(exist_ok=True)
        entries = list(location.directory.iterdir())
        if replace_existing:
            if entries != [location.database] or sha256_file(location.database) != existing_target_sha256:
                raise RuntimeError("MetricHit target changed before atomic replacement")
            os.replace(staging_path, location.database)
        else:
            if entries:
                raise RuntimeError("MetricHit project storage directory is not empty")
            if location.database.exists():
                raise RuntimeError("MetricHit target appeared during atomic materialization")
            os.rename(staging_path, location.database)
    finally:
        if staging_path.exists():
            staging_path.unlink()

    storage.initialize(DEFAULT_PROJECT_ID)
    verified_manifest = _verify_materialized_target(location.database, manifest)
    if verified_manifest != manifest or sha256_file(source_path) != source_hash_before:
        raise RuntimeError("post-materialization reconciliation failed")
    target_sha256 = sha256_file(location.database)
    migration_artifact = _artifact_payload("project-migration-manifest", {
        "migration": manifest, "targetSha256": target_sha256,
    })
    rollback_artifact = _artifact_payload("project-migration-rollback", {
        "migrationKey": MATERIALIZATION_KEY,
        "projectId": DEFAULT_PROJECT_ID,
        "legacyDatabase": str(source_path),
        "legacySourceSha256": source_hash_before,
        "targetDatabase": str(location.database),
        "targetSha256": target_sha256,
        "verifiedBackup": backup,
        "rollbackMethod": (
            "restore the verified full backup set to revert the guarded target replacement and runtime cutover"
            if replace_existing
            else "with separate owner approval, remove only the newly materialized target; legacy remains the working source; restore the verified full backup set if broader recovery is required"
        ),
    })
    _write_exact_json(migration_manifest_path, migration_artifact)
    _write_exact_json(rollback_manifest_path, rollback_artifact)
    return {
        "migrationKey": MATERIALIZATION_KEY,
        "applied": 1,
        "alreadyMaterialized": 0,
        "replacedExisting": int(replace_existing),
        "projectId": DEFAULT_PROJECT_ID,
        "targetDatabase": str(location.database),
        "targetSha256": target_sha256,
        "counts": manifest["counts"],
        "tables": [item["table"] for item in primary_tables],
        "sourceSha256Before": source_hash_before,
        "sourceSha256After": sha256_file(source_path),
        "planManifestSha256": expected_manifest_sha256,
        "manifestSha256": manifest["manifestSha256"],
        "migrationManifest": str(migration_manifest_path.resolve()),
        "rollbackManifest": str(rollback_manifest_path.resolve()),
        "integrity": "ok",
        "foreignKeys": "ok",
        "cutover": activate_runtime,
    }

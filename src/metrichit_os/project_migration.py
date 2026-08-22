from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from .database import read_only_database, sha256_file
from .project_scope import DEFAULT_PROJECT_ID, YADRO_CONTROL_PLANE_PROJECT_ID


PLAN_SCHEMA_VERSION = 1
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

    results: list[tuple[str, str | None, list[str]]] = []
    for row in rows:
        signals: list[tuple[str, str | None, str]] = []
        if row["table"] in SYSTEM_TABLES:
            signals.append((CLASS_CORE, None, "core_system_table"))
        if row["table"] == "documents" and row["entityType"] == "project":
            signals.append(_signal(row["id"], projects))
        metadata = row["metadata"]
        if metadata.get("project_id"):
            signals.append(_signal(str(metadata["project_id"]), projects))
        if metadata.get("subproject_id"):
            signals.append(_signal(str(metadata["subproject_id"]), projects))
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

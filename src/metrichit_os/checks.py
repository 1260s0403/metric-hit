from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from .config import (
    EDITORIAL_DATABASE,
    EDITORIAL_MIGRATIONS,
    MEMORY_DATABASE,
    MEMORY_MIGRATIONS,
)
from .database import normalize_sql, read_only_database


MEMORY_TABLES = [
    "audit_log", "decisions", "document_versions", "documents",
    "memory_candidates", "memory_conflicts", "memory_items",
    "schema_migrations", "sources", "tasks",
]
MEMORY_TRIGGERS = [
    "audit_log_prevent_delete", "audit_log_prevent_update",
    "document_versions_prevent_delete", "document_versions_prevent_update",
    "memory_candidates_conflict_on_approval", "memory_candidates_protect_terminal_delete",
    "memory_candidates_protect_terminal_update", "memory_candidates_require_pending_insert",
    "memory_candidates_validate_review_metadata_insert",
    "memory_candidates_validate_review_metadata_update",
    "memory_candidates_validate_status_transition", "memory_items_audit_insert",
    "memory_items_audit_update", "memory_conflicts_prevent_delete",
    "memory_conflicts_protect_closed_decision", "memory_conflicts_protect_history",
    "memory_conflicts_validate_insert", "memory_conflicts_validate_update",
    "memory_items_prevent_delete", "memory_items_validate_update",
]
EDITORIAL_TABLES = [
    "approvals", "audit_events", "daily_plans", "editorial_runs", "idempotency_keys",
    "material_versions", "materials", "plan_items", "publication_jobs", "research_items",
    "research_sources", "schema_migrations", "topic_proposals",
]
EDITORIAL_PROTECTIVE_TRIGGERS = ["audit_events_prevent_update", "audit_events_prevent_delete"]


def _migration_files(directory: Path) -> list[Path]:
    return sorted(path for path in directory.glob("*.sql") if path.stem.split("_", 1)[0].isdigit())


def _expected_migrations(files: list[Path]) -> list[dict[str, object]]:
    return [
        {
            "version": int(path.stem.split("_", 1)[0]),
            "name": path.name,
            "checksum": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in files
    ]


def _expected_triggers(files: list[Path]) -> dict[str, str]:
    database = sqlite3.connect(":memory:")
    try:
        for path in files:
            database.executescript(path.read_text(encoding="utf-8"))
        return {
            row[0]: normalize_sql(row[1])
            for row in database.execute(
                "SELECT name, sql FROM sqlite_master WHERE type = 'trigger' ORDER BY name"
            )
        }
    finally:
        database.close()


def _check_database(
    database_path: Path,
    migrations_path: Path,
    required_tables: list[str],
    trigger_names: list[str],
    reject_unexpected_triggers: bool,
    pending_migrations_path: Path | None = None,
) -> dict[str, object]:
    with read_only_database(database_path) as database:
        integrity = database.execute("PRAGMA integrity_check").fetchall()
        foreign_keys = database.execute("PRAGMA foreign_key_check").fetchall()
        tables = [row[0] for row in database.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )]
        migrations = [dict(row) for row in database.execute(
            "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
        )]
        applied_versions = {int(item["version"]) for item in migrations}
        migration_files = _migration_files(migrations_path)
        if pending_migrations_path is not None:
            migration_files.extend(
                path for path in _migration_files(pending_migrations_path)
                if int(path.stem.split("_", 1)[0]) in applied_versions
            )
        migration_files.sort(key=lambda path: int(path.stem.split("_", 1)[0]))
        expected_migrations = _expected_migrations(migration_files)
        expected_triggers = _expected_triggers(migration_files)
        triggers = {
            row[0]: normalize_sql(row[1])
            for row in database.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='trigger' ORDER BY name"
            )
        }
        if len(integrity) != 1 or integrity[0][0] != "ok":
            raise RuntimeError("Integrity check failed")
        if foreign_keys:
            raise RuntimeError("Foreign key check failed")
        if tables != sorted(required_tables):
            raise RuntimeError("Database table set differs from the required schema")
        if migrations != expected_migrations:
            raise RuntimeError("Applied migrations do not match migration files")
        for name in trigger_names:
            if triggers.get(name) != expected_triggers.get(name):
                raise RuntimeError(f"Protective trigger is invalid: {name}")
        if reject_unexpected_triggers and triggers != expected_triggers:
            raise RuntimeError("Database trigger set differs from migration files")
    return {
        "integrity": "ok",
        "migration_count": len(migrations),
        "tables": tables,
    }


def check_memory_database(path: Path = MEMORY_DATABASE) -> dict[str, object]:
    return _check_database(path, MEMORY_MIGRATIONS, MEMORY_TABLES, MEMORY_TRIGGERS, True)


def check_editorial_database(path: Path = EDITORIAL_DATABASE) -> dict[str, object]:
    if not path.is_file():
        return {
            "exists": False,
            "state": "paused",
            "integrity": "not_applicable",
            "migration_count": 0,
            "tables": [],
        }
    checked = _check_database(
        path, EDITORIAL_MIGRATIONS, EDITORIAL_TABLES,
        EDITORIAL_PROTECTIVE_TRIGGERS, False,
        EDITORIAL_MIGRATIONS.parent / "pending-migrations",
    )
    return {"exists": True, "state": "active", **checked}

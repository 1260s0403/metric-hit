from __future__ import annotations

import hashlib
from pathlib import Path

from .checks import check_editorial_database, check_memory_database
from .config import CURRENT_CONTEXT, EDITORIAL_DATABASE, MEMORY_DATABASE
from .database import read_only_database


def _status_counts(database, table: str, column: str = "status") -> dict[str, int]:
    return {
        row[0]: row[1]
        for row in database.execute(
            f"SELECT {column}, count(*) FROM {table} GROUP BY {column} ORDER BY {column}"
        )
    }


def memory_summary(path: Path = MEMORY_DATABASE) -> dict[str, object]:
    checked = check_memory_database(path)
    with read_only_database(path) as database:
        checked.update({
            "candidate_statuses": _status_counts(database, "memory_candidates"),
            "open_conflicts": database.execute(
                "SELECT count(*) FROM memory_conflicts WHERE status='open'"
            ).fetchone()[0],
            "open_tasks": database.execute(
                "SELECT count(*) FROM tasks WHERE status IN ('pending','in_progress')"
            ).fetchone()[0],
            "source_count": database.execute("SELECT count(*) FROM sources").fetchone()[0],
        })
    return checked


def editorial_status(path: Path = EDITORIAL_DATABASE) -> dict[str, object]:
    checked = check_editorial_database(path)
    entity_tables = [
        "editorial_runs", "daily_plans", "materials", "approvals", "publication_jobs"
    ]
    with read_only_database(path) as database:
        checked["entities"] = {
            table: {
                "count": database.execute(f"SELECT count(*) FROM {table}").fetchone()[0],
                "statuses": _status_counts(database, table),
            }
            for table in entity_tables
        }
    return checked


def current_context(path: Path = CURRENT_CONTEXT) -> dict[str, object]:
    if not path.is_file():
        return {"exists": False, "sha256": None, "content": None}
    content = path.read_text(encoding="utf-8")
    return {
        "exists": True,
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "content": content,
    }

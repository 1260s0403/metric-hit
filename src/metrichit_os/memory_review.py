from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .database import read_only_database


class MemoryReviewError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _required(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MemoryReviewError(f"{label} is required")
    return value.strip()


def _optional(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise MemoryReviewError("comment must be a string")
    return value.strip() or None


def _json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    parsed = json.loads(value)
    return parsed if isinstance(parsed, dict) else {}


class MemoryReviewStore:
    """Owner-only candidate review through the protected memory state machine."""

    def __init__(self, path: Path, context_path: Path | None = None):
        self.path = path
        self.context_path = context_path

    def candidates(self, query: str = "") -> list[dict[str, Any]]:
        pattern = f"%{query.strip()}%"
        with read_only_database(self.path) as connection:
            rows = connection.execute(
                """
                SELECT c.id,c.type,c.semantic_key,c.title,c.content,c.status,c.author,
                       c.created_at,c.updated_at,c.valid_at,c.version,
                       s.type source_type,s.title source_title,s.author source_author,
                       (SELECT count(*) FROM memory_conflicts x WHERE x.candidate_id=c.id AND x.status='open') conflict_count,
                       (SELECT t.title FROM tasks t
                        WHERE json_extract(t.data_json,'$.decision_candidate_id')=c.id
                           OR json_extract(c.data_json,'$.handoff_task_id')=t.id
                        ORDER BY t.created_at DESC LIMIT 1) task_title
                FROM memory_candidates c JOIN sources s ON s.id=c.source_id
                WHERE c.status='pending'
                  AND (?='' OR c.semantic_key LIKE ? OR c.title LIKE ? OR c.content LIKE ? OR s.title LIKE ?)
                ORDER BY c.created_at ASC,c.semantic_key ASC
                """,
                (query.strip(), pattern, pattern, pattern, pattern),
            ).fetchall()
        return [dict(row) for row in rows]

    def candidate(self, candidate_id: str) -> dict[str, Any]:
        with read_only_database(self.path) as connection:
            row = connection.execute(
                """
                SELECT c.*,s.type source_type,s.title source_title,s.content source_content,
                       s.author source_author,s.valid_at source_valid_at,
                       t.id task_id,t.title task_title,t.status task_status
                FROM memory_candidates c JOIN sources s ON s.id=c.source_id
                LEFT JOIN tasks t ON json_extract(t.data_json,'$.decision_candidate_id')=c.id
                                  OR json_extract(c.data_json,'$.handoff_task_id')=t.id
                WHERE c.id=? ORDER BY t.created_at DESC LIMIT 1
                """,
                (candidate_id,),
            ).fetchone()
            if row is None:
                raise MemoryReviewError("memory candidate not found")
            result = dict(row)
            result["data"] = _json_object(result.pop("data_json"))
            result["conflicts"] = [dict(item) for item in connection.execute(
                """
                SELECT x.id,x.status,x.title,x.resolution,m.title existing_title,m.content existing_content
                FROM memory_conflicts x JOIN memory_items m ON m.id=x.existing_memory_item_id
                WHERE x.candidate_id=? ORDER BY x.created_at,x.id
                """,
                (candidate_id,),
            ).fetchall()]
            return result

    def conflicts(self) -> list[dict[str, Any]]:
        with read_only_database(self.path) as connection:
            rows = connection.execute(
                """
                SELECT x.id,x.title,x.content,x.status,x.created_at,x.version,
                       c.id candidate_id,c.semantic_key,c.title candidate_title,c.content candidate_content,
                       m.id existing_memory_item_id,m.title existing_title,m.content existing_content,
                       s.title source_title,
                       (SELECT t.id FROM tasks t WHERE json_extract(t.data_json,'$.decision_candidate_id')=c.id
                        ORDER BY t.created_at DESC LIMIT 1) task_id,
                       (SELECT t.title FROM tasks t WHERE json_extract(t.data_json,'$.decision_candidate_id')=c.id
                        ORDER BY t.created_at DESC LIMIT 1) task_title
                FROM memory_conflicts x
                JOIN memory_candidates c ON c.id=x.candidate_id
                JOIN memory_items m ON m.id=x.existing_memory_item_id
                JOIN sources s ON s.id=x.source_id
                WHERE x.status='open' ORDER BY x.created_at,x.id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def approve(self, candidate_id: str, comment: object = None) -> dict[str, Any]:
        return self._review(candidate_id, "approved", _optional(comment))

    def reject(self, candidate_id: str, reason: object) -> dict[str, Any]:
        return self._review(candidate_id, "rejected", _required(reason, "rejection reason"))

    def _review(self, candidate_id: str, status: str, note: str | None) -> dict[str, Any]:
        now = _now()
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM memory_candidates WHERE id=?", (candidate_id,)).fetchone()
            if row is None:
                raise MemoryReviewError("memory candidate not found")
            if row["status"] != "pending":
                raise MemoryReviewError("only pending candidates can be reviewed")
            if status == "approved":
                self._validate_semantic_integrity(connection, row)
            changed = connection.execute(
                """UPDATE memory_candidates SET status=?,reviewed_by='owner',reviewed_at=?,review_note=?,
                          updated_at=?,version=version+1 WHERE id=? AND status='pending'""",
                (status, now, note, now, candidate_id),
            ).rowcount
            if changed != 1:
                raise MemoryReviewError("candidate review was not applied")
            self._audit(
                connection, entity_type="memory_candidate", entity_id=candidate_id,
                title="Memory candidate reviewed", source_id=str(row["source_id"]),
                data={"old": {"status": "pending"}, "new": {"status": status, "reviewed_by": "owner", "reviewed_at": now, "review_note": note}},
            )
        if status == "approved":
            self.export_current_context()
        return self.candidate(candidate_id)

    @staticmethod
    def _validate_semantic_integrity(connection: sqlite3.Connection, candidate: sqlite3.Row) -> None:
        competing_pending = connection.execute(
            "SELECT 1 FROM memory_candidates WHERE semantic_key=? AND status='pending' AND id<>? LIMIT 1",
            (candidate["semantic_key"], candidate["id"]),
        ).fetchone()
        if competing_pending:
            raise MemoryReviewError("another pending candidate has the same semantic key")
        approved = connection.execute(
            "SELECT id FROM memory_candidates WHERE semantic_key=? AND status='approved' AND id<>? ORDER BY reviewed_at DESC,updated_at DESC,id DESC",
            (candidate["semantic_key"], candidate["id"]),
        ).fetchall()
        if not approved:
            return
        supersedes = _json_object(candidate["data_json"]).get("supersedes_candidate_id")
        if not isinstance(supersedes, str) or supersedes != approved[0]["id"]:
            raise MemoryReviewError("approved memory with this semantic key exists; create an explicit evolution candidate")

    def resolve(self, conflict_id: str, outcome: object, reason: object) -> dict[str, Any]:
        decision = _required(outcome, "conflict outcome")
        if decision not in {"candidate", "existing"}:
            raise MemoryReviewError("conflict outcome must be candidate or existing")
        explanation = _required(reason, "conflict resolution reason")
        now = _now()
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT x.*,c.type candidate_type,c.semantic_key,c.title candidate_title,
                          c.content candidate_content,c.data_json candidate_data_json,
                          c.source_id candidate_source_id,c.valid_at candidate_valid_at,
                          c.access_level candidate_access_level,m.status existing_status
                   FROM memory_conflicts x JOIN memory_candidates c ON c.id=x.candidate_id
                   JOIN memory_items m ON m.id=x.existing_memory_item_id WHERE x.id=?""",
                (conflict_id,),
            ).fetchone()
            if row is None:
                raise MemoryReviewError("memory conflict not found")
            if row["status"] != "open":
                raise MemoryReviewError("only open conflicts can be resolved")
            if decision == "candidate":
                if row["existing_status"] != "active":
                    raise MemoryReviewError("conflicting memory item is no longer active")
                connection.execute(
                    "UPDATE memory_items SET status='superseded',updated_at=?,version=version+1 WHERE id=? AND status='active'",
                    (now, row["existing_memory_item_id"]),
                )
                connection.execute(
                    """INSERT INTO memory_items
                       (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version)
                       VALUES (?,?,?,?,?,?,'active',?,'owner',?,?,1)""",
                    (str(uuid.uuid4()), row["candidate_type"], row["semantic_key"], row["candidate_title"],
                     row["candidate_content"], row["candidate_data_json"], row["candidate_source_id"],
                     row["candidate_valid_at"], row["candidate_access_level"]),
                )
                status = "resolved"
                resolution = f"Выбран кандидат. Причина: {explanation}"
            else:
                status = "dismissed"
                resolution = f"Сохранена текущая запись. Причина: {explanation}"
            connection.execute(
                "UPDATE memory_conflicts SET status=?,resolution=?,updated_at=?,version=version+1 WHERE id=? AND status='open'",
                (status, resolution, now, conflict_id),
            )
            self._audit(
                connection, entity_type="memory_conflict", entity_id=conflict_id,
                title="Memory conflict resolved", source_id=str(row["source_id"]),
                data={"old": {"status": "open"}, "new": {"status": status, "outcome": decision, "resolution": resolution}},
            )
        self.export_current_context()
        return {"id": conflict_id, "status": status, "outcome": decision, "resolution": resolution}

    def export_current_context(self) -> None:
        if self.context_path is None:
            return
        content = build_current_context(self.path)
        self.context_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.context_path.with_suffix(self.context_path.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(self.context_path)

    @staticmethod
    def _audit(
        connection: sqlite3.Connection, *, entity_type: str, entity_id: str,
        title: str, source_id: str, data: dict[str, Any],
    ) -> None:
        connection.execute(
            """INSERT INTO audit_log
               (id,type,title,data_json,source_id,author,entity_type,entity_id,action)
               VALUES (?,'memory_review',?,?,?,'owner',?,?,'update')""",
            (str(uuid.uuid4()), title, json.dumps(data, ensure_ascii=False, sort_keys=True), source_id, entity_type, entity_id),
        )


def build_current_context(database_path: Path, generated_at: str | None = None) -> str:
    generated = generated_at or _now()

    def section(connection: sqlite3.Connection, heading: str, types: tuple[str, ...]) -> str:
        placeholders = ",".join("?" for _ in types)
        editorial_exclusion = ""
        if "editorial_rule" in types:
            editorial_exclusion = """
              AND semantic_key NOT IN (
                SELECT value FROM memory_candidates policies,json_each(policies.data_json,'$.supersedes_editorial_rules')
                WHERE policies.status='approved' AND policies.semantic_key='content.editorial_directness_policy'
              )
            """
        rows = connection.execute(
            f"""
            SELECT title,content FROM (
              SELECT title,content,semantic_key,
                     ROW_NUMBER() OVER (PARTITION BY semantic_key ORDER BY reviewed_at DESC,updated_at DESC,id DESC) revision_rank
              FROM memory_candidates c
              WHERE status='approved' AND type IN ({placeholders})
                AND NOT EXISTS (
                  SELECT 1 FROM memory_conflicts x
                  WHERE x.candidate_id=c.id AND x.status IN ('open','dismissed')
                )
              {editorial_exclusion}
            ) WHERE revision_rank=1 ORDER BY semantic_key
            """,
            types,
        ).fetchall()
        body = "\n".join(f"- **{row['title']}:** {row['content']}" for row in rows) if rows else "- Нет утверждённых записей."
        return f"## {heading}\n\n{body}"

    with read_only_database(database_path) as connection:
        task_rows = connection.execute(
            "SELECT title,content FROM tasks WHERE status IN ('pending','in_progress') ORDER BY created_at,title"
        ).fetchall()
        tasks = "\n".join(f"- **{row['title']}:** {row['content']}" for row in task_rows) if task_rows else "- Нет открытых задач."
        return "\n".join((
            "# MetricHit — текущий рабочий контекст",
            "",
            f"Сформировано: {generated}. Этот файл содержит только утверждённую память. Задачи и планы вынесены в отдельный раздел и не являются реализованными фактами.",
            "",
            section(connection, "Основные факты о продукте", ("product_fact",)),
            "",
            section(connection, "Коммерческие условия", ("commercial_terms",)),
            "",
            section(connection, "Официальные ресурсы и каналы", ("official_resource", "official_channel")),
            "",
            section(connection, "Действующие решения", ("decision", "ai_policy")),
            "",
            section(connection, "Редакционные правила", ("editorial_rule",)),
            "",
            section(connection, "Подтверждённые публикации и площадки", ("publication_state",)),
            "",
            "## Открытые задачи и планы",
            "",
            tasks,
            "",
        ))

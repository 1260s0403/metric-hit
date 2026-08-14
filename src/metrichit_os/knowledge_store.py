from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


KNOWLEDGE_KINDS = {
    "artem": "artem_recommendation",
    "idea": "owner_idea",
}
KNOWLEDGE_STATUSES = {"active", "converted_to_task", "archived"}


class KnowledgeError(ValueError):
    pass


def _utc_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _kind(value: str) -> str:
    try:
        return KNOWLEDGE_KINDS[value]
    except KeyError as error:
        raise KnowledgeError("kind must be artem or idea") from error


def _status(value: str) -> str:
    if value not in KNOWLEDGE_STATUSES:
        raise KnowledgeError("status must be active, converted_to_task, or archived")
    return value


def _tags(value: str | None) -> list[str]:
    if not value:
        return []
    return [tag.strip() for tag in value.split(",") if tag.strip()]


class KnowledgeStore:
    def __init__(self, database_path: Path):
        self.path = database_path.resolve()
        if not self.path.is_file():
            raise FileNotFoundError("Database does not exist")

    def add(
        self,
        *,
        kind: str,
        text: str,
        topic: str,
        tags: str | None = None,
        author: str = "owner",
        source: str = "manual",
        status: str = "active",
    ) -> dict[str, object]:
        stored_kind = _kind(kind)
        stored_status = _status(status)
        if not text.strip() or not topic.strip() or not author.strip() or not source.strip():
            raise KnowledgeError("text, topic, author, and source must not be empty")
        entry_id = str(uuid4())
        created_at = _utc_text()
        metadata = {
            "kind": stored_kind,
            "topic": topic.strip(),
            "tags": _tags(tags),
            "source": source.strip(),
            "knowledge_status": stored_status,
        }
        document_status = "archived" if stored_status == "archived" else "active"
        with sqlite3.connect(self.path) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(
                """
                INSERT INTO documents
                  (id, type, title, content, data_json, status, author, created_at, updated_at, access_level, version)
                VALUES (?, 'knowledge_entry', ?, ?, ?, ?, ?, ?, ?, 'internal', 1)
                """,
                (
                    entry_id, topic.strip(), text, json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                    document_status, author.strip(), created_at, created_at,
                ),
            )
        return self._entry({
            "id": entry_id,
            "title": topic.strip(),
            "content": text,
            "data_json": json.dumps(metadata, ensure_ascii=False, sort_keys=True),
            "author": author.strip(),
            "created_at": created_at,
        })

    def list(self, *, kind: str, limit: int = 20) -> list[dict[str, object]]:
        stored_kind = _kind(kind)
        if not 1 <= limit <= 100:
            raise KnowledgeError("limit must be between 1 and 100")
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT id, title, content, data_json, author, created_at
                FROM documents
                WHERE type='knowledge_entry' AND json_extract(data_json, '$.kind')=?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (stored_kind, limit),
            ).fetchall()
        return [self._entry(dict(row)) for row in rows]

    def search(self, *, kind: str, query: str, limit: int = 20) -> list[dict[str, object]]:
        stored_kind = _kind(kind)
        if not query.strip():
            raise KnowledgeError("query must not be empty")
        if not 1 <= limit <= 100:
            raise KnowledgeError("limit must be between 1 and 100")
        pattern = f"%{query.strip()}%"
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT id, title, content, data_json, author, created_at
                FROM documents
                WHERE type='knowledge_entry'
                  AND json_extract(data_json, '$.kind')=?
                  AND (content LIKE ? COLLATE NOCASE OR title LIKE ? COLLATE NOCASE)
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (stored_kind, pattern, pattern, limit),
            ).fetchall()
        return [self._entry(dict(row)) for row in rows]

    def to_task(self, *, entry_id: str, title: str | None = None) -> dict[str, object]:
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            entry = connection.execute(
                "SELECT id, type, title, content, data_json, author FROM documents WHERE id=?",
                (entry_id,),
            ).fetchone()
            if entry is None:
                raise KnowledgeError("knowledge entry was not found")
            if entry["type"] != "knowledge_entry":
                raise KnowledgeError("document is not a supported knowledge entry")
            metadata = json.loads(entry["data_json"])
            kind = metadata.get("kind")
            if kind not in set(KNOWLEDGE_KINDS.values()):
                raise KnowledgeError("document is not a supported knowledge entry")
            existing = connection.execute(
                """
                SELECT id, type, title, content, data_json, status, author, created_at
                FROM tasks WHERE json_extract(data_json, '$.knowledge_entry_id')=?
                """,
                (entry_id,),
            ).fetchone()
            if existing is not None:
                return self._task(dict(existing))
            task_id = str(uuid4())
            created_at = _utc_text()
            task_metadata = {
                "knowledge_entry_id": entry_id,
                "knowledge_kind": kind,
                "knowledge_tags": metadata.get("tags", []),
                "knowledge_topic": metadata.get("topic", entry["title"]),
            }
            task_title = title.strip() if title and title.strip() else entry["title"]
            connection.execute(
                """
                INSERT INTO tasks
                  (id, type, title, content, data_json, status, author, created_at, updated_at, access_level, version)
                VALUES (?, 'knowledge_task', ?, ?, ?, 'pending', ?, ?, ?, 'internal', 1)
                """,
                (
                    task_id, task_title, entry["content"],
                    json.dumps(task_metadata, ensure_ascii=False, sort_keys=True),
                    entry["author"], created_at, created_at,
                ),
            )
            return self._task({
                "id": task_id, "type": "knowledge_task", "title": task_title,
                "content": entry["content"], "data_json": json.dumps(task_metadata, ensure_ascii=False, sort_keys=True),
                "status": "pending", "author": entry["author"], "created_at": created_at,
            })

    @staticmethod
    def _entry(row: dict[str, object]) -> dict[str, object]:
        metadata = json.loads(str(row["data_json"]))
        return {
            "author": row["author"],
            "created_at": row["created_at"],
            "id": row["id"],
            "kind": metadata["kind"],
            "source": metadata["source"],
            "status": metadata["knowledge_status"],
            "tags": metadata["tags"],
            "text": row["content"],
            "topic": metadata["topic"],
        }

    @staticmethod
    def _task(row: dict[str, object]) -> dict[str, object]:
        metadata = json.loads(str(row["data_json"]))
        return {
            "author": row["author"],
            "content": row["content"],
            "created_at": row["created_at"],
            "id": row["id"],
            "knowledge_entry_id": metadata["knowledge_entry_id"],
            "knowledge_kind": metadata["knowledge_kind"],
            "knowledge_tags": metadata["knowledge_tags"],
            "knowledge_topic": metadata["knowledge_topic"],
            "status": row["status"],
            "title": row["title"],
            "type": row["type"],
        }

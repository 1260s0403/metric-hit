from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, datetime, timezone
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


def _task_title(text: str, limit: int = 80) -> str:
    sentence = re.split(r"(?<=[.!?])\s+", " ".join(text.split()), maxsplit=1)[0]
    return sentence if len(sentence) <= limit else sentence[: limit - 1].rstrip() + "…"


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
            connection.execute(
                "INSERT INTO audit_log (id,type,title,data_json,author,created_at,updated_at,access_level,version,entity_type,entity_id,action) VALUES (?, 'knowledge_entry_change','Knowledge entry created',?,?,?,?,'restricted',1,'knowledge_entry',?,'create')",
                (str(uuid4()), json.dumps({"new": {**metadata, "id": entry_id, "title": topic.strip(), "content": text}}, ensure_ascii=False, sort_keys=True), author.strip(), created_at, created_at, entry_id),
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

    def _to_task(
        self, *, entry_id: str, title: str | None = None, description: str | None = None,
        priority: str = "normal", due_date: str | None = None,
    ) -> dict[str, object]:
        due_date = self._normalize_due_date(due_date)
        self._validate_task_fields(title=title or "x", priority=priority, due_date=due_date)
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("BEGIN IMMEDIATE")
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
                return self._task(dict(existing)), False
            task_id = str(uuid4())
            created_at = _utc_text()
            task_description = description if description is not None else entry["content"]
            task_metadata = {
                "knowledge_entry_id": entry_id,
                "knowledge_kind": kind,
                "knowledge_tags": metadata.get("tags", []),
                "knowledge_topic": metadata.get("topic", entry["title"]),
                "priority": priority,
                "due_date": due_date,
            }
            task_title = title.strip() if title and title.strip() else _task_title(task_description)
            connection.execute(
                """
                INSERT INTO tasks
                  (id, type, title, content, data_json, status, author, created_at, updated_at, access_level, version)
                VALUES (?, 'knowledge_task', ?, ?, ?, 'pending', ?, ?, ?, 'internal', 1)
                """,
                (
                    task_id, task_title, task_description,
                    json.dumps(task_metadata, ensure_ascii=False, sort_keys=True),
                    entry["author"], created_at, created_at,
                ),
            )
            connection.execute(
                "INSERT INTO audit_log (id,type,title,data_json,author,created_at,updated_at,access_level,version,entity_type,entity_id,action) VALUES (?, 'task_change','Knowledge task created',?,?,?,?,'restricted',1,'task',?,'create')",
                (str(uuid4()), json.dumps({"new": {"title": task_title, "description": task_description, "priority": priority, "due_date": due_date}}, ensure_ascii=False, sort_keys=True), entry["author"], created_at, created_at, task_id),
            )
            task = self._task({
                "id": task_id, "type": "knowledge_task", "title": task_title,
                "content": task_description, "data_json": json.dumps(task_metadata, ensure_ascii=False, sort_keys=True),
                "status": "pending", "author": entry["author"], "created_at": created_at,
            })
            return task, True

    def to_task(
        self, *, entry_id: str, title: str | None = None, description: str | None = None,
        priority: str = "normal", due_date: str | None = None,
    ) -> dict[str, object]:
        task, _ = self._to_task(
            entry_id=entry_id, title=title, description=description, priority=priority, due_date=due_date,
        )
        return task

    def to_task_with_created(
        self, *, entry_id: str, title: str | None = None, description: str | None = None,
        priority: str = "normal", due_date: str | None = None,
    ) -> tuple[dict[str, object], bool]:
        return self._to_task(
            entry_id=entry_id, title=title, description=description, priority=priority, due_date=due_date,
        )

    def create_task(
        self, *, title: str, description: str, priority: str = "normal", due_date: str | None = None,
        author: str = "owner",
    ) -> dict[str, object]:
        due_date = self._normalize_due_date(due_date)
        self._validate_task_fields(title=title, priority=priority, due_date=due_date)
        task_id = str(uuid4())
        created_at = _utc_text()
        metadata = {"priority": priority, "due_date": due_date, "standalone": True}
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """INSERT INTO tasks
                   (id, type, title, content, data_json, status, author, created_at, updated_at, access_level, version)
                   VALUES (?, 'standalone_task', ?, ?, ?, 'pending', ?, ?, ?, 'internal', 1)""",
                (task_id, title.strip(), description, json.dumps(metadata, ensure_ascii=False, sort_keys=True), author, created_at, created_at),
            )
            connection.execute(
                "INSERT INTO audit_log (id,type,title,data_json,author,created_at,updated_at,access_level,version,entity_type,entity_id,action) VALUES (?, 'task_change','Knowledge task created',?,?,?,?,'restricted',1,'task',?,'create')",
                (str(uuid4()), json.dumps({"new": {"title": title.strip(), "description": description, "priority": priority, "due_date": due_date}}, ensure_ascii=False, sort_keys=True), author, created_at, created_at, task_id),
            )
        return self._task({"id": task_id, "type": "standalone_task", "title": title.strip(), "content": description,
                           "data_json": json.dumps(metadata), "status": "pending", "author": author, "created_at": created_at,
                           "updated_at": created_at})

    def list_tasks(self, *, query: str = "", status: str = "all", priority: str = "all", due: str = "all", sort: str = "recommended", project: str = "all") -> list[dict[str, object]]:
        if status not in {"all", "open", "completed", "cancelled"} or priority not in {"all", "high", "normal", "low"} or due not in {"all", "overdue", "today", "week", "none"} or sort not in {"recommended", "due", "priority", "newest", "oldest"}:
            raise KnowledgeError("invalid task filter")
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT tasks.id, tasks.type, tasks.title, tasks.content, tasks.data_json, tasks.status,
                       tasks.author, tasks.created_at, tasks.updated_at, documents.content AS source_text
                FROM tasks LEFT JOIN documents ON documents.id=json_extract(tasks.data_json, '$.knowledge_entry_id')
                WHERE (tasks.type='knowledge_task'
                  AND json_extract(tasks.data_json, '$.knowledge_kind') IN ('artem_recommendation', 'owner_idea'))
                   OR tasks.type='standalone_task'
                ORDER BY tasks.created_at DESC, tasks.id DESC
                """
            ).fetchall()
        tasks = [self._task(dict(row)) for row in rows]
        today = date.today()
        def match(item):
            if query.casefold() not in (str(item["title"]) + " " + str(item["description"])).casefold(): return False
            if status != "all" and item["status"] != status: return False
            if priority != "all" and item["priority"] != priority: return False
            if project == "none" and item.get("project_id"): return False
            if project not in {"all", "none"} and item.get("project_id") != project: return False
            value = item["due_date"]
            if due == "none" and value is not None: return False
            if due == "overdue" and not (value and date.fromisoformat(str(value)) < today): return False
            if due == "today" and value != today.isoformat(): return False
            if due == "week" and not (value and today <= date.fromisoformat(str(value)) <= date.fromordinal(today.toordinal() + 7)): return False
            return True
        tasks = [item for item in tasks if match(item)]
        rank = {"high": 0, "normal": 1, "low": 2}
        def recommended(item):
            value = item["due_date"]
            if item["status"] != "open": return (7, "", -str(item.get("updated_at", "")).__len__())
            if value:
                due_date = date.fromisoformat(str(value))
                return (0 if due_date < today else 1 if due_date == today else 2, value, "")
            return (3 + rank[item["priority"]], "", "")
        if sort == "recommended": tasks.sort(key=recommended)
        elif sort == "due": tasks.sort(key=lambda item: (item["due_date"] is None, item["due_date"] or "9999-12-31"))
        elif sort == "priority": tasks.sort(key=lambda item: rank[item["priority"]])
        elif sort == "newest": tasks.sort(key=lambda item: str(item["created_at"]), reverse=True)
        elif sort == "oldest": tasks.sort(key=lambda item: str(item["created_at"]))
        return tasks

    def today_tasks(self) -> list[dict[str, object]]:
        current = date.today()
        tasks = self.list_tasks(status="open")
        urgent = [item for item in tasks if item["due_date"] and date.fromisoformat(str(item["due_date"])) <= current]
        high = [item for item in tasks if item["due_date"] is None and item["priority"] == "high"][:5]
        return urgent + high

    def edit_task(self, *, task_id: str, title: str, description: str, priority: str, due_date: str | None) -> dict[str, object]:
        due_date = self._normalize_due_date(due_date)
        self._validate_task_fields(title=title, priority=priority, due_date=due_date)
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row; connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM tasks WHERE id=? AND type IN ('knowledge_task', 'standalone_task')", (task_id,)).fetchone()
            if row is None: raise KnowledgeError("knowledge task was not found")
            metadata = json.loads(row["data_json"])
            if row["type"] == "knowledge_task" and metadata.get("knowledge_kind") not in set(KNOWLEDGE_KINDS.values()): raise KnowledgeError("knowledge task was not found")
            old = self._task(dict(row)); metadata.update(priority=priority, due_date=due_date)
            now = _utc_text(); version = row["version"] + 1
            connection.execute("UPDATE tasks SET title=?, content=?, data_json=?, updated_at=?, version=? WHERE id=?", (title.strip(), description, json.dumps(metadata, ensure_ascii=False, sort_keys=True), now, version, task_id))
            connection.execute("INSERT INTO audit_log (id,type,title,data_json,author,created_at,updated_at,access_level,version,entity_type,entity_id,action) VALUES (?, 'task_change','Knowledge task edited',?,?,?,?,'restricted',1,'task',?,'update')", (str(uuid4()), json.dumps({"old": {key: old[key] for key in ("title","description","priority","due_date")}, "new": {"title": title.strip(), "description": description, "priority": priority, "due_date": due_date}}, ensure_ascii=False, sort_keys=True), row["author"], now, now, task_id))
            changed = dict(row); changed.update(title=title.strip(), content=description, data_json=json.dumps(metadata), updated_at=now, version=version)
            return self._task(changed)

    def task_for_entry(self, entry_id: str) -> dict[str, object] | None:
        return next((task for task in self.list_tasks() if task["knowledge_entry_id"] == entry_id), None)

    def set_task_status(self, *, task_id: str, status: str) -> dict[str, object]:
        if status not in {"completed", "cancelled"}:
            raise KnowledgeError("status must be completed or cancelled")
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("BEGIN IMMEDIATE")
            task = connection.execute(
                """
                SELECT id, type, title, content, data_json, status, author, created_at, updated_at, version
                FROM tasks WHERE id=?
                """,
                (task_id,),
            ).fetchone()
            if task is None or task["type"] not in {"knowledge_task", "standalone_task"}:
                raise KnowledgeError("knowledge task was not found")
            metadata = json.loads(task["data_json"])
            if task["type"] == "knowledge_task" and metadata.get("knowledge_kind") not in set(KNOWLEDGE_KINDS.values()):
                raise KnowledgeError("knowledge task was not found")
            if task["status"] == status:
                return self._task(dict(task))
            if task["status"] not in {"pending", "in_progress"}:
                raise KnowledgeError("closed task cannot change status")
            updated_at = _utc_text()
            new_version = task["version"] + 1
            connection.execute(
                "UPDATE tasks SET status=?, updated_at=?, version=? WHERE id=?",
                (status, updated_at, new_version, task_id),
            )
            connection.execute(
                """
                INSERT INTO audit_log
                  (id, type, title, data_json, author, created_at, updated_at, access_level, version, entity_type, entity_id, action)
                VALUES (?, 'task_change', 'Knowledge task status updated', ?, ?, ?, ?, 'restricted', 1, 'task', ?, 'update')
                """,
                (
                    str(uuid4()),
                    json.dumps({
                        "new": {"status": status, "updated_at": updated_at, "version": new_version},
                        "old": {"status": task["status"], "updated_at": task["updated_at"], "version": task["version"]},
                    }, ensure_ascii=False, sort_keys=True),
                    task["author"], updated_at, updated_at, task_id,
                ),
            )
            changed = dict(task)
            changed.update(status=status, updated_at=updated_at, version=new_version)
            return self._task(changed)

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
        description = row["content"]
        display_title = row["title"]
        if display_title.casefold() in {"панель", "кейс", "статьи"}:
            display_title = f"{display_title} — {_task_title(description)}"
        return {
            "author": row["author"],
            "content": row["content"],
            "description": description,
            "display_title": display_title,
            "priority": metadata.get("priority", "normal"),
            "project_id": metadata.get("project_id"),
            "due_date": metadata.get("due_date"),
            "created_at": row["created_at"],
            "id": row["id"],
            "knowledge_entry_id": metadata.get("knowledge_entry_id"),
            "knowledge_kind": metadata.get("knowledge_kind"),
            "knowledge_tags": metadata.get("knowledge_tags", []),
            "knowledge_topic": metadata.get("knowledge_topic"),
            "status": "open" if row["status"] in {"pending", "in_progress"} else row["status"],
            "source": ("Рекомендация Артёма" if metadata.get("knowledge_kind") == "artem_recommendation" else "Моя идея") if metadata.get("knowledge_kind") else "Самостоятельная задача",
            "title": row["title"],
            "type": row["type"],
            "updated_at": row.get("updated_at", row["created_at"]),
        }

    @staticmethod
    def _validate_task_fields(*, title: str, priority: str, due_date: str | None) -> None:
        if not title.strip():
            raise KnowledgeError("title must not be empty")
        if priority not in {"high", "normal", "low"}:
            raise KnowledgeError("priority must be high, normal, or low")
        if due_date:
            try:
                date.fromisoformat(due_date)
            except ValueError as error:
                raise KnowledgeError("due_date must be YYYY-MM-DD") from error

    @staticmethod
    def _normalize_due_date(value: str | None) -> str | None:
        return None if value is None or not value.strip() else value

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .database import read_only_database


SEARCH_TYPES = {"all", "artem", "idea", "task", "fact", "decision", "document"}
SEARCH_STATUSES = {"all", "open", "completed", "cancelled", "active"}
MAX_RESULTS = 50


def normalize(value: str) -> str:
    return " ".join(value.casefold().replace("ё", "е").split())


def _tags(data_json: str) -> list[str]:
    try:
        metadata = json.loads(data_json)
        value = []
        for key in ("tags", "knowledge_tags"):
            if isinstance(metadata.get(key), list):
                value.extend(metadata[key])
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return [str(tag) for tag in value] if isinstance(value, list) else []


def _data(data_json: object) -> dict[str, object]:
    try:
        value = json.loads(str(data_json))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _snippet(text: str, query: str, limit: int = 180) -> str:
    match = re.search(r"\s+".join(re.escape(part) for part in normalize(query).split()), text.casefold().replace("ё", "е"))
    if match is None:
        return text[:limit].strip() + ("…" if len(text) > limit else "")
    start = max(0, match.start() - (limit // 2))
    end = min(len(text), start + limit)
    start = text.find(" ", start) + 1 if start else 0
    value = text[start:end].strip()
    return ("…" if start else "") + value + ("…" if end < len(text) else "")


def _record(*, item_type: str, row: Any, title: str, text: str, tags: list[str], status: str, date: str, project_id: str | None = None, project_name: str | None = None) -> dict[str, object]:
    return {
        "id": str(row["id"]), "type": item_type, "title": title, "text": text,
        "tags": tags, "status": status, "date": date,
        "project_id": project_id, "project_name": project_name,
    }


def search(database_path: Path, *, query: str, item_type: str = "all", status: str = "all") -> list[dict[str, object]]:
    if item_type not in SEARCH_TYPES or status not in SEARCH_STATUSES:
        raise ValueError("invalid search filter")
    normalized_query = normalize(query)
    if not normalized_query:
        return []
    records: list[dict[str, object]] = []
    with read_only_database(database_path) as database:
        projects = {str(row["id"]): str(row["title"]) for row in database.execute("SELECT id,title FROM documents WHERE type='project'")}
        for row in database.execute("SELECT id,title,content,data_json,status,created_at,updated_at FROM documents WHERE type='knowledge_entry'"):
            try:
                data = json.loads(row["data_json"])
            except (TypeError, ValueError, json.JSONDecodeError):
                data = {}
            kind = "artem" if data.get("kind") == "artem_recommendation" else "idea" if data.get("kind") == "owner_idea" else None
            if kind:
                project_id = data.get("project_id")
                records.append(_record(item_type=kind, row=row, title=str(row["title"]), text=str(row["content"]), tags=_tags(row["data_json"]), status=str(data.get("knowledge_status", row["status"])), date=str(row["updated_at"] or row["created_at"]), project_id=str(project_id) if project_id else None, project_name=projects.get(str(project_id))))
        for row in database.execute("SELECT id,title,content,data_json,status,created_at,updated_at FROM tasks WHERE type IN ('knowledge_task','standalone_task')"):
            task_status = "open" if row["status"] in {"pending", "in_progress"} else str(row["status"])
            metadata = _data(row["data_json"])
            project_id = metadata.get("project_id")
            records.append(_record(item_type="task", row=row, title=str(row["title"]), text=str(row["content"]), tags=_tags(row["data_json"]), status=task_status, date=str(row["updated_at"] or row["created_at"]), project_id=str(project_id) if project_id else None, project_name=projects.get(str(project_id))))
        for row in database.execute("SELECT id,semantic_key,title,content,status,updated_at FROM memory_items WHERE status='active'"):
            records.append(_record(item_type="fact", row=row, title=str(row["title"]), text=f"{row['semantic_key']}\n{row['content']}", tags=[], status="active", date=str(row["updated_at"])))
        for row in database.execute("SELECT id,title,content,status,updated_at FROM decisions WHERE status='active'"):
            records.append(_record(item_type="decision", row=row, title=str(row["title"]), text=str(row["content"]), tags=[], status="active", date=str(row["updated_at"])))
        for row in database.execute("SELECT id,title,content,data_json,status,created_at,updated_at FROM documents WHERE type!='knowledge_entry' AND status='active'"):
            records.append(_record(item_type="document", row=row, title=str(row["title"]), text=str(row["content"]), tags=_tags(row["data_json"]), status="active", date=str(row["updated_at"] or row["created_at"])))

    results: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for record in records:
        if item_type != "all" and record["type"] != item_type:
            continue
        if status != "all" and record["status"] != status:
            continue
        title = normalize(str(record["title"]))
        text = normalize(str(record["text"]))
        tags = normalize(" ".join(str(tag) for tag in record["tags"]))
        if normalized_query == title:
            rank = 0
        elif normalized_query in title:
            rank = 1
        elif normalized_query in text or normalized_query in tags:
            rank = 2
        else:
            continue
        identity = (str(record["type"]), str(record["id"]))
        if identity in seen:
            continue
        seen.add(identity)
        results.append({**record, "rank": rank, "snippet": _snippet(str(record["text"]), query)})
    results.sort(key=lambda item: str(item["date"]), reverse=True)
    results.sort(key=lambda item: int(item["rank"]))
    return results[:MAX_RESULTS]

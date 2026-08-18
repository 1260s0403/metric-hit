from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .database import read_only_database


def _data(value: object) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _kind(payload: dict[str, Any]) -> str | None:
    value = payload.get("kind") or payload.get("knowledge_kind")
    return "artem" if value == "artem_recommendation" else "idea" if value == "owner_idea" else None


def _status(value: object) -> str:
    return {"pending": "Открыта", "in_progress": "Открыта", "completed": "Выполнена", "cancelled": "Отменена"}.get(str(value), str(value))


def _human_field(key: str, value: object) -> str:
    if key == "status": return _status(value)
    if key == "priority": return {"high": "Высокий", "normal": "Обычный", "low": "Низкий"}.get(str(value), str(value))
    if key == "due_date": return str(value or "Без срока")
    return str(value or "—")


def _changes(payload: dict[str, Any]) -> list[dict[str, str]]:
    old, new = payload.get("old"), payload.get("new")
    if not isinstance(old, dict) or not isinstance(new, dict): return []
    names = {"title": "Название", "name": "Название", "description": "Описание", "content": "Описание", "priority": "Приоритет", "due_date": "Срок", "status": "Статус", "project_id": "Проект"}
    result = []
    for key in names:
        before, after = old.get(key), new.get(key)
        if before != after and (key in old or key in new): result.append({"field": names[key], "old": _human_field(key, before), "new": _human_field(key, after)})
    return result


def _timestamp(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def list_activity(database_path: Path, *, period: str = "all", item_type: str = "all", action: str = "all", project: str = "all", offset: int = 0, limit: int = 50) -> dict[str, object]:
    if period not in {"today", "7", "30", "all"} or item_type not in {"all", "task", "artem", "idea", "memory", "project"} or action not in {"all", "create", "update", "completed", "cancelled"} or offset < 0 or not 1 <= limit <= 50:
        raise ValueError("invalid activity filter")
    now = datetime.now(timezone.utc)
    cutoff = None if period == "all" else (now.replace(hour=0, minute=0, second=0, microsecond=0) if period == "today" else now - timedelta(days=int(period)))
    items: list[dict[str, object]] = []
    with read_only_database(database_path) as db:
        project_names = {str(row["id"]): str(row["title"]) for row in db.execute("SELECT id,title FROM documents WHERE type='project'")}
        rows = db.execute("SELECT id,type,title,data_json,author,entity_type,entity_id,action,created_at FROM audit_log ORDER BY created_at DESC, id DESC").fetchall()
        for row in rows:
            created_at = _timestamp(row["created_at"])
            if cutoff and (created_at is None or created_at < cutoff): continue
            payload = _data(row["data_json"]); entity = str(row["entity_type"]); target_type = "unknown"
            title = str(row["title"]); target_view = None; target_id = str(row["entity_id"]); current = None
            project_id = None
            subproject_id = None
            if entity == "task":
                target_type, target_view = "task", "tasks"
                current = db.execute("SELECT title,data_json FROM tasks WHERE id=?", (target_id,)).fetchone(); title = str(current["title"]) if current else title
                if current:
                    metadata = _data(current["data_json"])
                    project_id, subproject_id = metadata.get("project_id"), metadata.get("subproject_id")
            elif entity in {"knowledge_entry", "document"}:
                kind = _kind(payload.get("new", payload))
                if kind:
                    target_type, target_view = kind, kind
                current = db.execute("SELECT title,data_json FROM documents WHERE id=?", (target_id,)).fetchone(); title = str(current["title"]) if current else title
                if current:
                    metadata = _data(current["data_json"])
                    project_id, subproject_id = metadata.get("project_id"), metadata.get("subproject_id")
            elif entity == "memory_item":
                target_type = "memory"
                current = db.execute("SELECT title FROM memory_items WHERE id=?", (target_id,)).fetchone(); title = str(current["title"]) if current else title
            elif entity == "project":
                target_type, target_view = "project", "projects"
                current = db.execute("SELECT title FROM documents WHERE id=? AND type='project'", (target_id,)).fetchone(); title = str(current["title"]) if current else title
            changes = _changes(payload)
            # Keep the project filter grounded in the recorded change when an
            # object has since moved or is no longer available.
            for state in (payload.get("new"), payload.get("old"), payload):
                if not isinstance(state, dict):
                    continue
                if not project_id and state.get("project_id"):
                    project_id = state["project_id"]
                if not subproject_id and state.get("subproject_id"):
                    subproject_id = state["subproject_id"]
            for change in changes:
                if change["field"] == "Проект":
                    change["old"] = project_names.get(change["old"], "Без проекта" if change["old"] == "—" else "Недоступен")
                    change["new"] = project_names.get(change["new"], "Без проекта" if change["new"] == "—" else "Недоступен")
            event_action = "create" if str(row["action"]) == "create" else "update"
            if target_type == "task" and changes:
                status = next((change["new"] for change in changes if change["field"] == "Статус"), None)
                event_action = "completed" if status == "Выполнена" else "cancelled" if status == "Отменена" else "update"
            if item_type != "all" and target_type != item_type: continue
            if action != "all" and event_action != action: continue
            # A selected top-level project and a selected subproject are both
            # valid scopes.  Use the scope recorded on the object or event;
            # do not manufacture a relationship for legacy records.
            scope_ids = {str(value) for value in (project_id, subproject_id) if value}
            if project != "all" and project not in scope_ids and not (target_type == "project" and target_id == project):
                continue
            labels = {"create": "Создано", "update": "Изменено", "completed": "Задача выполнена", "cancelled": "Задача отменена"}
            display_scope = subproject_id or project_id
            items.append({"id": str(row["id"]), "object_type": target_type, "title": title, "date": str(row["created_at"]), "action": event_action, "label": labels[event_action], "changes": changes, "available": current is not None, "target_id": target_id, "target_view": target_view, "project_id": str(display_scope) if display_scope else None, "project_name": project_names.get(str(display_scope)) if display_scope else None, "author": str(row["author"] or "—")})
    page = items[offset:offset + limit + 1]
    return {"items": page[:limit], "has_more": len(page) > limit, "next_offset": offset + limit}

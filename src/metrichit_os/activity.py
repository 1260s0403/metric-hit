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
    names = {"title": "Название", "description": "Описание", "content": "Описание", "priority": "Приоритет", "due_date": "Срок", "status": "Статус"}
    result = []
    for key in names:
        before, after = old.get(key), new.get(key)
        if before != after and (key in old or key in new): result.append({"field": names[key], "old": _human_field(key, before), "new": _human_field(key, after)})
    return result


def list_activity(database_path: Path, *, period: str = "all", item_type: str = "all", action: str = "all", offset: int = 0, limit: int = 50) -> dict[str, object]:
    if period not in {"today", "7", "30", "all"} or item_type not in {"all", "task", "artem", "idea", "memory"} or action not in {"all", "create", "update", "completed", "cancelled"} or offset < 0 or not 1 <= limit <= 50:
        raise ValueError("invalid activity filter")
    cutoff = None
    if period != "all": cutoff = (datetime.now(timezone.utc) - timedelta(days=0 if period == "today" else int(period))).strftime("%Y-%m-%dT00:00:00.000Z")
    items: list[dict[str, object]] = []
    with read_only_database(database_path) as db:
        rows = db.execute("SELECT id,type,title,data_json,entity_type,entity_id,action,created_at FROM audit_log ORDER BY created_at DESC, id DESC").fetchall()
        for row in rows:
            if cutoff and str(row["created_at"]) < cutoff: continue
            payload = _data(row["data_json"]); entity = str(row["entity_type"]); target_type = "unknown"
            title = str(row["title"]); target_view = None; target_id = str(row["entity_id"]); current = None
            if entity == "task":
                target_type, target_view = "task", "tasks"
                current = db.execute("SELECT title FROM tasks WHERE id=?", (target_id,)).fetchone(); title = str(current["title"]) if current else title
            elif entity in {"knowledge_entry", "document"}:
                kind = _kind(payload.get("new", payload))
                if kind:
                    target_type, target_view = kind, kind
                    current = db.execute("SELECT title FROM documents WHERE id=?", (target_id,)).fetchone(); title = str(current["title"]) if current else title
            elif entity == "memory_item":
                target_type = "memory"
                current = db.execute("SELECT title FROM memory_items WHERE id=?", (target_id,)).fetchone(); title = str(current["title"]) if current else title
            changes = _changes(payload)
            event_action = "create" if str(row["action"]) == "create" else "update"
            if target_type == "task" and changes:
                status = next((change["new"] for change in changes if change["field"] == "Статус"), None)
                event_action = "completed" if status == "Выполнена" else "cancelled" if status == "Отменена" else "update"
            if item_type != "all" and target_type != item_type: continue
            if action != "all" and event_action != action: continue
            labels = {"create": "Создано", "update": "Изменено", "completed": "Задача выполнена", "cancelled": "Задача отменена"}
            items.append({"id": str(row["id"]), "object_type": target_type, "title": title, "date": str(row["created_at"]), "action": event_action, "label": labels[event_action], "changes": changes, "available": current is not None, "target_id": target_id, "target_view": target_view})
    page = items[offset:offset + limit + 1]
    return {"items": page[:limit], "has_more": len(page) > limit, "next_offset": offset + limit}

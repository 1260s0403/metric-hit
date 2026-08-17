from __future__ import annotations

import json
import re
import secrets
import sqlite3
from datetime import date
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import CURRENT_CONTEXT, MEMORY_DATABASE
from .activity import list_activity
from .database import read_only_database
from .global_search import search as global_search
from .knowledge_store import KnowledgeError, KnowledgeStore
from .memory_review import MemoryReviewError, MemoryReviewStore
from .project_store import ProjectStore
from .project_scope import DEFAULT_PROJECT_ID


LOCAL_HOST = "127.0.0.1"
TOKEN_HEADER = "X-Operator-Token"


def _error(message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": "operator_panel_error", "message": message}, status_code=status_code)


def _entries(store: KnowledgeStore, kind: str, query: str) -> list[dict[str, object]]:
    if kind not in {"artem", "idea"}:
        raise KnowledgeError("kind must be artem or idea")
    return store.search(kind=kind, query=query) if query else store.list(kind=kind)


def _summary(items: list[dict[str, object]]) -> dict[str, object]:
    topics: dict[str, int] = {}
    theses: list[str] = []
    seen: set[str] = set()
    for item in items:
        topic = str(item["topic"])
        topics[topic] = topics.get(topic, 0) + 1
        thesis = _short_text(str(item["text"])) or topic
        key = thesis.casefold()
        if key not in seen and len(theses) < 10:
            seen.add(key)
            theses.append(thesis)
    lines = ["# Выжимка", f"Записей: {len(items)}", "", "## Ключевые тезисы"]
    lines.extend(f"- {thesis}" for thesis in theses) or lines.append("- Нет")
    lines.extend(("", "## Основные темы"))
    lines.extend(f"- {topic} — {count}" for topic, count in sorted(topics.items(), key=lambda pair: (-pair[1], pair[0]))) or lines.append("- Нет")
    return {"count": len(items), "markdown": "\n".join(lines), "topics": topics, "theses": theses}


def _short_text(text: str, limit: int = 220) -> str:
    normalized = " ".join(text.split())
    sentence = re.split(r"(?<=[.!?])\s+", normalized, maxsplit=1)[0]
    return sentence if len(sentence) <= limit else sentence[: limit - 1].rstrip() + "…"


def _action_plan(items: list[dict[str, object]], tasks: list[dict[str, object]]) -> dict[str, object]:
    entry_ids = {str(item["id"]) for item in items}
    related = [task for task in tasks if task["knowledge_entry_id"] in entry_ids]
    task_ids = {str(task["knowledge_entry_id"]) for task in related}
    groups = {status: [task for task in related if task["status"] == status] for status in ("open", "completed", "cancelled")}
    without_task = [item for item in items if item["id"] not in task_ids]
    labels = {"open": "Открытые связанные задачи", "completed": "Выполненные связанные задачи", "cancelled": "Отменённые связанные задачи"}
    lines = ["# План действий", "", "## Сделать сейчас"]
    if groups["open"]:
        for number, task in enumerate(groups["open"], 1):
            lines.extend((f"{number}. {task['title']}", f"   {_short_text(str(task['description']))}"))
    else:
        lines.append("- Нет открытых задач")
    lines.extend(("", "## Уже в работе"))
    if groups["open"]:
        lines.extend(f"- {task['title']} — {_short_text(str(task['description']))}" for task in groups["open"])
    else:
        lines.append("- Нет")
    lines.extend(("", "## Можно превратить в задачи"))
    if without_task:
        lines.extend(f"- {item['topic']} — {_short_text(str(item['text']))}" for item in without_task)
    else:
        lines.append("- Нет")
    lines.extend(("", "## Завершено", f"- {len(groups['completed'])} задач", "", "## Отменено", f"- {len(groups['cancelled'])} задач"))
    return {**groups, "markdown": "\n".join(lines), "without_task": without_task}


def _memory_items(database_path: Path, query: str) -> list[dict[str, object]]:
    pattern = f"%{query.strip()}%"
    with read_only_database(database_path) as database:
        rows = database.execute(
            """
            SELECT id, semantic_key, title, content, updated_at, version FROM memory_items
            WHERE status='active' AND (?='' OR semantic_key LIKE ? OR title LIKE ? OR content LIKE ?)
            ORDER BY updated_at DESC, semantic_key ASC
            """,
            (query.strip(), pattern, pattern, pattern),
        ).fetchall()
    return [dict(row) for row in rows]


def _decisions(database_path: Path, query: str) -> list[dict[str, object]]:
    pattern = f"%{query.strip()}%"
    with read_only_database(database_path) as database:
        rows = database.execute(
            """
            SELECT id, title, content, updated_at, version FROM decisions
            WHERE status='active' AND (?='' OR title LIKE ? OR content LIKE ?)
            ORDER BY updated_at DESC, title ASC
            """,
            (query.strip(), pattern, pattern),
        ).fetchall()
    return [dict(row) for row in rows]


def _memory_documents(database_path: Path, query: str) -> list[dict[str, object]]:
    pattern = f"%{query.strip()}%"
    with read_only_database(database_path) as database:
        rows = database.execute(
            """
            SELECT id, title, content, updated_at, version FROM documents
            WHERE type!='knowledge_entry' AND status='active'
              AND (?='' OR title LIKE ? OR content LIKE ?)
            ORDER BY updated_at DESC, id ASC
            """,
            (query.strip(), pattern, pattern),
        ).fetchall()
    return [dict(row) for row in rows]


def _current_context(context_path: Path = CURRENT_CONTEXT) -> dict[str, object]:
    path = context_path if context_path.is_file() else CURRENT_CONTEXT
    content = path.read_text(encoding="utf-8")
    return {"content": content}


def _dashboard(store: KnowledgeStore, database_path: Path) -> dict[str, object]:
    """Build independent, read-only dashboard blocks without exposing raw tables."""
    result: dict[str, object] = {}
    try:
        open_tasks = store.list_tasks(status="open", sort="recommended")
        with read_only_database(database_path) as connection:
            project_names = {str(row["id"]): str(row["title"]) for row in connection.execute("SELECT id,title FROM documents WHERE type='project'")}
        for task in open_tasks:
            project_id = task.get("project_id")
            task["project_name"] = project_names.get(str(project_id)) if project_id else None
        today = date.today().isoformat()
        important = open_tasks[:5]
        result["tasks"] = {
            "open": len(open_tasks),
            "overdue": sum(1 for task in open_tasks if task["due_date"] and task["due_date"] < today),
            "today": sum(1 for task in open_tasks if task["due_date"] == today),
            "high": sum(1 for task in open_tasks if task["priority"] == "high"),
            "items": important,
            "overdue_items": [task for task in important if task["due_date"] and task["due_date"] < today],
            "today_items": [task for task in important if task["due_date"] == today],
            "high_items": [
                task for task in important
                if task["priority"] == "high" and (not task["due_date"] or task["due_date"] > today)
            ],
        }
    except (KnowledgeError, sqlite3.Error, ValueError):
        result["tasks"] = {"error": "Задачи временно недоступны."}
    for kind in ("artem", "idea"):
        try:
            result[kind] = {"items": store.list(kind=kind, limit=3)}
        except (KnowledgeError, sqlite3.Error):
            result[kind] = {"error": "Записи временно недоступны."}

    def count(sql: str) -> int | None:
        try:
            with read_only_database(database_path) as connection:
                return int(connection.execute(sql).fetchone()[0])
        except sqlite3.Error:
            return None

    memory = {
        "approved": count("SELECT count(*) FROM memory_items WHERE status='active'"),
        "pending": count("SELECT count(*) FROM memory_candidates WHERE status='pending'"),
        "conflicts": count("SELECT count(*) FROM memory_conflicts WHERE status='open'"),
        "sources": count("SELECT count(*) FROM sources"),
    }
    result["memory"] = memory if all(value is not None for value in memory.values()) else {
        "approved": "недоступно", "pending": "недоступно", "conflicts": "недоступно", "sources": "недоступно",
    }
    return result



from .operator_panel_ui import OPERATOR_PANEL_ASSETS, _page

def create_operator_app(database_path: Path) -> FastAPI:
    store = KnowledgeStore(database_path)
    projects = ProjectStore(database_path)
    context_path = CURRENT_CONTEXT if database_path.resolve() == MEMORY_DATABASE.resolve() else database_path.with_name("current-context.md")
    memory_review = MemoryReviewStore(database_path, context_path)
    token = secrets.token_urlsafe(32)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/assets", StaticFiles(directory=OPERATOR_PANEL_ASSETS), name="operator-panel-assets")

    @app.get("/favicon.ico", status_code=204)
    def favicon() -> None:
        return None

    @app.get("/", response_class=HTMLResponse)
    def page(request: Request, view: str = "overview", focus_task: str | None = None) -> str:
        focused = focus_task if focus_task and any(task["id"] == focus_task for task in store.list_tasks()) else None
        return _page(token, focused, view)

    @app.get("/api/entries")
    def entries(kind: str, query: str = "") -> JSONResponse:
        try:
            tasks = {task["knowledge_entry_id"]: task for task in store.list_tasks()}
            items = _entries(store, kind, query)
            return JSONResponse([{**item, "task": tasks.get(item["id"])} for item in items])
        except KnowledgeError as error:
            return _error(str(error), 400)

    @app.get("/api/dashboard")
    def dashboard() -> JSONResponse:
        return JSONResponse(_dashboard(store, database_path))

    @app.get("/api/projects")
    def project_list() -> JSONResponse:
        return JSONResponse(projects.list())

    @app.get("/api/projects/{project_id}")
    def project_detail(project_id: str) -> JSONResponse:
        try:
            return JSONResponse(projects.detail(project_id))
        except KnowledgeError as error:
            return _error(str(error), 404)

    @app.post("/api/projects")
    async def project_create(request: Request) -> JSONResponse:
        if request.headers.get(TOKEN_HEADER) != token: return _error("missing or invalid startup token", 403)
        try:
            payload = await request.json(); item, created = projects.create(name=_text(payload, "name"), description=_optional_text(payload, "description") or "", parent_project_id=_optional_text(payload, "parent_project_id")); item["created"] = created
            return JSONResponse(item)
        except (KnowledgeError, ValueError, TypeError, json.JSONDecodeError) as error: return _error(str(error), 400)

    @app.post("/api/projects/{project_id}/edit")
    async def project_edit(project_id: str, request: Request) -> JSONResponse:
        if request.headers.get(TOKEN_HEADER) != token: return _error("missing or invalid startup token", 403)
        try:
            payload = await request.json(); return JSONResponse(projects.edit(project_id=project_id, name=_text(payload, "name"), description=_optional_text(payload, "description") or ""))
        except (KnowledgeError, ValueError, TypeError, json.JSONDecodeError) as error: return _error(str(error), 400)

    @app.post("/api/projects/{project_id}/archive")
    async def project_archive(project_id: str, request: Request) -> JSONResponse:
        if request.headers.get(TOKEN_HEADER) != token: return _error("missing or invalid startup token", 403)
        try: return JSONResponse(projects.archive(project_id))
        except KnowledgeError as error: return _error(str(error), 400)

    @app.post("/api/projects/assign")
    async def project_assign(request: Request) -> JSONResponse:
        if request.headers.get(TOKEN_HEADER) != token: return _error("missing or invalid startup token", 403)
        try:
            payload = await request.json(); projects.assign(object_id=_text(payload, "object_id"), project_id=_optional_text(payload, "project_id"), subproject_id=_optional_text(payload, "subproject_id")); return JSONResponse({"ok": True})
        except (KnowledgeError, ValueError, TypeError, json.JSONDecodeError) as error: return _error(str(error), 400)

    @app.get("/api/search")
    def search(query: str = "", item_type: str = "all", status: str = "all") -> JSONResponse:
        try:
            return JSONResponse({"query": query, "results": global_search(database_path, query=query, item_type=item_type, status=status)})
        except ValueError as error:
            return _error(str(error), 400)

    @app.get("/api/activity")
    def activity(period: str = "all", item_type: str = "all", action: str = "all", offset: int = 0) -> JSONResponse:
        try:
            return JSONResponse(list_activity(database_path, period=period, item_type=item_type, action=action, offset=offset))
        except ValueError as error:
            return _error(str(error), 400)

    @app.get("/api/summary")
    def summary(kind: str, query: str = "") -> JSONResponse:
        try:
            return JSONResponse(_summary(_entries(store, kind, query)))
        except KnowledgeError as error:
            return _error(str(error), 400)

    @app.get("/api/action-plan")
    def action_plan(kind: str, query: str = "") -> JSONResponse:
        try:
            return JSONResponse(_action_plan(_entries(store, kind, query), store.list_tasks()))
        except KnowledgeError as error:
            return _error(str(error), 400)

    @app.get("/api/memory/context")
    def memory_context() -> JSONResponse:
        return JSONResponse(_current_context(context_path))

    @app.get("/api/memory/candidates")
    def memory_candidates(query: str = "") -> JSONResponse:
        return JSONResponse(memory_review.candidates(query))

    @app.get("/api/memory/candidates/{candidate_id}")
    def memory_candidate(candidate_id: str) -> JSONResponse:
        try:
            return JSONResponse(memory_review.candidate(candidate_id))
        except MemoryReviewError as error:
            return _error(str(error), 404)

    @app.get("/api/memory/conflicts")
    def memory_conflicts() -> JSONResponse:
        return JSONResponse(memory_review.conflicts())

    @app.post("/api/memory/candidates/{candidate_id}/approve")
    async def memory_candidate_approve(candidate_id: str, request: Request) -> JSONResponse:
        if request.headers.get(TOKEN_HEADER) != token:
            return _error("missing or invalid startup token", 403)
        try:
            payload = await request.json()
            return JSONResponse(memory_review.approve(candidate_id, payload.get("comment") if isinstance(payload, dict) else None))
        except (MemoryReviewError, sqlite3.Error, OSError, json.JSONDecodeError) as error:
            return _error(str(error), 400)

    @app.post("/api/memory/candidates/{candidate_id}/reject")
    async def memory_candidate_reject(candidate_id: str, request: Request) -> JSONResponse:
        if request.headers.get(TOKEN_HEADER) != token:
            return _error("missing or invalid startup token", 403)
        try:
            payload = await request.json()
            return JSONResponse(memory_review.reject(candidate_id, payload.get("reason") if isinstance(payload, dict) else None))
        except (MemoryReviewError, sqlite3.Error, json.JSONDecodeError) as error:
            return _error(str(error), 400)

    @app.post("/api/memory/conflicts/{conflict_id}/resolve")
    async def memory_conflict_resolve(conflict_id: str, request: Request) -> JSONResponse:
        if request.headers.get(TOKEN_HEADER) != token:
            return _error("missing or invalid startup token", 403)
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                raise MemoryReviewError("request body must be an object")
            return JSONResponse(memory_review.resolve(conflict_id, payload.get("outcome"), payload.get("reason")))
        except (MemoryReviewError, sqlite3.Error, OSError, json.JSONDecodeError) as error:
            return _error(str(error), 400)

    @app.get("/api/memory/facts")
    def memory_facts(query: str = "") -> JSONResponse:
        return JSONResponse(_memory_items(database_path, query))

    @app.get("/api/memory/decisions")
    def memory_decisions(query: str = "") -> JSONResponse:
        return JSONResponse(_decisions(database_path, query))

    @app.get("/api/memory/documents")
    def memory_documents(query: str = "") -> JSONResponse:
        return JSONResponse(_memory_documents(database_path, query))

    @app.post("/api/entries")
    async def add_entry(request: Request) -> JSONResponse:
        if request.headers.get(TOKEN_HEADER) != token:
            return _error("missing or invalid startup token", 403)
        try:
            payload = await request.json()
            project_id = _optional_text(payload, "project_id") or DEFAULT_PROJECT_ID
            subproject_id = _optional_text(payload, "subproject_id")
            projects.validate_assignment(project_id, subproject_id, required=True)
            item = store.add(
                kind=_text(payload, "kind"), topic=_text(payload, "topic"), text=_text(payload, "text"),
                tags=_optional_text(payload, "tags"),
                project_id=project_id, subproject_id=subproject_id,
            )
            return JSONResponse(item, status_code=201)
        except (KnowledgeError, ValueError, TypeError, json.JSONDecodeError) as error:
            return _error(str(error), 400)

    @app.post("/api/tasks")
    async def add_task(request: Request) -> JSONResponse:
        if request.headers.get(TOKEN_HEADER) != token:
            return _error("missing or invalid startup token", 403)
        try:
            payload = await request.json()
            project_id = _optional_text(payload, "project_id") or DEFAULT_PROJECT_ID
            subproject_id = _optional_text(payload, "subproject_id")
            projects.validate_assignment(project_id, subproject_id, required=True)
            entry_id = _optional_text(payload, "id")
            if entry_id:
                item, created = store.to_task_with_created(
                    entry_id=entry_id, title=_optional_text(payload, "title"),
                    description=_optional_text(payload, "description"),
                    priority=_optional_text(payload, "priority") or "normal",
                    due_date=_optional_text(payload, "due_date"),
                    project_id=project_id, subproject_id=subproject_id,
                )
                item["created"] = created
            else:
                item = store.create_task(
                    title=_text(payload, "title"), description=_text(payload, "description"),
                    priority=_optional_text(payload, "priority") or "normal", due_date=_optional_text(payload, "due_date"),
                    project_id=project_id, subproject_id=subproject_id,
                )
                item["created"] = True
            return JSONResponse(item)
        except (KnowledgeError, ValueError, TypeError, json.JSONDecodeError) as error:
            return _error(str(error), 400)

    @app.get("/api/tasks")
    def tasks(query: str = "", status: str = "all", priority: str = "all", due: str = "all", sort: str = "recommended", project: str = "all") -> JSONResponse:
        try:
            return JSONResponse(store.list_tasks(query=query, status=status, priority=priority, due=due, sort=sort, project=project))
        except KnowledgeError as error:
            return _error(str(error), 400)

    @app.get("/api/tasks/today")
    def today_tasks() -> JSONResponse:
        return JSONResponse(store.today_tasks())

    @app.post("/api/tasks/{task_id}/edit")
    async def edit_task(task_id: str, request: Request) -> JSONResponse:
        if request.headers.get(TOKEN_HEADER) != token:
            return _error("missing or invalid startup token", 403)
        try:
            payload = await request.json()
            project_id = _optional_text(payload, "project_id")
            subproject_id = _optional_text(payload, "subproject_id")
            projects.validate_assignment(project_id, subproject_id, required=True)
            item = store.edit_task(
                task_id=task_id, title=_text(payload, "title"), description=_text(payload, "description"),
                priority=_text(payload, "priority"), due_date=_optional_text(payload, "due_date"),
            )
            projects.assign(object_id=task_id, project_id=project_id, subproject_id=subproject_id)
            return JSONResponse(item)
        except (KnowledgeError, ValueError, TypeError, json.JSONDecodeError) as error:
            return _error(str(error), 400)

    @app.post("/api/tasks/{task_id}/status")
    async def change_task_status(task_id: str, request: Request) -> JSONResponse:
        if request.headers.get(TOKEN_HEADER) != token:
            return _error("missing or invalid startup token", 403)
        try:
            payload = await request.json()
            return JSONResponse(store.set_task_status(task_id=task_id, status=_text(payload, "status")))
        except (KnowledgeError, ValueError, TypeError, json.JSONDecodeError) as error:
            return _error(str(error), 400)

    return app


def _text(payload: object, key: str) -> str:
    if not isinstance(payload, dict) or not isinstance(payload.get(key), str):
        raise KnowledgeError(f"{key} must be a string")
    return payload[key]


def _optional_text(payload: object, key: str) -> str | None:
    if not isinstance(payload, dict) or payload.get(key) is None:
        return None
    if not isinstance(payload[key], str):
        raise KnowledgeError(f"{key} must be a string")
    return payload[key]


def run_operator_panel(database_path: Path, *, port: int, host: str = LOCAL_HOST) -> None:
    if host != LOCAL_HOST:
        raise ValueError("operator panel may only listen on 127.0.0.1")
    if not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    uvicorn.run(create_operator_app(database_path), host=host, port=port)

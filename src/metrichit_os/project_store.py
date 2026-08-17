from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .database import read_only_database
from .knowledge_store import KnowledgeError


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _meta(value: object) -> dict[str, object]:
    try: parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError): return {}
    return parsed if isinstance(parsed, dict) else {}


def _name(value: str) -> str:
    return " ".join(value.casefold().replace("ё", "е").split())


TOP_LEVEL_SCOPE_TYPES = {"control_plane", "managed_project"}


class ProjectStore:
    def __init__(self, path: Path): self.path = path.resolve()

    def _project(self, row: sqlite3.Row | dict[str, object]) -> dict[str, object]:
        metadata = _meta(row["data_json"])
        return {"id": row["id"], "name": row["title"], "description": row["content"], "status": row["status"], "scope_type": metadata.get("scope_type", "managed_project"), "parent_project_id": metadata.get("parent_project_id"), "default_for_new": bool(metadata.get("default_for_new")), "created_at": row["created_at"], "updated_at": row["updated_at"]}

    def validate_assignment(self, project_id: str | None, subproject_id: str | None = None, *, required: bool = False) -> tuple[str | None, str | None]:
        if not project_id:
            if required: raise KnowledgeError("project scope is required")
            if subproject_id: raise KnowledgeError("subproject requires a project")
            return None, None
        with read_only_database(self.path) as db:
            row = db.execute("SELECT status,data_json FROM documents WHERE id=? AND type='project'", (project_id,)).fetchone()
            if not row or row["status"] != "active" or _meta(row["data_json"]).get("scope_type") not in TOP_LEVEL_SCOPE_TYPES:
                raise KnowledgeError("project must be an active top-level project")
            if subproject_id:
                child = db.execute("SELECT status,data_json FROM documents WHERE id=? AND type='project'", (subproject_id,)).fetchone()
                child_meta = _meta(child["data_json"]) if child else {}
                if not child or child["status"] != "active" or child_meta.get("scope_type") != "subproject" or child_meta.get("parent_project_id") != project_id:
                    raise KnowledgeError("subproject must belong to the selected project")
        return project_id, subproject_id

    def list(self) -> list[dict[str, object]]:
        with read_only_database(self.path) as db:
            rows = db.execute("SELECT id,title,content,data_json,status,created_at,updated_at FROM documents WHERE type='project' ORDER BY status,title COLLATE NOCASE,id").fetchall()
            projects = [self._project(row) for row in rows]
            objects = db.execute("SELECT data_json,status,type FROM tasks UNION ALL SELECT data_json,status,type FROM documents WHERE type='knowledge_entry'").fetchall()
        role_order = {"control_plane": 0, "managed_project": 1, "subproject": 2}
        projects.sort(key=lambda item: (
            item["status"] != "active",
            role_order.get(str(item["scope_type"]), 3),
            _name(str(item["name"])),
            str(item["id"]),
        ))
        for project in projects:
            project.update(open_tasks=0, artem=0, ideas=0)
        by_id = {str(item["id"]): item for item in projects}
        unassigned = {"open_tasks": 0, "artem": 0, "ideas": 0}
        for row in objects:
            metadata = _meta(row["data_json"]); project = by_id.get(str(metadata.get("project_id")))
            targets = [project] if project else [unassigned]
            child = by_id.get(str(metadata.get("subproject_id")))
            if child and child.get("parent_project_id") == metadata.get("project_id"): targets.append(child)
            for target in targets:
                if row["type"] in {"knowledge_task", "standalone_task"}:
                    if row["status"] in {"pending", "in_progress"}: target["open_tasks"] += 1
                elif metadata.get("kind") == "artem_recommendation": target["artem"] += 1
                elif metadata.get("kind") == "owner_idea": target["ideas"] += 1
        return [{"id": "unassigned", "name": "Без проекта", "description": "Несвязанные записи", "status": "virtual", **unassigned}, *projects]

    def detail(self, project_id: str) -> dict[str, object]:
        project = next((item for item in self.list() if item["id"] == project_id), None)
        if not project or project_id == "unassigned":
            raise KnowledgeError("project was not found")
        groups: dict[str, list[dict[str, object]]] = {"tasks": [], "artem": [], "ideas": []}
        with read_only_database(self.path) as db:
            rows = db.execute("SELECT id,type,title,content,data_json,status FROM documents WHERE type='knowledge_entry' UNION ALL SELECT id,type,title,content,data_json,status FROM tasks WHERE type IN ('knowledge_task','standalone_task')").fetchall()
        for row in rows:
            metadata = _meta(row["data_json"])
            scope_key = "subproject_id" if project.get("scope_type") == "subproject" else "project_id"
            if metadata.get(scope_key) != project_id:
                continue
            item = {"id": str(row["id"]), "title": str(row["title"] or ""), "content": str(row["content"] or ""), "status": str(row["status"])}
            if row["type"] in {"knowledge_task", "standalone_task"} and row["status"] in {"pending", "in_progress"}:
                groups["tasks"].append(item)
            elif metadata.get("kind") == "artem_recommendation": groups["artem"].append(item)
            elif metadata.get("kind") == "owner_idea": groups["ideas"].append(item)
        return {"project": project, **groups}

    def create(self, *, name: str, description: str, parent_project_id: str | None = None, author: str = "owner") -> tuple[dict[str, object], bool]:
        if not name.strip(): raise KnowledgeError("project name must not be empty")
        if parent_project_id: self.validate_assignment(parent_project_id, required=True)
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row; db.execute("BEGIN IMMEDIATE")
            for row in db.execute("SELECT id,title,content,data_json,status,created_at,updated_at FROM documents WHERE type='project' AND status='active'"):
                if _name(str(row["title"])) == _name(name): return self._project(row), False
            now, project_id = _utc(), str(uuid4()); metadata_dict = {"kind":"project", "scope_type":"subproject" if parent_project_id else "managed_project"}
            if parent_project_id: metadata_dict["parent_project_id"] = parent_project_id
            metadata = json.dumps(metadata_dict, ensure_ascii=False, sort_keys=True)
            db.execute("INSERT INTO documents (id,type,title,content,data_json,status,author,created_at,updated_at,access_level,version) VALUES (?, 'project', ?, ?, ?, 'active', ?, ?, ?, 'internal', 1)", (project_id,name.strip(),description,metadata,author,now,now))
            self._audit(db, project_id, "project", author, now, "Project created", {"new":{"name":name.strip(),"description":description,"status":"active"}}, "create")
            return {"id":project_id,"name":name.strip(),"description":description,"status":"active","scope_type":metadata_dict["scope_type"],"parent_project_id":parent_project_id,"default_for_new":False,"created_at":now,"updated_at":now}, True

    def edit(self, *, project_id: str, name: str, description: str) -> dict[str, object]:
        if not name.strip(): raise KnowledgeError("project name must not be empty")
        with sqlite3.connect(self.path) as db:
            db.row_factory=sqlite3.Row; db.execute("BEGIN IMMEDIATE"); row=db.execute("SELECT * FROM documents WHERE id=? AND type='project'",(project_id,)).fetchone()
            if not row: raise KnowledgeError("project was not found")
            for other in db.execute("SELECT id,title FROM documents WHERE type='project' AND status='active' AND id<>?",(project_id,)):
                if _name(str(other["title"]))==_name(name): raise KnowledgeError("active project name already exists")
            if row["title"]==name.strip() and row["content"]==description: return self._project(row)
            now=_utc(); db.execute("UPDATE documents SET title=?,content=?,updated_at=?,version=version+1 WHERE id=?",(name.strip(),description,now,project_id)); self._audit(db,project_id,"project",row["author"],now,"Project edited",{"old":{"name":row["title"],"description":row["content"]},"new":{"name":name.strip(),"description":description}},"update")
            value=dict(row); value.update(title=name.strip(),content=description,updated_at=now); return self._project(value)

    def archive(self, project_id: str) -> dict[str, object]:
        with sqlite3.connect(self.path) as db:
            db.row_factory=sqlite3.Row; db.execute("BEGIN IMMEDIATE"); row=db.execute("SELECT * FROM documents WHERE id=? AND type='project'",(project_id,)).fetchone()
            if not row: raise KnowledgeError("project was not found")
            if row["status"]=="archived": return self._project(row)
            now=_utc(); db.execute("UPDATE documents SET status='archived',updated_at=?,version=version+1 WHERE id=?",(now,project_id)); self._audit(db,project_id,"project",row["author"],now,"Project archived",{"old":{"status":"active"},"new":{"status":"archived"}},"update"); value=dict(row);value.update(status="archived",updated_at=now);return self._project(value)

    def assign(self, *, object_id: str, project_id: str | None, subproject_id: str | None = None) -> None:
        self.validate_assignment(project_id, subproject_id, required=bool(project_id or subproject_id))
        with sqlite3.connect(self.path) as db:
            db.row_factory=sqlite3.Row; db.execute("BEGIN IMMEDIATE"); row=db.execute("SELECT id,type,data_json,author FROM tasks WHERE id=? AND type IN ('knowledge_task','standalone_task') UNION ALL SELECT id,type,data_json,author FROM documents WHERE id=? AND type='knowledge_entry'",(object_id,object_id)).fetchone()
            if not row: raise KnowledgeError("object was not found")
            try:
                metadata = json.loads(str(row["data_json"]))
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                raise KnowledgeError("object metadata cannot be changed safely") from error
            if not isinstance(metadata, dict):
                raise KnowledgeError("object metadata cannot be changed safely")
            old_project, old_subproject = metadata.get("project_id"), metadata.get("subproject_id")
            if old_project and not project_id: raise KnowledgeError("scoped object cannot be returned to legacy unassigned state")
            if (old_project, old_subproject)==(project_id, subproject_id):return
            if project_id: metadata["project_id"]=project_id
            else: metadata.pop("project_id",None)
            if subproject_id: metadata["subproject_id"]=subproject_id
            else: metadata.pop("subproject_id",None)
            now=_utc(); table="tasks" if row["type"] in {"knowledge_task","standalone_task"} else "documents"; entity="task" if table=="tasks" else "knowledge_entry"; kind=metadata.get("kind") or metadata.get("knowledge_kind"); db.execute(f"UPDATE {table} SET data_json=?,updated_at=?,version=version+1 WHERE id=?",(json.dumps(metadata,ensure_ascii=False,sort_keys=True),now,object_id)); self._audit(db,object_id,entity,row["author"],now,"Project assignment changed",{"old":{"project_id":old_project,"subproject_id":old_subproject},"new":{"project_id":project_id,"subproject_id":subproject_id,"kind":kind}},"update")

    @staticmethod
    def _audit(db: sqlite3.Connection, entity_id: str, entity_type: str, author: str, now: str, title: str, data: dict[str, object], action: str) -> None:
        db.execute("INSERT INTO audit_log (id,type,title,data_json,author,created_at,updated_at,access_level,version,entity_type,entity_id,action) VALUES (?, 'project_change', ?, ?, ?, ?, ?, 'restricted', 1, ?, ?, ?)",(str(uuid4()),title,json.dumps(data,ensure_ascii=False,sort_keys=True),author,now,now,entity_type,entity_id,action))

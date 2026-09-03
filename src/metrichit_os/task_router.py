from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from .knowledge_store import KnowledgeError
from .project_store import ProjectStore


def _normal(value: str) -> str:
    return " ".join(value.casefold().replace("ё", "е").split())


def _slug(value: str) -> str:
    transliteration = str.maketrans({
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    })
    text = unicodedata.normalize("NFKD", value.casefold().translate(transliteration)).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "task"


def parse_short_task_command(text: str) -> tuple[str, str]:
    match = re.search(r"(?:ядро\s+старт\.?\s*)?проект\s*[«\"]?([^»:\"]+)[»\"]?\s*:\s*(.+)$", text.strip(), re.IGNORECASE)
    if not match:
        raise KnowledgeError("use: Ядро старт. Проект «Название»: задача")
    project_name, task = (part.strip() for part in match.groups())
    if not project_name or not task:
        raise KnowledgeError("project name and task must not be empty")
    return project_name, task


def route_project_task(store: ProjectStore, *, project_name: str, task: str, worktree_root: str = "tmp") -> dict[str, object]:
    wanted = _normal(project_name)
    matches = [project for project in store.list() if project["status"] == "active" and _normal(str(project["name"])) == wanted]
    if not matches:
        raise KnowledgeError("active project was not found")
    if len(matches) != 1:
        raise KnowledgeError("project name is ambiguous")
    project = matches[0]
    parent_id = project.get("parent_project_id")
    project_id = str(parent_id or project["id"])
    subproject_id = str(project["id"]) if parent_id else None
    branch = f"codex/{_slug(str(project['name']))}/{_slug(task)[:48]}"
    return {
        "project": {"id": project_id, "name": str(project["name"]), "subproject_id": subproject_id},
        "task": task.strip(),
        "branch": branch,
        "worktree": str(Path(worktree_root) / f"{_slug(str(project['name']))}-{_slug(task)[:48]}"),
        "requires_resource_declaration": True,
        "creates_worktree": False,
        "next_step": "declare exact paths, SQLite and shared resources before claiming a writer lease",
    }


def project_task_scope(store: ProjectStore, *, project_name: str, task: str) -> dict[str, object]:
    """Resolve one registered project task to its stable parallel chat identity."""
    route = route_project_task(store, project_name=project_name, task=task)
    project = route["project"]
    normalized_task = _normal(str(route["task"]))
    return {
        "key": str(uuid5(NAMESPACE_URL, f"metrichit-project-task:{project['id']}:{normalized_task}")),
        "kind": "project_task",
        "label": f"Проект «{project['name']}»: {route['task']}",
        "project_id": project["id"],
        "subproject_id": project["subproject_id"],
        "task_name": route["task"],
        "branch": route["branch"],
    }

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from .config import MEMORY_DATABASE, PROJECT_STORAGE_ROOT
from .database import read_only_database
from .knowledge_store import KnowledgeError, KnowledgeStore
from .memory_review import MemoryReviewError, MemoryReviewStore
from .project_migration import verify_metrichit_runtime_storage
from .project_scope import DEFAULT_PROJECT_ID


@dataclass(frozen=True)
class RuntimeDatabases:
    """Validated central/control-plane and MetricHit runtime databases."""

    central: Path
    metrichit: Path | None = None

    @classmethod
    def resolve(
        cls,
        central_path: Path,
        project_path: Path | None = None,
    ) -> "RuntimeDatabases":
        central = central_path.resolve()
        candidate = project_path
        if candidate is None and central == MEMORY_DATABASE.resolve():
            candidate = PROJECT_STORAGE_ROOT / DEFAULT_PROJECT_ID / "project.sqlite"
        if candidate is None:
            return cls(central=central)
        target = candidate.resolve()
        verify_metrichit_runtime_storage(central, target)
        return cls(central=central, metrichit=target)

    @property
    def read_paths(self) -> tuple[Path, ...]:
        return (self.metrichit, self.central) if self.metrichit is not None else (self.central,)

    def path_for_scope(self, project_id: str | None) -> Path:
        if project_id == DEFAULT_PROJECT_ID:
            if self.metrichit is None:
                return self.central
            return self.metrichit
        return self.central

    def path_for_record(self, table: str, record_id: str) -> Path | None:
        if table not in {"documents", "tasks"}:
            raise ValueError("unsupported routed table")
        for path in self.read_paths:
            with read_only_database(path) as connection:
                row = connection.execute(
                    f'SELECT id FROM "{table}" WHERE id=?', (record_id,)
                ).fetchone()
            if row is not None:
                return path
        return None


class RoutedKnowledgeStore:
    """Route scoped writes and federate reads with project precedence."""

    def __init__(self, databases: RuntimeDatabases):
        self.databases = databases
        self._stores = {path: KnowledgeStore(path) for path in databases.read_paths}

    @staticmethod
    def _dedupe(items: list[dict[str, object]]) -> list[dict[str, object]]:
        seen: set[str] = set()
        result = []
        for item in items:
            identity = str(item["id"])
            if identity not in seen:
                seen.add(identity)
                result.append(item)
        return result

    def _store_for_scope(self, project_id: str | None) -> KnowledgeStore:
        return self._stores[self.databases.path_for_scope(project_id)]

    def _store_for_record(self, table: str, record_id: str) -> KnowledgeStore:
        path = self.databases.path_for_record(table, record_id)
        if path is None:
            label = "knowledge entry" if table == "documents" else "knowledge task"
            raise KnowledgeError(f"{label} was not found")
        return self._stores[path]

    def add(self, **kwargs: Any) -> dict[str, object]:
        return self._store_for_scope(kwargs.get("project_id")).add(**kwargs)

    def list(self, *, kind: str, limit: int = 20) -> list[dict[str, object]]:
        if not 1 <= limit <= 100:
            raise KnowledgeError("limit must be between 1 and 100")
        items = [item for path in self.databases.read_paths for item in self._stores[path].list_all(kind=kind)]
        items = self._dedupe(items)
        items.sort(key=lambda item: (str(item["created_at"]), str(item["id"])), reverse=True)
        return items[:limit]

    def list_all(self, *, kind: str) -> list[dict[str, object]]:
        items = [item for path in self.databases.read_paths for item in self._stores[path].list_all(kind=kind)]
        items = self._dedupe(items)
        items.sort(key=lambda item: (str(item["created_at"]), str(item["id"])), reverse=True)
        return items

    def search(self, *, kind: str, query: str, limit: int = 20) -> list[dict[str, object]]:
        if not query.strip():
            raise KnowledgeError("query must not be empty")
        if not 1 <= limit <= 100:
            raise KnowledgeError("limit must be between 1 and 100")
        items = [
            item
            for path in self.databases.read_paths
            for item in self._stores[path].search(kind=kind, query=query, limit=100)
        ]
        items = self._dedupe(items)
        items.sort(key=lambda item: (str(item["created_at"]), str(item["id"])), reverse=True)
        return items[:limit]

    def _task_store_for_entry(self, entry_id: str, project_id: str | None) -> KnowledgeStore:
        path = self.databases.path_for_record("documents", entry_id)
        if path is None:
            raise KnowledgeError("knowledge entry was not found")
        if path != self.databases.path_for_scope(project_id):
            raise KnowledgeError("cross-storage task conversion requires a separate migration")
        return self._stores[path]

    def to_task(self, **kwargs: Any) -> dict[str, object]:
        return self._task_store_for_entry(kwargs["entry_id"], kwargs.get("project_id")).to_task(**kwargs)

    def to_task_with_created(self, **kwargs: Any) -> tuple[dict[str, object], bool]:
        return self._task_store_for_entry(
            kwargs["entry_id"], kwargs.get("project_id")
        ).to_task_with_created(**kwargs)

    def create_task(self, **kwargs: Any) -> dict[str, object]:
        return self._store_for_scope(kwargs.get("project_id")).create_task(**kwargs)

    @staticmethod
    def _sort_tasks(items: list[dict[str, object]], sort: str) -> None:
        current = date.today()
        rank = {"high": 0, "normal": 1, "low": 2}

        def recommended(item: dict[str, object]) -> tuple[object, ...]:
            value = item["due_date"]
            if item["status"] != "open":
                return (7, "", "")
            if value:
                due_date = date.fromisoformat(str(value))
                return (0 if due_date < current else 1 if due_date == current else 2, value, "")
            return (3 + rank[str(item["priority"])], "", "")

        if sort == "recommended":
            items.sort(key=recommended)
        elif sort == "due":
            items.sort(key=lambda item: (item["due_date"] is None, item["due_date"] or "9999-12-31"))
        elif sort == "priority":
            items.sort(key=lambda item: rank[str(item["priority"])])
        elif sort == "newest":
            items.sort(key=lambda item: str(item["created_at"]), reverse=True)
        elif sort == "oldest":
            items.sort(key=lambda item: str(item["created_at"]))

    def list_tasks(self, **kwargs: Any) -> list[dict[str, object]]:
        sort = str(kwargs.get("sort", "recommended"))
        items = [
            item
            for path in self.databases.read_paths
            for item in self._stores[path].list_tasks(**{**kwargs, "sort": "newest"})
        ]
        items = self._dedupe(items)
        self._sort_tasks(items, sort)
        return items

    def today_tasks(self) -> list[dict[str, object]]:
        current = date.today()
        tasks = self.list_tasks(status="open")
        urgent = [item for item in tasks if item["due_date"] and date.fromisoformat(str(item["due_date"])) <= current]
        high = [item for item in tasks if item["due_date"] is None and item["priority"] == "high"][:5]
        return urgent + high

    def edit_task(self, **kwargs: Any) -> dict[str, object]:
        return self._store_for_record("tasks", kwargs["task_id"]).edit_task(**kwargs)

    def task_for_entry(self, entry_id: str) -> dict[str, object] | None:
        return next((task for task in self.list_tasks() if task["knowledge_entry_id"] == entry_id), None)

    def set_task_status(self, **kwargs: Any) -> dict[str, object]:
        return self._store_for_record("tasks", kwargs["task_id"]).set_task_status(**kwargs)


class RoutedMemoryReviewStore:
    def __init__(self, databases: RuntimeDatabases, central_context_path: Path):
        self.databases = databases
        self._stores = {
            path: MemoryReviewStore(
                path,
                central_context_path if path == databases.central else None,
            )
            for path in databases.read_paths
        }

    def _store_with_row(self, table: str, row_id: str) -> MemoryReviewStore:
        for path in self.databases.read_paths:
            with read_only_database(path) as connection:
                row = connection.execute(f'SELECT id FROM "{table}" WHERE id=?', (row_id,)).fetchone()
            if row is not None:
                return self._stores[path]
        label = "memory conflict" if table == "memory_conflicts" else "memory candidate"
        raise MemoryReviewError(f"{label} not found")

    def _project_ids(self, table: str) -> set[str]:
        if self.databases.metrichit is None:
            return set()
        with read_only_database(self.databases.metrichit) as connection:
            return {str(row["id"]) for row in connection.execute(f'SELECT id FROM "{table}"')}

    @staticmethod
    def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        result = []
        for item in items:
            identity = str(item["id"])
            if identity not in seen:
                seen.add(identity)
                result.append(item)
        return result

    def candidates(self, query: str = "") -> list[dict[str, Any]]:
        project_ids = self._project_ids("memory_candidates")
        items = [
            item
            for path in self.databases.read_paths
            for item in self._stores[path].candidates(query)
            if path != self.databases.central or str(item["id"]) not in project_ids
        ]
        return self._dedupe(items)

    def candidate(self, candidate_id: str) -> dict[str, Any]:
        return self._store_with_row("memory_candidates", candidate_id).candidate(candidate_id)

    def conflicts(self) -> list[dict[str, Any]]:
        project_ids = self._project_ids("memory_conflicts")
        items = [
            item
            for path in self.databases.read_paths
            for item in self._stores[path].conflicts()
            if path != self.databases.central or str(item["id"]) not in project_ids
        ]
        return self._dedupe(items)

    def approve(self, candidate_id: str, comment: object = None) -> dict[str, Any]:
        return self._store_with_row("memory_candidates", candidate_id).approve(candidate_id, comment)

    def reject(self, candidate_id: str, reason: object) -> dict[str, Any]:
        return self._store_with_row("memory_candidates", candidate_id).reject(candidate_id, reason)

    def resolve(self, conflict_id: str, outcome: object, reason: object) -> dict[str, Any]:
        return self._store_with_row("memory_conflicts", conflict_id).resolve(conflict_id, outcome, reason)

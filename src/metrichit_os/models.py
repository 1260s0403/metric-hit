from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    backend: Literal["python-fastapi"] = "python-fastapi"
    read_only: Literal[True] = True


class ContextResponse(BaseModel):
    exists: bool
    sha256: str | None
    content: str | None


class DatabaseStatus(BaseModel):
    integrity: Literal["ok"]
    migration_count: int
    tables: list[str]


class MemorySummaryResponse(DatabaseStatus):
    candidate_statuses: dict[str, int]
    open_conflicts: int
    open_tasks: int
    source_count: int


class EntityStatus(BaseModel):
    count: int
    statuses: dict[str, int]


class EditorialStatusResponse(DatabaseStatus):
    entities: dict[str, EntityStatus]

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from metrichit_os.knowledge_store import KnowledgeError, KnowledgeStore
from metrichit_os.project_store import ProjectStore


def db(tmp_path: Path) -> Path:
    path = tmp_path / "projects.sqlite"; subprocess.run(["node", "scripts/init-memory.mjs", str(path)], check=True, capture_output=True); return path


def test_project_lifecycle_assignment_and_counts(tmp_path: Path) -> None:
    path=db(tmp_path); projects=ProjectStore(path); knowledge=KnowledgeStore(path)
    first, created=projects.create(name="Ёлка",description="one"); assert created and first["scope_type"] == "managed_project"
    same, created=projects.create(name=" елка ",description="two"); assert not created and same["id"]==first["id"]
    task=knowledge.create_task(title="Task",description="x"); entry=knowledge.add(kind="idea",topic="Idea",text="x")
    projects.assign(object_id=str(task["id"]),project_id=str(first["id"])); projects.assign(object_id=str(entry["id"]),project_id=str(first["id"]))
    listed=next(item for item in projects.list() if item["id"]==first["id"]); assert listed["open_tasks"]==1 and listed["ideas"]==1
    projects.archive(str(first["id"])); assert projects.archive(str(first["id"]))["status"]=="archived"
    with pytest.raises(KnowledgeError): projects.assign(object_id=str(task["id"]),project_id=str(first["id"]))
    assert next(item for item in projects.list() if item["id"]=="unassigned")["artem"]==0

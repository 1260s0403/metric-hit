from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from metrichit_os.knowledge_store import KnowledgeError
from metrichit_os.project_store import ProjectStore
from metrichit_os.task_router import parse_short_task_command, route_project_task


def database(tmp_path: Path) -> Path:
    path = tmp_path / "memory.sqlite"
    subprocess.run(["node", "scripts/init-memory.mjs", str(path)], check=True, capture_output=True)
    return path


def test_short_command_routes_active_project_without_creating_a_worktree(tmp_path: Path) -> None:
    projects = ProjectStore(database(tmp_path))
    landing, _ = projects.create(name="Лендинг", description="")
    name, task = parse_short_task_command("Ядро старт. Проект «Лендинг»: добавь блок тарифов")
    route = route_project_task(projects, project_name=name, task=task)
    assert route["project"] == {"id": landing["id"], "name": "Лендинг", "subproject_id": None}
    assert route["branch"].startswith("codex/lending/")
    assert route["creates_worktree"] is False
    assert route["requires_resource_declaration"] is True


def test_short_command_rejects_unknown_or_incomplete_project(tmp_path: Path) -> None:
    projects = ProjectStore(database(tmp_path))
    with pytest.raises(KnowledgeError, match="use:"):
        parse_short_task_command("Работаем с лендингом")
    with pytest.raises(KnowledgeError, match="not found"):
        route_project_task(projects, project_name="Лендинг", task="тарифы")

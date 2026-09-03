from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

import pytest

from metrichit_os.chat_continuity import ChatContinuityStore
from metrichit_os.knowledge_store import KnowledgeError
from metrichit_os.project_store import ProjectStore


def fixture(tmp_path: Path) -> tuple[Path, ProjectStore, ChatContinuityStore]:
    path = tmp_path / "memory.sqlite"
    subprocess.run(["node", "scripts/init-memory.mjs", str(path)], check=True, capture_output=True)
    projects = ProjectStore(path)
    metrichit, _ = projects.create(name="MetricHit", description="")
    projects.create(name="Лендинг", description="", parent_project_id=str(metrichit["id"]))
    return path, projects, ChatContinuityStore(path, projects)


def test_transition_saves_checkpoint_and_resume_is_read_only(tmp_path: Path) -> None:
    path, _, continuity = fixture(tmp_path)
    saved = continuity.transition(
        scope_label="Лендинг", branch="codex/lending/tariffs", worktree="tmp/lending-tariffs",
        head="a" * 40, task_name="Тарифы", context_pack_id="pack-1", dirty_files=["work/landing/index.html"],
    )
    assert saved["copy_command"] == "Ядро старт. Лендинг."
    assert saved["checkpoint"]["dirty_files"] == ["work/landing/index.html"]
    with sqlite3.connect(path) as db:
        before = db.execute("SELECT count(*) FROM audit_log").fetchone()[0]
    resumed = continuity.resume("Ядро старт. Лендинг.")
    assert resumed["status"] == "resuming"
    assert resumed["checkpoint"]["branch"] == "codex/lending/tariffs"
    assert resumed["checkpoint"]["context_pack_id"] == "pack-1"
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM audit_log").fetchone()[0] == before


def test_strategy_and_builtin_scopes_use_copyable_russian_commands(tmp_path: Path) -> None:
    _, _, continuity = fixture(tmp_path)
    strategy = continuity.transition(scope_label="Strategy", branch="codex/strategy", worktree="workspace", head="b" * 40)
    assert strategy["copy_command"] == "Ядро старт."
    assert continuity.resume("Ядро старт.")["status"] == "resuming"
    telegram = continuity.resume("Ядро старт. ТГ-бот.")
    assert telegram["status"] == "no_active_task"
    assert telegram["scope"]["kind"] == "workflow"
    assert telegram["scope"]["label"] == "ТГ-бот"
    assert telegram["copy_command"] == "Ядро старт. ТГ-бот."


def test_unknown_scope_is_blocked(tmp_path: Path) -> None:
    _, _, continuity = fixture(tmp_path)
    with pytest.raises(KnowledgeError, match="not found"):
        continuity.resume("Ядро старт. Несуществующий проект.")

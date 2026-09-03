from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from metrichit_os.chat_continuity import ChatContinuityStore
from metrichit_os import cli
from metrichit_os.isolated_worktree import IsolatedWorktree
from metrichit_os.knowledge_store import KnowledgeError
from metrichit_os.project_store import ProjectStore


def fixture(tmp_path: Path) -> tuple[Path, ProjectStore, ChatContinuityStore]:
    path = tmp_path / "memory.sqlite"
    subprocess.run(["node", "scripts/init-memory.mjs", str(path)], check=True, capture_output=True)
    projects = ProjectStore(path)
    metrichit, _ = projects.create(name="MetricHit", description="")
    projects.create(name="Лендинг", description="", parent_project_id=str(metrichit["id"]))
    return path, projects, ChatContinuityStore(path, projects)


def repository(tmp_path: Path) -> tuple[Path, Path]:
    canonical, root = tmp_path / "canonical", tmp_path / "worktrees"
    canonical.mkdir()
    for args in (("init",), ("config", "user.email", "tests@example.invalid"), ("config", "user.name", "Tests")):
        subprocess.run(["git", "-C", str(canonical), *args], check=True, capture_output=True)
    (canonical / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(canonical), "add", "README.md"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(canonical), "commit", "-m", "fixture"], check=True, capture_output=True)
    return canonical, root


def workspace(tmp_path: Path, name: str, branch: str) -> dict[str, str]:
    canonical, root = repository(tmp_path)
    return IsolatedWorktree(canonical, root).prepare(scope_key=name, branch=branch)


def test_transition_saves_verified_checkpoint_and_resume_is_read_only(tmp_path: Path) -> None:
    path, _, continuity = fixture(tmp_path)
    prepared = workspace(tmp_path, "landing-tariffs", "codex/lending/tariffs")
    saved = continuity.transition(
        scope_label="Лендинг", branch=prepared["branch"], canonical_worktree=prepared["canonical_worktree"],
        execution_worktree=prepared["execution_worktree"], head=prepared["head"], task_name="Тарифы", context_pack_id="pack-1",
    )
    assert saved["copy_command"] == "Ядро старт. Лендинг."
    assert saved["checkpoint"]["schema_version"] == 3
    with sqlite3.connect(path) as db:
        before = db.execute("SELECT count(*) FROM audit_log").fetchone()[0]
    resumed = continuity.resume("Ядро старт. Лендинг.")
    assert resumed["status"] == "resuming"
    assert resumed["execution_worktree"] == prepared["execution_worktree"]
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM audit_log").fetchone()[0] == before


def test_active_scope_passport_can_resume_verified_checkpoint(tmp_path: Path) -> None:
    path, projects, continuity = fixture(tmp_path)
    timestamp = "2026-09-03T00:00:00.000Z"
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO scope_passports (id,scope_kind,parent_scope_id,name,summary,status,metadata_json,created_at,updated_at) VALUES (?,?,?,?,?,'active','{}',?,?)", ("scope:subproject:automation", "subproject", "scope:project:metrichit", "Автоматизация", "Площадочные сценарии.", timestamp, timestamp))
        db.execute("INSERT INTO scope_passports (id,scope_kind,parent_scope_id,name,summary,status,metadata_json,created_at,updated_at) VALUES (?,?,?,?,?,'active','{}',?,?)", ("scope:task:automation:avito", "task", "scope:subproject:automation", "Авито", "Изолированный контур Авито.", timestamp, timestamp))
    assert continuity.resume("Ядро старт. Авито.")["status"] == "no_active_task"
    prepared = workspace(tmp_path, "automation-avito", "codex/automation/avito")
    continuity.transition(scope_label="Авито", branch=prepared["branch"], canonical_worktree=prepared["canonical_worktree"], execution_worktree=prepared["execution_worktree"], head=prepared["head"])
    assert continuity.resume("Ядро старт. Авито.")["status"] == "resuming"
    assert not any(project["name"] == "Авито" for project in projects.list())


def test_transition_rejects_unverified_or_dirty_workspace(tmp_path: Path) -> None:
    _, _, continuity = fixture(tmp_path)
    prepared = workspace(tmp_path, "landing", "codex/lending/tariffs")
    with pytest.raises(KnowledgeError, match="clean"):
        continuity.transition(scope_label="Лендинг", branch=prepared["branch"], canonical_worktree=prepared["canonical_worktree"], execution_worktree=prepared["execution_worktree"], head=prepared["head"], dirty_files=["README.md"])
    with pytest.raises(KnowledgeError, match="HEAD"):
        continuity.transition(scope_label="Лендинг", branch=prepared["branch"], canonical_worktree=prepared["canonical_worktree"], execution_worktree=prepared["execution_worktree"], head="f" * 40)


def test_resume_rejects_legacy_checkpoint(tmp_path: Path) -> None:
    path, _, continuity = fixture(tmp_path)
    prepared = workspace(tmp_path, "landing", "codex/lending/tariffs")
    saved = continuity.transition(scope_label="Лендинг", branch=prepared["branch"], canonical_worktree=prepared["canonical_worktree"], execution_worktree=prepared["execution_worktree"], head=prepared["head"])
    with sqlite3.connect(path) as db:
        checkpoint = dict(saved["checkpoint"])
        checkpoint["schema_version"] = 2
        db.execute("INSERT INTO audit_log (id,type,title,content,data_json,status,author,created_at,updated_at,valid_at,access_level,version,entity_type,entity_id,action) VALUES (?, 'chat_transition_checkpoint', 'Переход в новый чат', ?, ?, 'recorded', 'strategy', ?, ?, ?, 'internal', 1, 'chat_scope', ?, 'create')", (str(uuid4()), checkpoint["continuation_command"], json.dumps(checkpoint), "9999-01-01T00:00:00.000Z", "9999-01-01T00:00:00.000Z", "9999-01-01T00:00:00.000Z", checkpoint["scope_key"]))
    with pytest.raises(KnowledgeError, match="new isolated task"):
        continuity.resume("Ядро старт. Лендинг.")


def test_cli_prepares_workspace_and_immediately_saves_checkpoint(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path, _, continuity = fixture(tmp_path)
    canonical, root = repository(tmp_path)
    assert cli.run_workflow_command([
        "chat-workspace-prepare", "--db", str(path), "--scope", "Лендинг",
        "--canonical-worktree", str(canonical), "--worktree-root", str(root),
        "--branch", "codex/lending/tariffs",
    ]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "checkpoint_saved"
    assert continuity.resume("Ядро старт. Лендинг.")["status"] == "resuming"


def test_parallel_start_isolates_each_telegram_bot(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path, _, continuity = fixture(tmp_path)
    canonical, root = repository(tmp_path)
    for bot in ("Финансы", "Поддержка"):
        assert cli.run_workflow_command([
            "chat-parallel-start", "--db", str(path), "--text", f"Ядро старт. ТГ-боты. {bot}.",
            "--canonical-worktree", str(canonical), "--worktree-root", str(root),
        ]) == 0
        result = json.loads(capsys.readouterr().out)
        assert result["status"] == "checkpoint_saved"
        assert continuity.resume(f"Ядро старт. ТГ-боты. {bot}.")["status"] == "resuming"
    finance = continuity.resume("Ядро старт. ТГ-боты. Финансы.")
    support = continuity.resume("Ядро старт. ТГ-боты. Поддержка.")
    assert finance["execution_worktree"] != support["execution_worktree"]


def test_parallel_start_isolates_named_project_tasks_and_rejects_unknown(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path, _, continuity = fixture(tmp_path)
    canonical, root = repository(tmp_path)
    commands = (
        "Ядро старт. Проект «Лендинг»: добавь блок тарифов.",
        "Ядро старт. Проект «Лендинг»: добавь FAQ.",
    )
    worktrees: list[str] = []
    for command in commands:
        assert cli.run_workflow_command([
            "chat-parallel-start", "--db", str(path), "--text", command,
            "--canonical-worktree", str(canonical), "--worktree-root", str(root),
        ]) == 0
        result = json.loads(capsys.readouterr().out)
        assert result["copy_command"] == command
        worktrees.append(continuity.resume(command)["execution_worktree"])
    assert worktrees[0] != worktrees[1]
    with pytest.raises(KnowledgeError, match="not found"):
        cli.run_workflow_command([
            "chat-parallel-start", "--db", str(path), "--text", "Ядро старт. Проект «Нет»: задача.",
            "--canonical-worktree", str(canonical), "--worktree-root", str(root),
        ])

from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path
from uuid import uuid4

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


def worktrees(tmp_path: Path, name: str) -> tuple[str, str]:
    return str(tmp_path / "canonical"), str(tmp_path / "worktrees" / name)


def test_transition_saves_checkpoint_and_resume_is_read_only(tmp_path: Path) -> None:
    path, _, continuity = fixture(tmp_path)
    canonical_worktree, execution_worktree = worktrees(tmp_path, "lending-tariffs")
    saved = continuity.transition(
        scope_label="Лендинг", branch="codex/lending/tariffs", canonical_worktree=canonical_worktree,
        execution_worktree=execution_worktree,
        head="a" * 40, task_name="Тарифы", context_pack_id="pack-1", dirty_files=["work/landing/index.html"],
    )
    assert saved["copy_command"] == "Ядро старт. Лендинг."
    assert saved["checkpoint"]["dirty_files"] == ["work/landing/index.html"]
    assert saved["checkpoint"]["canonical_worktree"] == canonical_worktree
    assert saved["checkpoint"]["execution_worktree"] == execution_worktree
    assert saved["checkpoint"]["requires_worktree_activation"] is True
    with sqlite3.connect(path) as db:
        before = db.execute("SELECT count(*) FROM audit_log").fetchone()[0]
    resumed = continuity.resume("Ядро старт. Лендинг.")
    assert resumed["status"] == "resuming"
    assert resumed["checkpoint"]["branch"] == "codex/lending/tariffs"
    assert resumed["checkpoint"]["context_pack_id"] == "pack-1"
    assert resumed["execution_worktree"] == execution_worktree
    assert resumed["requires_worktree_activation"] is True
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM audit_log").fetchone()[0] == before


def test_strategy_and_telegram_direction_use_copyable_russian_commands(tmp_path: Path) -> None:
    _, _, continuity = fixture(tmp_path)
    canonical_worktree, execution_worktree = worktrees(tmp_path, "strategy")
    strategy = continuity.transition(
        scope_label="Strategy", branch="codex/strategy", canonical_worktree=canonical_worktree,
        execution_worktree=execution_worktree, head="b" * 40,
    )
    assert strategy["copy_command"] == "Ядро старт."
    assert continuity.resume("Ядро старт.")["status"] == "resuming"
    telegram = continuity.resume("Ядро старт. ТГ-боты.")
    assert telegram["status"] == "no_active_task"
    assert telegram["scope"]["kind"] == "workflow"
    assert telegram["scope"]["label"] == "ТГ-боты"
    assert telegram["copy_command"] == "Ядро старт. ТГ-боты."
    assert continuity.resume("Ядро старт. ТГ-бот.")["scope"]["key"] == telegram["scope"]["key"]


def test_telegram_bots_keep_independent_checkpoints(tmp_path: Path) -> None:
    _, _, continuity = fixture(tmp_path)
    canonical_worktree, finance_worktree = worktrees(tmp_path, "telegram-finance")
    finance = continuity.transition(
        scope_label="ТГ-боты. Финансы", branch="codex/telegram-finance", canonical_worktree=canonical_worktree,
        execution_worktree=finance_worktree,
        head="c" * 40, task_name="Финансовый бот",
    )
    _, support_worktree = worktrees(tmp_path, "telegram-support")
    support = continuity.transition(
        scope_label="ТГ-боты. Поддержка", branch="codex/telegram-support", canonical_worktree=canonical_worktree,
        execution_worktree=support_worktree,
        head="d" * 40, task_name="Бот поддержки",
    )
    assert finance["copy_command"] == "Ядро старт. ТГ-боты. Финансы."
    assert support["copy_command"] == "Ядро старт. ТГ-боты. Поддержка."
    resumed_finance = continuity.resume("Ядро старт. ТГ-боты. Финансы.")
    resumed_support = continuity.resume("Ядро старт. ТГ-боты. Поддержка.")
    assert resumed_finance["checkpoint"]["branch"] == "codex/telegram-finance"
    assert resumed_support["checkpoint"]["branch"] == "codex/telegram-support"
    assert resumed_finance["scope"]["key"] != resumed_support["scope"]["key"]


def test_active_scope_passport_without_project_can_resume_its_checkpoint(tmp_path: Path) -> None:
    path, projects, continuity = fixture(tmp_path)
    timestamp = "2026-09-03T00:00:00.000Z"
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO scope_passports "
            "(id,scope_kind,parent_scope_id,name,summary,status,metadata_json,created_at,updated_at) "
            "VALUES (?,?,?,?,?,'active','{}',?,?)",
            (
                "scope:subproject:automation", "subproject", "scope:project:metrichit", "Автоматизация",
                "Площадочные сценарии.", timestamp, timestamp,
            ),
        )
        db.execute(
            "INSERT INTO scope_passports "
            "(id,scope_kind,parent_scope_id,name,summary,status,metadata_json,created_at,updated_at) "
            "VALUES (?,?,?,?,?,'active','{}',?,?)",
            (
                "scope:task:automation:avito", "task", "scope:subproject:automation", "Авито",
                "Изолированный контур Авито.", timestamp, timestamp,
            ),
        )
    assert not any(project["name"] == "Авито" for project in projects.list())

    first = continuity.resume("Ядро старт. Авито.")
    assert first["status"] == "no_active_task"
    assert first["scope"]["label"] == "Авито"
    assert first["copy_command"] == "Ядро старт. Авито."

    canonical_worktree, execution_worktree = worktrees(tmp_path, "automation-avito")
    saved = continuity.transition(
        scope_label="Авито", branch="codex/automation/avito", canonical_worktree=canonical_worktree,
        execution_worktree=execution_worktree,
        head="e" * 40, task_name="Авито",
    )
    resumed = continuity.resume("Ядро старт. Авито.")
    assert saved["checkpoint"] == resumed["checkpoint"]


def test_unknown_scope_is_blocked(tmp_path: Path) -> None:
    _, _, continuity = fixture(tmp_path)
    with pytest.raises(KnowledgeError, match="not found"):
        continuity.resume("Ядро старт. Несуществующий проект.")


@pytest.mark.parametrize(
    ("canonical_worktree", "execution_worktree", "message"),
    [
        ("canonical", "execution", "absolute"),
        ("", "", "absolute"),
        ("same", "same", "isolated"),
    ],
)
def test_transition_requires_an_absolute_isolated_worktree_contract(
    tmp_path: Path, canonical_worktree: str, execution_worktree: str, message: str,
) -> None:
    _, _, continuity = fixture(tmp_path)
    if canonical_worktree == "same":
        canonical_worktree = execution_worktree = str(tmp_path / "canonical")
    with pytest.raises(KnowledgeError, match=message):
        continuity.transition(
            scope_label="Лендинг", branch="codex/lending/tariffs",
            canonical_worktree=canonical_worktree, execution_worktree=execution_worktree,
            head="f" * 40,
        )


def test_resume_rejects_legacy_unqualified_checkpoint(tmp_path: Path) -> None:
    path, _, continuity = fixture(tmp_path)
    canonical_worktree, execution_worktree = worktrees(tmp_path, "lending-tariffs")
    saved = continuity.transition(
        scope_label="Лендинг", branch="codex/lending/tariffs", canonical_worktree=canonical_worktree,
        execution_worktree=execution_worktree, head="f" * 40,
    )
    with sqlite3.connect(path) as db:
        checkpoint = dict(saved["checkpoint"])
        checkpoint.update(schema_version=1, worktree=execution_worktree)
        for field in ("canonical_worktree", "execution_worktree", "requires_worktree_activation"):
            checkpoint.pop(field)
        db.execute(
            "INSERT INTO audit_log "
            "(id,type,title,content,data_json,status,author,created_at,updated_at,valid_at,access_level,version,entity_type,entity_id,action) "
            "VALUES (?, 'chat_transition_checkpoint', 'Переход в новый чат', ?, ?, 'recorded', 'strategy', ?, ?, ?, 'internal', 1, 'chat_scope', ?, 'create')",
            (
                str(uuid4()), checkpoint["continuation_command"], json.dumps(checkpoint),
                "9999-01-01T00:00:00.000Z", "9999-01-01T00:00:00.000Z", "9999-01-01T00:00:00.000Z",
                checkpoint["scope_key"],
            ),
        )
    with pytest.raises(KnowledgeError, match="new isolated task"):
        continuity.resume("Ядро старт. Лендинг.")

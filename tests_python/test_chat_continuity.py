from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from metrichit_os.chat_continuity import ChatContinuityStore
from metrichit_os import cli
from metrichit_os.editorial_store import WorkflowError
from metrichit_os.handoff import HandoffStore
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


def test_resume_refreshes_a_clean_stale_checkpoint_to_canonical_head(tmp_path: Path) -> None:
    path, _, continuity = fixture(tmp_path)
    projects = ProjectStore(path)
    metrichit = next(project for project in projects.list() if project["name"] == "MetricHit")
    projects.create(name="Потсты/Статьи", description="", parent_project_id=str(metrichit["id"]))
    canonical, root = repository(tmp_path)
    scope = continuity.scope_info("Редакция")
    prepared = IsolatedWorktree(canonical, root).prepare(scope_key=str(scope["key"]), branch="codex/editorial")
    continuity.transition(scope_label="Редакция", branch=prepared["branch"], canonical_worktree=prepared["canonical_worktree"],
                          execution_worktree=prepared["execution_worktree"], head=prepared["head"])
    canonical = Path(prepared["canonical_worktree"])
    (canonical / "README.md").write_text("current\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(canonical), "commit", "-am", "canonical planner fix"], check=True, capture_output=True)
    resumed = continuity.resume("Ядро старт. Редакция.")
    assert resumed["status"] == "resuming"
    assert resumed["checkpoint"]["head"] == subprocess.run(
        ["git", "-C", str(canonical), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()


def test_resume_skips_older_divergent_checkpoint_when_new_current_checkpoint_exists(tmp_path: Path) -> None:
    path, _, continuity = fixture(tmp_path)
    projects = ProjectStore(path)
    metrichit = next(project for project in projects.list() if project["name"] == "MetricHit")
    projects.create(name="Потсты/Статьи", description="", parent_project_id=str(metrichit["id"]))
    canonical, root = repository(tmp_path)
    scope = continuity.scope_info("Редакция")
    old = IsolatedWorktree(canonical, root).prepare(scope_key=str(scope["key"]), branch="codex/editorial-old")
    continuity.transition(scope_label="Редакция", branch=old["branch"], canonical_worktree=old["canonical_worktree"],
                          execution_worktree=old["execution_worktree"], head=old["head"])
    old_path = Path(old["execution_worktree"])
    (old_path / "README.md").write_text("old divergent\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(old_path), "commit", "-am", "old divergent"], check=True, capture_output=True)
    (canonical / "README.md").write_text("canonical current\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(canonical), "commit", "-am", "canonical current"], check=True, capture_output=True)
    current = IsolatedWorktree(canonical, root).prepare(scope_key=f"{scope['key']}:current", branch="codex/editorial-current")
    continuity.transition(scope_label="Редакция", branch=current["branch"], canonical_worktree=current["canonical_worktree"],
                          execution_worktree=current["execution_worktree"], head=current["head"])

    first = continuity.resume("Ядро старт. Редакция.")
    second = continuity.resume("Ядро старт. Редакция.")
    assert first["execution_worktree"] == second["execution_worktree"] == current["execution_worktree"]
    assert first["checkpoint"]["branch"] == second["checkpoint"]["branch"] == "codex/editorial-current"
    assert first["checkpoint"]["head"] == second["checkpoint"]["head"] == current["head"]


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


def test_finish_prepares_one_continuation_only_after_delivered_result(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path, _, continuity = fixture(tmp_path)
    prepared = workspace(tmp_path, "landing", "codex/landing/finish")
    compiled = subprocess.run([
        "node", "scripts/structured-memory.mjs", "compile", "--db", str(path), "--scope", "scope:core",
        "--task-type", "general", "--text", "Исправить переход чата", "--result", "Готовый переход",
        "--card-scope", '["tests_python/test_chat_continuity.py"]', "--first-check", "pytest",
        "--acceptance", '["готово"]', "--forbidden-changes", '["не удалять"]',
    ], check=True, capture_output=True, text=True, encoding="utf-8")
    pack_id = json.loads(compiled.stdout)["pack"]["id"]
    with pytest.raises(KnowledgeError, match="must be delivered"):
        continuity.prepare_for_new_chat(
            scope_label="Лендинг", branch=prepared["branch"], canonical_worktree=prepared["canonical_worktree"],
            execution_worktree=prepared["execution_worktree"], head=prepared["head"], context_pack_id=pack_id,
        )
    subprocess.run([
        "node", "scripts/structured-memory.mjs", "close", "--db", str(path), "--id", pack_id,
        "--result", "Готовый переход", "--checks", '["pytest"]', "--satisfied-acceptance", '["готово"]',
        "--scope-compliant", "true", "--forbidden-observed", "[]",
    ], check=True, capture_output=True, text=True, encoding="utf-8")
    assert cli.run_workflow_command([
        "chat-finish", "--db", str(path), "--scope", "Лендинг", "--branch", prepared["branch"],
        "--canonical-worktree", prepared["canonical_worktree"], "--worktree", prepared["execution_worktree"],
        "--head", prepared["head"], "--context-pack", pack_id,
    ]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "ready_for_new_chat"
    assert result["copy_command"] == "Ядро старт. Лендинг."
    assert continuity.resume(result["copy_command"])["status"] == "resuming"


def test_cli_rejects_supplied_finish_evidence_instead_of_registering_it_as_delivery(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    active = tmp_path / "active"
    active.mkdir()
    source = tmp_path / "asset.png"
    source.write_bytes(b"generated-image")
    assert cli.run_workflow_command([
        "editorial-lifecycle", "--operation", "stage", "--data", json.dumps({
            "worktree": str(active), "key": "cli-lifecycle", "source": str(source),
            "target": "work/articles/assets/article.png",
        }),
    ]) == 0
    staged = json.loads(capsys.readouterr().out)
    assert cli.run_workflow_command([
        "editorial-lifecycle", "--operation", "promote", "--data", json.dumps({
            "staging": staged["staging"]["root"],
            "assets": json.dumps([{ "target": staged["asset"]["target"], "sha256": staged["asset"]["sha256"] }]),
            "artifact-qa": json.dumps({"computed": True, "passed": True}),
        }),
    ]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "promoted_after_qa"
    evidence = {stage: {"passed": True} for stage in (
        "artifact_validation", "commit", "serialized_integration", "domain_reconciliation", "close_card", "clean_checkpoint",
    )}
    with pytest.raises((ValueError, WorkflowError), match="unsupported|evidence"):
        cli.run_workflow_command([
            "editorial-lifecycle", "--operation", "finish", "--data", json.dumps({
                "staging": staged["staging"]["root"], "owner-command": "Заверши задачу.",
                "evidence": json.dumps(evidence),
            }),
        ])
    assert (active / "work/articles/assets/article.png").read_bytes() == b"generated-image"


def test_cli_finish_executes_and_resumes_real_delivery_without_duplicate_operations(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    database, _, _ = fixture(tmp_path)
    canonical, root = repository(tmp_path)
    prepared = IsolatedWorktree(canonical, root).prepare(
        scope_key="editorial-real-finish", branch="codex/editorial-real-finish",
    )
    execution = Path(prepared["execution_worktree"])
    compiled = subprocess.run([
        "node", "scripts/structured-memory.mjs", "compile", "--db", str(database), "--scope", "scope:core",
        "--task-type", "code", "--text", "Проверить реальное завершение редакционной задачи",
        "--result", "Изменение проверено и интегрировано", "--card-scope", '["README.md"]',
        "--first-check", "git diff --check", "--acceptance", '["README интегрирован"]',
        "--forbidden-changes", '["не публиковать"]',
    ], check=True, capture_output=True, text=True, encoding="utf-8")
    pack_id = json.loads(compiled.stdout)["pack"]["id"]
    handoff = HandoffStore(database).create_approved({
        "idempotency_key": "editorial-real-finish-v1",
        "semantic_key": "editorial.real_finish_v1",
        "goal": "Проверить реальное завершение редакционной задачи",
        "scope": ["README.md"],
        "constraints": ["Только изолированный worktree"],
        "acceptance": ["README интегрирован"],
        "source": "owner-approved test fixture",
        "project_id": None,
        "approved_by": "owner",
        "execution_resources": {
            "canonical_worktree": str(canonical.resolve()),
            "worktree": str(execution.resolve()),
            "branch": prepared["branch"],
            "base_head": prepared["head"],
            "paths": ["README.md"], "sqlite": ["data/database/test.sqlite"], "shared": ["integration"],
        },
    })
    developer = "editorial-real-finish-writer"
    HandoffStore(database).claim(handoff["handoff_id"], developer)
    (execution / "README.md").write_text("fixture\nverified editorial lifecycle\n", encoding="utf-8")
    state = tmp_path / "finish-state.json"

    def finish(scope_label: str) -> dict[str, object]:
        result = cli.run_workflow_command([
            "editorial-lifecycle", "--operation", "finish", "--data", json.dumps({
                "owner-command": "Заверши задачу.", "worktree": str(execution.resolve()),
                "canonical-worktree": str(canonical.resolve()), "db": str(database.resolve()),
                "context-pack": pack_id, "handoff-id": handoff["handoff_id"], "developer": developer,
                "check-argv": json.dumps(["git", "diff", "--check"]), "scope-label": scope_label,
                "task": "Реальный editorial finish", "state": str(state.resolve()),
                "commit-message": "test: verify real editorial finish",
            }, ensure_ascii=False),
        ])
        assert result == 0
        return json.loads(capsys.readouterr().out)

    with pytest.raises(WorkflowError, match="editorial-lifecycle"):
        finish("Несуществующий контур")
    interrupted = json.loads(state.read_text(encoding="utf-8"))
    assert interrupted["blocker"]["stage"] == "clean_checkpoint"
    assert interrupted["evidence"]["serialized_integration"]["passed"] is True
    commit = interrupted["evidence"]["commit"]["commit"]
    assert subprocess.run(
        ["git", "-C", str(canonical), "rev-parse", "HEAD"], check=True, capture_output=True, text=True,
    ).stdout.strip() == commit

    delivered = finish("Лендинг")
    assert delivered["status"] == "delivered"
    replayed = finish("Лендинг")
    assert replayed["status"] == "delivered"
    assert replayed["replayed"] is True
    assert replayed["commit"] == commit
    partial_integration = json.loads(state.read_text(encoding="utf-8"))
    partial_integration["status"] = "blocked"
    partial_integration["evidence"].pop("serialized_integration")
    state.write_text(json.dumps(partial_integration), encoding="utf-8")
    recovered = finish("Лендинг")
    assert recovered["status"] == "delivered"
    assert recovered["evidence"]["serialized_integration"]["mode"] == "already_integrated"
    assert subprocess.run(
        ["git", "-C", str(canonical), "rev-list", "--count", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip() == "2"
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT status FROM tasks WHERE id=?", (handoff["handoff_id"],)).fetchone()[0] == "completed"
        assert connection.execute("SELECT status FROM context_packs WHERE id=?", (pack_id,)).fetchone()[0] == "closed"
        assert connection.execute(
            "SELECT count(*) FROM audit_log WHERE type='chat_transition_checkpoint'"
        ).fetchone()[0] == 1
    tampered = json.loads(state.read_text(encoding="utf-8"))
    tampered["evidence"]["commit"]["commit"] = "f" * 40
    state.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(WorkflowError, match="commit_state_mismatch"):
        finish("Лендинг")


def test_resume_rejects_legacy_checkpoint(tmp_path: Path) -> None:
    path, _, continuity = fixture(tmp_path)
    prepared = workspace(tmp_path, "landing", "codex/lending/tariffs")
    scope = continuity.scope_info("Лендинг")
    checkpoint = {
        "schema_version": 2, "scope_key": scope["key"], "scope_label": scope["label"],
        "branch": prepared["branch"], "canonical_worktree": prepared["canonical_worktree"],
        "execution_worktree": prepared["execution_worktree"], "head": prepared["head"],
        "requires_worktree_activation": True, "continuation_command": "Ядро старт. Лендинг.",
    }
    with sqlite3.connect(path) as db:
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


def test_cli_workspace_prepare_reuses_latest_valid_checkpoint(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path, _, continuity = fixture(tmp_path)
    projects = ProjectStore(path)
    metrichit = next(project for project in projects.list() if project["name"] == "MetricHit")
    projects.create(name="Потсты/Статьи", description="", parent_project_id=str(metrichit["id"]))
    canonical, root = repository(tmp_path)
    scope = continuity.scope_info("Редакция")
    old = IsolatedWorktree(canonical, root).prepare(scope_key=str(scope["key"]), branch="codex/editorial-old")
    continuity.transition(scope_label="Редакция", branch=old["branch"], canonical_worktree=old["canonical_worktree"],
                          execution_worktree=old["execution_worktree"], head=old["head"])
    old_path = Path(old["execution_worktree"])
    (old_path / "README.md").write_text("old divergent\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(old_path), "commit", "-am", "old divergent"], check=True, capture_output=True)
    (canonical / "README.md").write_text("canonical current\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(canonical), "commit", "-am", "canonical current"], check=True, capture_output=True)
    current = IsolatedWorktree(canonical, root).prepare(scope_key=f"{scope['key']}:current", branch="codex/editorial-current")
    continuity.transition(scope_label="Редакция", branch=current["branch"], canonical_worktree=current["canonical_worktree"],
                          execution_worktree=current["execution_worktree"], head=current["head"])

    for _ in range(2):
        assert cli.run_workflow_command([
            "chat-workspace-prepare", "--db", str(path), "--scope", "Редакция",
            "--canonical-worktree", str(canonical), "--worktree-root", str(root),
        ]) == 0
        result = json.loads(capsys.readouterr().out)
        assert result["status"] == "resuming"
        assert result["execution_worktree"] == current["execution_worktree"]
        assert result["checkpoint"]["branch"] == "codex/editorial-current"
        assert result["checkpoint"]["head"] == current["head"]


def test_workspace_prepare_keeps_explicit_new_context_pack_separate_from_old_checkpoint(tmp_path: Path) -> None:
    path, _, continuity = fixture(tmp_path)
    canonical, root = repository(tmp_path)
    old = IsolatedWorktree(canonical, root).prepare(scope_key="landing-old", branch="codex/landing/old")
    continuity.transition(
        scope_label="Лендинг", branch=old["branch"], canonical_worktree=old["canonical_worktree"],
        execution_worktree=old["execution_worktree"], head=old["head"], context_pack_id="old-pack",
    )

    prepared = continuity.prepare_workspace(
        scope_label="Лендинг", canonical_worktree=str(canonical), worktree_root=str(root),
        branch="codex/landing/new", context_pack_id="new-pack", task_name="Новая задача",
    )

    assert prepared["status"] == "checkpoint_saved"
    assert prepared["checkpoint"]["context_pack_id"] == "new-pack"
    assert prepared["checkpoint"]["branch"] == "codex/landing/new"
    assert prepared["checkpoint"]["execution_worktree"] != old["execution_worktree"]


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

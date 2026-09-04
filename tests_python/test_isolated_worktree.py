from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import metrichit_os.isolated_worktree as isolated_worktree
from metrichit_os.isolated_worktree import IsolatedWorktree, scope_slug
from metrichit_os.knowledge_store import KnowledgeError


def repo(tmp_path: Path) -> tuple[Path, Path]:
    canonical, root = tmp_path / "repo", tmp_path / "managed"
    canonical.mkdir()
    for command in (("init",), ("config", "user.email", "tests@example.invalid"), ("config", "user.name", "Tests")):
        subprocess.run(["git", "-C", str(canonical), *command], check=True, capture_output=True)
    (canonical / "file.txt").write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(canonical), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(canonical), "commit", "-m", "initial"], check=True, capture_output=True)
    return canonical, root


def test_prepare_creates_then_reuses_real_isolated_worktree(tmp_path: Path) -> None:
    canonical, root = repo(tmp_path)
    service = IsolatedWorktree(canonical, root)
    first = service.prepare(scope_key="scope:avito", branch="codex/automation/avito")
    second = service.prepare(scope_key="scope:avito", branch="codex/automation/avito")
    assert first == second
    assert Path(first["execution_worktree"]).parent == root
    assert first["execution_worktree"] != str(canonical)


def test_prepare_fast_forwards_clean_stale_worktree_to_canonical_head(tmp_path: Path) -> None:
    canonical, root = repo(tmp_path)
    service = IsolatedWorktree(canonical, root)
    prepared = service.prepare(scope_key="scope:editorial", branch="codex/editorial")
    (canonical / "file.txt").write_text("two\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(canonical), "commit", "-am", "canonical update"], check=True, capture_output=True)
    refreshed = service.prepare(scope_key="scope:editorial", branch="codex/editorial")
    assert refreshed["execution_worktree"] == prepared["execution_worktree"]
    assert refreshed["head"] == subprocess.run(
        ["git", "-C", str(canonical), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()


def test_prepare_refuses_existing_unregistered_target_and_branch_collision(tmp_path: Path) -> None:
    canonical, root = repo(tmp_path)
    service = IsolatedWorktree(canonical, root)
    target = root / scope_slug("scope:avito")
    target.parent.mkdir()
    target.mkdir()
    with pytest.raises(KnowledgeError, match="not registered"):
        service.prepare(scope_key="scope:avito", branch="codex/automation/avito")
    target.rmdir()
    service.prepare(scope_key="scope:avito", branch="codex/automation/avito")
    with pytest.raises(KnowledgeError, match="already checked out"):
        service.prepare(scope_key="scope:other", branch="codex/automation/avito")


def test_verify_refuses_dirty_or_wrong_head(tmp_path: Path) -> None:
    canonical, root = repo(tmp_path)
    service = IsolatedWorktree(canonical, root)
    prepared = service.prepare(scope_key="scope:avito", branch="codex/automation/avito")
    with pytest.raises(KnowledgeError, match="HEAD"):
        service.verify(prepared["execution_worktree"], prepared["branch"], "f" * 40)
    (Path(prepared["execution_worktree"]) / "file.txt").write_text("changed\n", encoding="utf-8")
    with pytest.raises(KnowledgeError, match="not clean"):
        service.verify(prepared["execution_worktree"], prepared["branch"], prepared["head"])


def test_rejects_canonical_and_non_direct_managed_paths(tmp_path: Path) -> None:
    canonical, root = repo(tmp_path)
    with pytest.raises(KnowledgeError, match="outside"):
        IsolatedWorktree(canonical, canonical / "worktrees")
    service = IsolatedWorktree(canonical, root)
    with pytest.raises(KnowledgeError, match="isolated"):
        service.verify(canonical, "codex/test", "f" * 40)


def test_git_allows_only_the_resolved_invocation_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    worktree = (tmp_path / "managed" / "scope").resolve()
    captured: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(isolated_worktree.subprocess, "run", fake_run)

    assert isolated_worktree._git(worktree, "status", "--porcelain") == "ok"
    assert captured == [[
        "git", "-c", f"safe.directory={worktree}", "-C", str(worktree), "status", "--porcelain",
    ]]

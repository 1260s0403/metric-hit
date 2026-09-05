from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path

from .knowledge_store import KnowledgeError


_BRANCH = re.compile(r"(?!.*\.\.)(?!.*//)[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")


def _path(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise KnowledgeError("worktree paths must be absolute")
    return path.resolve()


def _same(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left)) == os.path.normcase(str(right))


def _git(cwd: Path, *arguments: str) -> str:
    # Worktrees can be created by an elevated process and resumed by the
    # desktop process.  Do not change the user's global Git configuration:
    # trust only this resolved path for this one Git invocation.
    result = subprocess.run(
        ["git", "-c", f"safe.directory={cwd}", "-C", str(cwd), *arguments],
        text=True, encoding="utf-8",
        capture_output=True, check=False,
    )
    if result.returncode:
        message = result.stderr.strip() or result.stdout.strip() or "Git command failed"
        raise KnowledgeError(message)
    return result.stdout.strip()


def _worktrees(canonical: Path) -> list[dict[str, str]]:
    blocks = _git(canonical, "worktree", "list", "--porcelain").split("\n\n")
    result: list[dict[str, str]] = []
    for block in blocks:
        values: dict[str, str] = {}
        for line in block.splitlines():
            key, _, value = line.partition(" ")
            if key in {"worktree", "HEAD", "branch"}:
                values[key] = value
        if "worktree" in values:
            values["worktree"] = str(Path(values["worktree"]).resolve())
            result.append(values)
    return result


def scope_slug(scope_key: str) -> str:
    readable = re.sub(r"[^a-z0-9]+", "-", scope_key.casefold()).strip("-")[:36] or "scope"
    return f"{readable}-{hashlib.sha256(scope_key.encode('utf-8')).hexdigest()[:10]}"


class IsolatedWorktree:
    """Creates and verifies managed, non-canonical Git worktrees without cleanup."""

    def __init__(self, canonical_worktree: str | Path, worktree_root: str | Path):
        self.canonical = _path(canonical_worktree)
        self.root = _path(worktree_root)
        top_level = Path(_git(self.canonical, "rev-parse", "--show-toplevel")).resolve()
        if not _same(top_level, self.canonical):
            raise KnowledgeError("canonical worktree must be the Git top-level worktree")
        if _same(self.canonical, self.root) or self.root.is_relative_to(self.canonical):
            raise KnowledgeError("managed worktree root must be outside the canonical worktree")

    def _target(self, scope_key: str) -> Path:
        target = (self.root / scope_slug(scope_key)).resolve()
        if target.parent != self.root:
            raise KnowledgeError("managed worktree target is invalid")
        return target

    @staticmethod
    def _branch(branch: str) -> str:
        if not _BRANCH.fullmatch(branch):
            raise KnowledgeError("branch has an invalid format")
        return branch

    def prepare(self, *, scope_key: str, branch: str | None = None, base: str | None = None) -> dict[str, str]:
        target = self._target(scope_key)
        branch = self._branch(branch or f"codex/chat/{scope_slug(scope_key)}")
        registered = _worktrees(self.canonical)
        existing = next((item for item in registered if _same(Path(item["worktree"]), target)), None)
        expected_ref = f"refs/heads/{branch}"
        if existing is not None:
            # Git retains a worktree registration when its directory disappears
            # outside this process.  It cannot be refreshed, and its branch is
            # still considered checked out until the stale registration is
            # pruned.  Prune only this already-missing target, then continue
            # through the ordinary add-and-verify path.
            if not target.is_dir():
                _git(self.canonical, "worktree", "prune")
                registered = _worktrees(self.canonical)
                existing = next((item for item in registered if _same(Path(item["worktree"]), target)), None)
                if existing is not None:
                    raise KnowledgeError("managed worktree target is registered but unavailable")
            else:
                return self.refresh(target, branch)
        if target.exists():
            raise KnowledgeError("managed worktree target already exists but is not registered by Git")
        if any(item.get("branch") == expected_ref for item in registered):
            raise KnowledgeError("requested branch is already checked out by another worktree")
        if self.root.exists() and not self.root.is_dir():
            raise KnowledgeError("managed worktree root is not a directory")
        self.root.mkdir(parents=True, exist_ok=True)
        branch_exists = subprocess.run(
            ["git", "-C", str(self.canonical), "show-ref", "--verify", "--quiet", expected_ref],
            capture_output=True, check=False,
        ).returncode == 0
        if branch_exists:
            _git(self.canonical, "worktree", "add", str(target), branch)
        else:
            base_ref = base or "HEAD"
            _git(self.canonical, "rev-parse", "--verify", f"{base_ref}^{{commit}}")
            _git(self.canonical, "worktree", "add", "-b", branch, str(target), base_ref)
        head = _git(target, "rev-parse", "HEAD")
        return self.verify(target, branch, head)

    def refresh(self, execution_worktree: str | Path, branch: str) -> dict[str, str]:
        """Bring a clean registered worktree forward to canonical HEAD, never by force."""
        target = _path(execution_worktree)
        branch = self._branch(branch)
        expected_ref = f"refs/heads/{branch}"
        item = next((entry for entry in _worktrees(self.canonical) if _same(Path(entry["worktree"]), target)), None)
        if item is None or item.get("branch") != expected_ref:
            raise KnowledgeError("execution worktree is not registered with the checkpoint branch")
        if _git(target, "status", "--porcelain"):
            raise KnowledgeError("managed worktree is not clean")
        canonical_head = _git(self.canonical, "rev-parse", "HEAD")
        current_head = _git(target, "rev-parse", "HEAD")
        if current_head != canonical_head:
            try:
                _git(target, "merge", "--ff-only", canonical_head)
            except KnowledgeError as error:
                raise KnowledgeError("managed worktree cannot fast-forward to canonical HEAD") from error
        return self.verify(target, branch, _git(target, "rev-parse", "HEAD"))

    def verify(self, execution_worktree: str | Path, branch: str, head: str) -> dict[str, str]:
        target = _path(execution_worktree)
        branch = self._branch(branch)
        if _same(target, self.canonical) or target.parent != self.root:
            raise KnowledgeError("execution worktree is not an isolated managed worktree")
        expected_ref = f"refs/heads/{branch}"
        item = next((entry for entry in _worktrees(self.canonical) if _same(Path(entry["worktree"]), target)), None)
        if item is None or item.get("branch") != expected_ref:
            raise KnowledgeError("execution worktree is not registered with the checkpoint branch")
        actual_head = _git(target, "rev-parse", "HEAD").lower()
        if not re.fullmatch(r"[0-9a-f]{40,64}", head.casefold()) or actual_head != head.casefold():
            raise KnowledgeError("execution worktree HEAD does not match the checkpoint")
        if _git(target, "status", "--porcelain"):
            raise KnowledgeError("execution worktree is not clean")
        return {"canonical_worktree": str(self.canonical), "execution_worktree": str(target), "branch": branch, "head": actual_head}

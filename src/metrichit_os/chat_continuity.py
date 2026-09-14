from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

from .knowledge_store import KnowledgeError
from .isolated_worktree import IsolatedWorktree
from .project_store import ProjectStore
from .task_router import parse_short_task_command, project_task_scope


BUILTIN_SCOPES = {"редакция": "Редакция"}
TELEGRAM_DIRECTION = "ТГ-боты"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _normal(value: str) -> str:
    return " ".join(value.casefold().replace("ё", "е").replace("-", " ").split())


def _scope_key(value: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"metrichit-chat-scope:{value}"))


def parse_start_command(text: str) -> str:
    match = re.fullmatch(r"\s*ядро\s+старт\s*\.?\s*(.*?)\s*\.?\s*", text, re.IGNORECASE)
    if not match:
        raise KnowledgeError("use: Ядро старт. or Ядро старт. Название.")
    return match.group(1).strip() or "Strategy"


class ChatContinuityStore:
    def __init__(self, path: Path, projects: ProjectStore):
        self.path = path.resolve()
        self.projects = projects

    def _scope(self, label: str) -> dict[str, object]:
        normalized = _normal(label)
        if normalized in {"strategy", "стратегия", "ядро"}:
            return {"key": _scope_key("strategy"), "kind": "strategy", "label": "Strategy", "project_id": None, "subproject_id": None}
        if normalized.startswith("проект "):
            project_name, task = parse_short_task_command(label)
            return project_task_scope(self.projects, project_name=project_name, task=task)
        telegram_parts = [part.strip() for part in re.split(r"\s*\.\s*", label) if part.strip()]
        if telegram_parts and _normal(telegram_parts[0]) in {"тг бот", "тг боты"}:
            if len(telegram_parts) > 2:
                raise KnowledgeError("use: Ядро старт. ТГ-боты. Название.")
            bot_name = telegram_parts[1] if len(telegram_parts) == 2 else None
            if bot_name:
                return {
                    "key": _scope_key(f"workflow:telegram-bots:{_normal(bot_name)}"),
                    "kind": "telegram_bot", "label": f"{TELEGRAM_DIRECTION}. {bot_name}",
                    "project_id": None, "subproject_id": None,
                }
            return {
                "key": _scope_key("workflow:telegram-bots"), "kind": "workflow",
                "label": TELEGRAM_DIRECTION, "project_id": None, "subproject_id": None,
            }
        display = BUILTIN_SCOPES.get(normalized)
        search = "Потсты/Статьи" if normalized == "редакция" else label
        matches = [
            item for item in self.projects.list()
            if item.get("status") == "active" and _normal(str(item.get("name", ""))) == _normal(search)
        ]
        if len(matches) > 1:
            raise KnowledgeError("scope name is ambiguous")
        if matches:
            item = matches[0]
            parent = item.get("parent_project_id")
            return {
                "key": _scope_key(f"project:{item['id']}"), "kind": "project", "label": display or str(item["name"]),
                "project_id": str(parent or item["id"]),
                "subproject_id": str(item["id"]) if parent else None,
            }
        with sqlite3.connect(self.path) as db:
            passports = [
                row for row in db.execute(
                    "SELECT id,scope_kind,name FROM scope_passports WHERE status='active'",
                ).fetchall()
                if _normal(str(row[2])) == normalized
            ]
        if len(passports) > 1:
            raise KnowledgeError("scope name is ambiguous")
        if passports:
            passport_id, scope_kind, name = passports[0]
            return {
                "key": _scope_key(f"passport:{passport_id}"), "kind": str(scope_kind), "label": str(name),
                "project_id": None, "subproject_id": None,
            }
        raise KnowledgeError("active scope was not found")

    @staticmethod
    def _command(scope: dict[str, object]) -> str:
        return "Ядро старт." if scope["kind"] == "strategy" else f"Ядро старт. {scope['label']}."

    @staticmethod
    def _worktree_contract(canonical_worktree: str, execution_worktree: str) -> tuple[str, str]:
        canonical = Path(canonical_worktree)
        execution = Path(execution_worktree)
        if not canonical.is_absolute() or not execution.is_absolute():
            raise KnowledgeError("canonical and execution worktrees must be absolute paths")
        canonical_path = str(canonical.resolve())
        execution_path = str(execution.resolve())
        if canonical_path == execution_path:
            raise KnowledgeError("execution worktree must be isolated from the canonical worktree")
        return canonical_path, execution_path

    def scope_info(self, label: str) -> dict[str, object]:
        return self._scope(label)

    def transition(self, *, scope_label: str, branch: str, canonical_worktree: str,
                   execution_worktree: str, head: str,
                   task_name: str | None = None, context_pack_id: str | None = None,
                   dirty_files: list[str] | None = None) -> dict[str, object]:
        scope = self._scope(scope_label)
        canonical_path, execution_path = self._worktree_contract(
            canonical_worktree, execution_worktree,
        )
        files = dirty_files or []
        if files:
            raise KnowledgeError("an isolated continuation checkpoint requires a clean worktree")
        if any(not isinstance(item, str) or not item.strip() for item in files):
            raise KnowledgeError("dirty files must contain paths")
        verified = IsolatedWorktree(canonical_path, str(Path(execution_path).parent)).verify(
            execution_path, branch, head,
        )
        timestamp = _utc()
        command = self._command(scope)
        checkpoint = {
            "schema_version": 3, "scope_key": scope["key"], "scope_label": scope["label"],
            "project_id": scope["project_id"], "subproject_id": scope["subproject_id"],
            "task_name": (task_name or str(scope["label"])).strip(), "branch": verified["branch"],
            "canonical_worktree": verified["canonical_worktree"], "execution_worktree": verified["execution_worktree"],
            "requires_worktree_activation": True, "head": verified["head"], "dirty_files": files,
            "context_pack_id": context_pack_id, "continuation_command": command,
            "recorded_at": timestamp,
        }
        with sqlite3.connect(self.path) as db:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute(
                "INSERT INTO audit_log (id,type,title,content,data_json,status,author,created_at,updated_at,valid_at,access_level,version,entity_type,entity_id,action) "
                "VALUES (?, 'chat_transition_checkpoint', 'Переход в новый чат', ?, ?, 'recorded', 'strategy', ?, ?, ?, 'internal', 1, 'chat_scope', ?, 'create')",
                (str(uuid4()), command, json.dumps(checkpoint, ensure_ascii=False, sort_keys=True), timestamp, timestamp, timestamp, scope["key"]),
            )
        return {"status": "checkpoint_saved", "checkpoint": checkpoint, "copy_command": command}

    def prepare_for_new_chat(self, *, scope_label: str, branch: str,
                             canonical_worktree: str, execution_worktree: str,
                             head: str, context_pack_id: str,
                             task_name: str | None = None) -> dict[str, object]:
        """Create a continuation checkpoint only after the current result is delivered."""
        if not context_pack_id.strip():
            raise KnowledgeError("a delivered context pack is required before preparing a new chat")
        with sqlite3.connect(self.path) as db:
            row = db.execute(
                "SELECT status,payload_json FROM context_packs WHERE id=?", (context_pack_id,),
            ).fetchone()
        if row is None:
            raise KnowledgeError("the current context pack was not found")
        try:
            outcome = json.loads(str(row[1])).get("terminal_outcome")
        except json.JSONDecodeError as error:
            raise KnowledgeError("the current context pack is invalid") from error
        if row[0] != "closed" or outcome != "delivered":
            raise KnowledgeError("the current result must be delivered before preparing a new chat")
        saved = self.transition(
            scope_label=scope_label, branch=branch, canonical_worktree=canonical_worktree,
            execution_worktree=execution_worktree, head=head, task_name=task_name,
            context_pack_id=context_pack_id,
        )
        return {
            "status": "ready_for_new_chat", "checkpoint": saved["checkpoint"],
            "copy_command": saved["copy_command"],
        }

    def prepare_parallel_start(self, *, text: str, canonical_worktree: str,
                               worktree_root: str, base: str | None = None) -> dict[str, object]:
        """Prepare the managed workspace required by one fresh parallel work chat."""
        scope_label = parse_start_command(text)
        scope = self._scope(scope_label)
        if scope["kind"] not in {"telegram_bot", "project_task"}:
            raise KnowledgeError(
                "parallel start supports: Ядро старт. ТГ-боты. Имя. or Ядро старт. Проект «Название»: задача"
            )
        return self.prepare_workspace(
            scope_label=scope_label, canonical_worktree=canonical_worktree,
            worktree_root=worktree_root, base=base,
        )

    def prepare_workspace(self, *, scope_label: str, canonical_worktree: str,
                          worktree_root: str, branch: str | None = None,
                          base: str | None = None, task_name: str | None = None,
                          context_pack_id: str | None = None) -> dict[str, object]:
        """Resume the newest usable checkpoint, or create a fresh isolated workspace."""
        scope = self._scope(scope_label)
        # An explicit branch, task, or context pack identifies a new execution
        # request.  Reusing a checkpoint here would silently replace that
        # request with whichever older task happened to be resumable.
        if branch is None and task_name is None and context_pack_id is None:
            try:
                resumed = self.resume(self._command(scope))
            except KnowledgeError:
                resumed = None
            if resumed is not None and resumed["status"] == "resuming":
                return resumed

        workspace = IsolatedWorktree(canonical_worktree, worktree_root)
        try:
            # A named branch denotes a fresh execution line within a scope.  Its
            # managed directory must therefore be distinct from a prior line of
            # the same scope; otherwise prepare would try to refresh that prior
            # directory against the new branch and correctly fail registration.
            scope_key = str(scope["key"])
            if branch is not None:
                scope_key = f"{scope_key}:branch:{branch}"
            prepared = workspace.prepare(scope_key=scope_key, branch=branch, base=base)
        except KnowledgeError:
            if branch is not None:
                raise
            # Preserve an unusable historical worktree and create a new managed
            # continuation instead of overwriting, resetting, or deleting it.
            prepared = workspace.prepare(
                scope_key=f"{scope['key']}:recovery:{_utc()}", base=base,
            )
        return self.transition(
            scope_label=scope_label, branch=prepared["branch"],
            canonical_worktree=prepared["canonical_worktree"],
            execution_worktree=prepared["execution_worktree"], head=prepared["head"],
            task_name=task_name, context_pack_id=context_pack_id,
        )

    def _activate_checkpoint(self, scope: dict[str, object], checkpoint: object) -> dict[str, object]:
        if not isinstance(checkpoint, dict) or checkpoint.get("scope_key") != scope["key"]:
            raise KnowledgeError("saved chat checkpoint is invalid")
        if checkpoint.get("schema_version") != 3 or checkpoint.get("requires_worktree_activation") is not True:
            raise KnowledgeError("saved checkpoint lacks the isolated worktree contract; start a new isolated task and create a new checkpoint")
        try:
            canonical_path, execution_path = self._worktree_contract(
                str(checkpoint["canonical_worktree"]), str(checkpoint["execution_worktree"]),
            )
        except (KeyError, KnowledgeError) as error:
            raise KnowledgeError("saved checkpoint lacks the isolated worktree contract; start a new isolated task and create a new checkpoint") from error
        if canonical_path != checkpoint["canonical_worktree"] or execution_path != checkpoint["execution_worktree"]:
            raise KnowledgeError("saved checkpoint has a non-canonical isolated worktree contract")
        try:
            workspace = IsolatedWorktree(canonical_path, str(Path(execution_path).parent))
            verified = workspace.refresh(execution_path, str(checkpoint["branch"]))
        except (KeyError, KnowledgeError) as error:
            raise KnowledgeError("saved checkpoint workspace is no longer safe to resume") from error
        if verified["head"] != checkpoint["head"]:
            refreshed = self.transition(
                scope_label=str(scope["label"]), branch=verified["branch"],
                canonical_worktree=verified["canonical_worktree"], execution_worktree=verified["execution_worktree"],
                head=verified["head"], task_name=str(checkpoint.get("task_name") or scope["label"]),
                context_pack_id=checkpoint.get("context_pack_id"),
            )
            checkpoint = refreshed["checkpoint"]
        return {
            "status": "resuming", "scope": scope, "checkpoint": checkpoint,
            "execution_worktree": verified["execution_worktree"], "requires_worktree_activation": True,
            "copy_command": self._command(scope),
        }

    def resume(self, command: str) -> dict[str, object]:
        scope = self._scope(parse_start_command(command))
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(
                "SELECT data_json FROM audit_log WHERE type='chat_transition_checkpoint' AND entity_type='chat_scope' AND entity_id=? ORDER BY created_at DESC,id DESC",
                (scope["key"],),
            ).fetchall()
        if not rows:
            return {
                "status": "strategy_startup" if scope["kind"] == "strategy" else "no_active_task",
                "scope": scope, "copy_command": self._command(scope),
            }
        first_error: KnowledgeError | None = None
        for row in rows:
            try:
                checkpoint = json.loads(str(row["data_json"]))
                return self._activate_checkpoint(scope, checkpoint)
            except (json.JSONDecodeError, KnowledgeError) as error:
                if first_error is None:
                    first_error = error if isinstance(error, KnowledgeError) else KnowledgeError("saved chat checkpoint is invalid")
        assert first_error is not None
        raise first_error

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from .database import read_only_database


class HandoffError(ValueError):
    pass


COORDINATOR_PROFILES = {
    "metrichit.editorial.v1": {
        "scope_id": "scope:subproject:editorial",
        "task_types": {"editorial", "research"},
        "allowed_skills": {
            "editorial": {"content-strategy", "seo-strategy", "copywriting", "image"},
            "research": {"content-strategy", "seo-strategy", "customer-research"},
        },
        "maximum_research_branches": 3,
        "maximum_delegation_depth": 2,
    },
}

EDITORIAL_SCOPE_CHAIN = (
    "scope:core", "scope:project:metrichit", "scope:subproject:editorial",
)


def _utc_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _uuid(key: str) -> str:
    value = hashlib.sha256(f"metrichit-handoff:{key}".encode()).hexdigest()
    return f"{value[:8]}-{value[8:12]}-4{value[13:16]}-a{value[17:20]}-{value[20:32]}"


def _normalize(value: str) -> str:
    return " ".join(value.casefold().replace("ё", "е").split())


def _required_text(payload: dict[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise HandoffError(f"{name} must be a non-empty string")
    return value.strip()


def _text_list(payload: dict[str, Any], name: str) -> list[str]:
    value = payload.get(name)
    if not isinstance(value, list) or not value:
        raise HandoffError(f"{name} must be a non-empty list")
    result = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise HandoffError(f"{name} must contain non-empty strings")
        result.append(item.strip())
    return result


def _orchestration_route(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {
        "profile_id", "parent_context_pack_id", "task_scope_id", "task_type", "scope_chain",
    }:
        raise HandoffError("orchestration must declare profile_id, parent_context_pack_id, task_scope_id, task_type and scope_chain")
    profile_id = _required_text(value, "profile_id")
    profile = COORDINATOR_PROFILES.get(profile_id)
    if profile is None:
        raise HandoffError("unknown or inactive coordinator profile")
    parent_context_pack_id = _required_text(value, "parent_context_pack_id")
    task_scope_id = _required_text(value, "task_scope_id")
    task_type = _required_text(value, "task_type")
    scope_chain = _text_list(value, "scope_chain")
    if task_type not in profile["task_types"]:
        raise HandoffError("task type is not allowed by coordinator profile")
    expected_chain = [*EDITORIAL_SCOPE_CHAIN, task_scope_id]
    if scope_chain != expected_chain or not task_scope_id.startswith("scope:task:"):
        raise HandoffError("coordinator route must use the exact compiler-generated scope chain")
    return {
        "profile_id": profile_id,
        "parent_context_pack_id": parent_context_pack_id,
        "task_scope_id": task_scope_id,
        "task_type": task_type,
        "scope_chain": scope_chain,
        "role": "temporary_read_only_coordinator",
        "lifecycle": {"stage": "routed"},
    }


def _child_card(value: object, handoff: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "result", "scope", "resources", "mandatory_rules", "first_check", "acceptance", "forbidden_changes",
    }:
        raise HandoffError("child execution card is incomplete")
    result = _required_text(value, "result")
    scope = _text_list(value, "scope")
    mandatory_rules = _text_list(value, "mandatory_rules")
    first_check = _required_text(value, "first_check")
    acceptance = _text_list(value, "acceptance")
    forbidden_changes = _text_list(value, "forbidden_changes")
    if not set(scope).issubset(set(handoff["scope"])):
        raise HandoffError("child execution card escapes the approved parent scope")
    resources = _execution_resources(value.get("resources"))
    if resources is None or resources != handoff.get("execution_resources"):
        raise HandoffError("child execution card resources must exactly match the approved handoff resources")
    return {
        "result": result, "scope": scope, "resources": resources,
        "mandatory_rules": mandatory_rules, "first_check": first_check,
        "acceptance": acceptance, "forbidden_changes": forbidden_changes,
    }


def _selected_skills(value: object, profile: dict[str, Any], task_type: str) -> list[str]:
    if not isinstance(value, list):
        raise HandoffError("selected_skills must be a list")
    selected = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise HandoffError("selected_skills must contain identifiers")
        selected.append(item.strip())
    if len(set(selected)) != len(selected):
        raise HandoffError("selected_skills contains duplicates")
    if not set(selected).issubset(profile["allowed_skills"][task_type]):
        raise HandoffError("unknown or disallowed skill")
    return selected


def _validated_orchestration(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise HandoffError("engineering task has invalid orchestration metadata")
    route_fields = {key: value.get(key) for key in (
        "profile_id", "parent_context_pack_id", "task_scope_id", "task_type", "scope_chain",
    )}
    expected = _orchestration_route(route_fields)
    if value.get("role") != expected["role"] or not isinstance(value.get("lifecycle"), dict):
        raise HandoffError("engineering task has invalid orchestration metadata")
    lifecycle = value["lifecycle"]
    stages = {"routed", "coordinator_claimed", "delegated", "worker_in_progress", "worker_submitted",
              "domain_approved", "integrating", "integrated", "completed"}
    if lifecycle.get("stage") not in stages:
        raise HandoffError("engineering task has invalid orchestration lifecycle")
    if lifecycle["stage"] != "routed" and not isinstance(lifecycle.get("coordinator_id"), str):
        raise HandoffError("engineering task has invalid coordinator ownership")
    delegation = value.get("delegation")
    if lifecycle["stage"] in {"delegated", "worker_in_progress", "worker_submitted", "domain_approved", "integrating", "integrated", "completed"}:
        if not isinstance(delegation, dict) or delegation.get("delegation_depth") != 2 or not isinstance(delegation.get("worker_id"), str):
            raise HandoffError("engineering task has invalid delegation metadata")
        profile = COORDINATOR_PROFILES[value["profile_id"]]
        _selected_skills(delegation.get("selected_skills"), profile, value["task_type"])
        branches = delegation.get("research_branches")
        if not isinstance(branches, int) or isinstance(branches, bool) or not 0 <= branches <= profile["maximum_research_branches"]:
            raise HandoffError("engineering task has invalid research branch declaration")
    return value


def _resource_path(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HandoffError(f"{label} must contain non-empty strings")
    normalized = value.strip().replace("\\", "/").rstrip("/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ":" in normalized or any(part in {"", ".", ".."} for part in path.parts):
        raise HandoffError(f"{label} must contain repository-relative paths")
    return path.as_posix()


def _execution_resources(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise HandoffError("execution_resources must be an object")
    expected = {"canonical_worktree", "worktree", "branch", "base_head", "paths", "sqlite", "shared"}
    if set(value) != expected:
        raise HandoffError("execution_resources must declare canonical_worktree, worktree, branch, base_head, paths, sqlite and shared")
    canonical = _required_text(value, "canonical_worktree")
    worktree = _required_text(value, "worktree")
    if not Path(canonical).is_absolute() or not Path(worktree).is_absolute():
        raise HandoffError("execution worktrees must be absolute paths")
    canonical = str(Path(canonical).resolve())
    worktree = str(Path(worktree).resolve())
    if canonical.casefold() == worktree.casefold():
        raise HandoffError("parallel writer cannot use the canonical worktree")
    branch = _required_text(value, "branch")
    if not re.fullmatch(r"(?!.*\.\.)(?!.*//)[A-Za-z0-9][A-Za-z0-9._/-]{0,127}", branch):
        raise HandoffError("execution branch has an invalid format")
    base_head = _required_text(value, "base_head").lower()
    if not re.fullmatch(r"[0-9a-f]{7,64}", base_head):
        raise HandoffError("base_head must be a 7-64 character hexadecimal Git commit hash")
    paths = [_resource_path(item, "execution_resources.paths") for item in _text_list(value, "paths")]
    sqlite_resources = value.get("sqlite")
    shared_resources = value.get("shared")
    if not isinstance(sqlite_resources, list) or not isinstance(shared_resources, list):
        raise HandoffError("execution_resources.sqlite and shared must be lists")
    sqlite_paths = [_resource_path(item, "execution_resources.sqlite") for item in sqlite_resources]
    shared = []
    for item in shared_resources:
        if not isinstance(item, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._:-]{0,127}", item.strip().casefold()):
            raise HandoffError("execution_resources.shared contains an invalid resource")
        shared.append(item.strip().casefold())
    for label, items in (("paths", paths), ("sqlite", sqlite_paths), ("shared", shared)):
        if len(set(item.casefold() for item in items)) != len(items):
            raise HandoffError(f"execution_resources.{label} contains duplicates")
    return {"canonical_worktree": canonical, "worktree": worktree, "branch": branch, "base_head": base_head,
            "paths": paths, "sqlite": sqlite_paths, "shared": shared}


def _paths_overlap(left: str, right: str) -> bool:
    left_parts = tuple(part.casefold() for part in PurePosixPath(left).parts)
    right_parts = tuple(part.casefold() for part in PurePosixPath(right).parts)
    shortest = min(len(left_parts), len(right_parts))
    return left_parts[:shortest] == right_parts[:shortest]


def _exclusive_resources(resources: dict[str, Any]) -> bool:
    exclusive_shared = {"core", "policy", "config", "migration", "dependency", "shared_runtime", "central_db", "memory", "context_pack", "integration"}
    if exclusive_shared.intersection(resources["shared"]):
        return True
    protected = ("agents.md", "documents/operating-context.md", "documents/structured-memory.md", "documents/roadmap.md",
                 "knowledge/approved", "data/database", "migrations", "pyproject.toml", "package.json", "package-lock.json",
                 "requirements.txt", "src/metrichit_os/migrations")
    return any(_paths_overlap(path, item) for path in resources["paths"] for item in protected)


def _title(goal: str) -> str:
    compact = " ".join(goal.split())
    return compact if len(compact) <= 80 else compact[:79].rstrip() + "…"


def _render_delta(delta: dict[str, Any]) -> str:
    lines = [f"Цель: {delta['goal']}", "", "Scope:"]
    lines.extend(f"- {item}" for item in delta["scope"])
    lines.extend(["", "Ограничения:"])
    lines.extend(f"- {item}" for item in delta["constraints"])
    lines.extend(["", "Acceptance:"])
    lines.extend(f"- {item}" for item in delta["acceptance"])
    lines.extend(["", f"Источник решения: {delta['source']}"])
    if delta.get("project_id"):
        lines.append(f"Проект: {delta['project_id']}")
    return "\n".join(lines)


class HandoffStore:
    ALLOWED_FIELDS = {
        "idempotency_key", "semantic_key", "goal", "scope", "constraints", "acceptance",
        "source", "project_id", "approved_by", "supersedes_candidate_id", "execution_resources", "orchestration",
    }

    def __init__(self, database_path: Path):
        self.path = database_path.resolve()
        if not self.path.is_file():
            raise FileNotFoundError("Database does not exist")

    def create_approved(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise HandoffError("handoff data must be a JSON object")
        unexpected = sorted(set(payload) - self.ALLOWED_FIELDS)
        if unexpected:
            raise HandoffError(f"unsupported handoff fields: {', '.join(unexpected)}")
        idempotency_key = _required_text(payload, "idempotency_key")
        semantic_key = _required_text(payload, "semantic_key")
        if not re.fullmatch(r"[a-z0-9]+(?:[._-][a-z0-9]+)+", semantic_key):
            raise HandoffError("semantic_key has an invalid format")
        approved_by = _required_text(payload, "approved_by")
        if approved_by != "owner":
            raise HandoffError("approved_by must be owner for an approved decision handoff")
        source_ref = _required_text(payload, "source")
        project_id = payload.get("project_id")
        if project_id is not None and (not isinstance(project_id, str) or not project_id.strip()):
            raise HandoffError("project_id must be a UUID string or null")
        project_id = project_id.strip() if isinstance(project_id, str) else None
        supersedes = payload.get("supersedes_candidate_id")
        if supersedes is not None and (not isinstance(supersedes, str) or not supersedes.strip()):
            raise HandoffError("supersedes_candidate_id must be a UUID string or null")
        supersedes = supersedes.strip() if isinstance(supersedes, str) else None
        delta = {
            "goal": _required_text(payload, "goal"),
            "scope": _text_list(payload, "scope"),
            "constraints": _text_list(payload, "constraints"),
            "acceptance": _text_list(payload, "acceptance"),
            "source": source_ref,
            "project_id": project_id,
            "execution_resources": _execution_resources(payload.get("execution_resources")),
            "orchestration": _orchestration_route(payload.get("orchestration")),
        }
        if delta["orchestration"] is not None and delta["execution_resources"] is None:
            raise HandoffError("orchestration writer requires declared execution resources")
        fingerprint_input = {
            "semantic_key": semantic_key, "approved_by": approved_by,
            "supersedes_candidate_id": supersedes, **delta,
        }
        fingerprint = hashlib.sha256(
            json.dumps(fingerprint_input, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        semantic_basis = {
            "goal": _normalize(delta["goal"]),
            "scope": [_normalize(item) for item in delta["scope"]],
            "constraints": [_normalize(item) for item in delta["constraints"]],
            "acceptance": [_normalize(item) for item in delta["acceptance"]],
        }
        semantic_fingerprint = hashlib.sha256(
            json.dumps(semantic_basis, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        source_id = _uuid(f"source:{idempotency_key}")
        document_id = _uuid(f"document:{idempotency_key}")
        version_id = _uuid(f"version:{idempotency_key}")
        candidate_id = _uuid(f"candidate:{idempotency_key}")
        task_id = _uuid(f"task:{idempotency_key}")
        now = _utc_text()
        title = _title(delta["goal"])
        rendered = _render_delta(delta)
        candidate_data = {
            "decision_delta": delta,
            "fingerprint": fingerprint,
            "semantic_fingerprint": semantic_fingerprint,
            "handoff_task_id": task_id,
            "supersedes_candidate_id": supersedes,
        }
        task_data = {
            "priority": "normal", "due_date": None, "standalone": True, "project_id": project_id,
            "handoff": {
                "kind": "codex_engineering", "idempotency_key": idempotency_key,
                "decision_candidate_id": candidate_id, "decision_semantic_key": semantic_key,
                "source_id": source_id,
                "lifecycle": {"status": "ready"},
                **delta,
            },
        }
        source_data = {"reference": source_ref, "authority": "explicit_owner_approval", "fingerprint": fingerprint}

        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute("SELECT data_json,status,source_id FROM memory_candidates WHERE id=?", (candidate_id,)).fetchone()
            if existing is not None:
                metadata = self._object(existing["data_json"])
                if metadata.get("fingerprint") != fingerprint or existing["status"] != "approved":
                    raise HandoffError("idempotency key already belongs to a different or incomplete handoff")
                result = self._load_task(connection, task_id)
                if existing["source_id"] != result["decision"]["source_id"]:
                    raise HandoffError("approved handoff has inconsistent source linkage")
                return result

            if project_id:
                project = connection.execute(
                    "SELECT status FROM documents WHERE id=? AND type='project'", (project_id,),
                ).fetchone()
                if project is None or project["status"] != "active":
                    raise HandoffError("project must exist and be active")

            same_key = connection.execute(
                "SELECT id,status,data_json FROM memory_candidates WHERE semantic_key=? AND status IN ('pending','approved') ORDER BY reviewed_at DESC,updated_at DESC,id DESC",
                (semantic_key,),
            ).fetchall()
            pending = [row for row in same_key if row["status"] == "pending"]
            approved = [row for row in same_key if row["status"] == "approved"]
            if pending:
                raise HandoffError("pending semantic duplicate blocks decision handoff")
            if approved:
                latest = str(approved[0]["id"])
                if supersedes != latest:
                    raise HandoffError("semantic evolution requires supersedes_candidate_id for the latest approved decision")
            elif supersedes is not None:
                raise HandoffError("supersedes_candidate_id does not match an approved decision")

            normalized = _normalize(rendered)
            for row in connection.execute(
                "SELECT semantic_key,content,data_json FROM memory_candidates WHERE status IN ('pending','approved') AND semantic_key<>?",
                (semantic_key,),
            ):
                other = self._object(row["data_json"])
                if other.get("semantic_fingerprint") == semantic_fingerprint or (row["content"] and _normalize(str(row["content"])) == normalized):
                    raise HandoffError(f"semantic duplicate already exists as {row['semantic_key']}")
            open_conflict = connection.execute(
                """SELECT 1 FROM memory_conflicts c
                   LEFT JOIN memory_candidates mc ON mc.id=c.candidate_id
                   LEFT JOIN memory_items mi ON mi.id=c.existing_memory_item_id
                   WHERE c.status='open' AND (mc.semantic_key=? OR mi.semantic_key=?) LIMIT 1""",
                (semantic_key, semantic_key),
            ).fetchone()
            if open_conflict:
                raise HandoffError("open memory conflict blocks decision handoff")

            if approved:
                previous_data = self._object(approved[0]["data_json"])
                previous_task_id = previous_data.get("handoff_task_id")
                if previous_task_id is not None and (not isinstance(previous_task_id, str) or not previous_task_id):
                    raise HandoffError("superseded decision has invalid handoff linkage")
                if previous_task_id:
                    previous_task = connection.execute(
                        "SELECT id,status,data_json,author,updated_at,version FROM tasks WHERE id=? AND type='standalone_task'",
                        (previous_task_id,),
                    ).fetchone()
                    if previous_task is None:
                        raise HandoffError("superseded decision is missing its engineering task")
                    previous_handoff = self._object(previous_task["data_json"]).get("handoff")
                    if not isinstance(previous_handoff, dict) or previous_handoff.get("decision_candidate_id") != supersedes:
                        raise HandoffError("superseded engineering task has inconsistent decision linkage")
                    if previous_task["status"] in {"pending", "in_progress"}:
                        previous_version = int(previous_task["version"])
                        connection.execute(
                            "UPDATE tasks SET status='cancelled',updated_at=?,version=? WHERE id=?",
                            (now, previous_version + 1, previous_task_id),
                        )
                        connection.execute(
                            "INSERT INTO audit_log (id,type,title,data_json,author,created_at,updated_at,access_level,version,entity_type,entity_id,action) VALUES (?, 'task_change','Codex engineering handoff superseded',?,?,?,?,'restricted',1,'task',?,'update')",
                            (
                                _uuid(f"audit:supersede:{idempotency_key}"),
                                json.dumps({
                                    "old": {"status": previous_task["status"], "updated_at": previous_task["updated_at"], "version": previous_version},
                                    "new": {"status": "cancelled", "updated_at": now, "version": previous_version + 1},
                                }, ensure_ascii=False, sort_keys=True),
                                previous_task["author"], now, now, previous_task_id,
                            ),
                        )

            connection.execute(
                "INSERT INTO sources (id,type,title,content,data_json,status,author,created_at,updated_at,access_level,version) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, ?, ?, 'internal', 1)",
                (source_id, title, source_ref, json.dumps(source_data, ensure_ascii=False, sort_keys=True), approved_by, now, now),
            )
            document_data = json.dumps({"decision_delta": delta, "fingerprint": fingerprint}, ensure_ascii=False, sort_keys=True)
            connection.execute(
                "INSERT INTO documents (id,type,title,content,data_json,status,source_id,author,created_at,updated_at,access_level,version) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, ?, ?, ?, 'internal', 1)",
                (document_id, title, rendered, document_data, source_id, approved_by, now, now),
            )
            connection.execute(
                "INSERT INTO document_versions (id,document_id,type,title,content,data_json,status,source_id,author,created_at,updated_at,access_level,version) VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, ?, ?, ?, 'internal', 1)",
                (version_id, document_id, title, rendered, document_data, source_id, approved_by, now, now),
            )
            connection.execute(
                "INSERT INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,created_at,updated_at,access_level,version) VALUES (?, 'decision', ?, ?, ?, ?, 'pending', ?, ?, ?, ?, 'internal', 1)",
                (candidate_id, semantic_key, title, rendered, json.dumps(candidate_data, ensure_ascii=False, sort_keys=True), source_id, approved_by, now, now),
            )
            connection.execute(
                "UPDATE memory_candidates SET status='approved',reviewed_by=?,reviewed_at=?,review_note=?,updated_at=?,version=version+1 WHERE id=? AND status='pending'",
                (approved_by, now, f"Explicit owner-approved decision delta from {source_ref}", now, candidate_id),
            )
            approved = connection.execute("SELECT status FROM memory_candidates WHERE id=?", (candidate_id,)).fetchone()
            if approved is None or approved["status"] != "approved":
                raise HandoffError("decision candidate was not approved")
            if connection.execute("SELECT 1 FROM memory_conflicts WHERE candidate_id=? AND status='open'", (candidate_id,)).fetchone():
                raise HandoffError("decision approval produced a memory conflict")
            connection.execute(
                "INSERT INTO tasks (id,type,title,content,data_json,status,source_id,author,created_at,updated_at,access_level,version) VALUES (?, 'standalone_task', ?, ?, ?, 'pending', ?, ?, ?, ?, 'internal', 1)",
                (task_id, title, rendered, json.dumps(task_data, ensure_ascii=False, sort_keys=True), source_id, approved_by, now, now),
            )
            connection.execute(
                "INSERT INTO audit_log (id,type,title,data_json,source_id,author,created_at,updated_at,access_level,version,entity_type,entity_id,action) VALUES (?, 'task_change','Codex engineering handoff created',?,?,?,?,?,'restricted',1,'task',?,'create')",
                (_uuid(f"audit:{idempotency_key}"), json.dumps({"new": {"title": title, "decision_candidate_id": candidate_id, "decision_semantic_key": semantic_key}}, ensure_ascii=False, sort_keys=True), source_id, approved_by, now, now, task_id),
            )
            return self._load_task(connection, task_id)

    def next(self) -> dict[str, Any] | None:
        with read_only_database(self.path) as connection:
            return self._next_ready(connection)
        return None

    def dispatcher_next(self) -> dict[str, Any] | None:
        """Return the next ready task without reserving it for a Dispatcher."""
        return self.next()

    def dispatcher_claim_next(self, dispatcher_id: str) -> dict[str, Any] | None:
        """Atomically reserve one ready task before native thread creation.

        A ``dispatching`` task deliberately cannot be selected again.  The
        returned payload is the only input a separate Dispatcher-agent needs;
        native Codex thread creation remains outside this repository.
        """
        dispatcher_id = self._developer_id(dispatcher_id)
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            ready = next((item for item in self._ready_results(connection)
                          if item.get("orchestration") is None and self._claim_blocker(connection, item) is None), None)
            if ready is None:
                return None
            row = self._handoff_row(connection, ready["handoff_id"])
            metadata = self._object(row["data_json"])
            handoff = metadata["handoff"]
            now = _utc_text()
            handoff["lifecycle"].update({"status": "dispatching", "claimed_at": now, "claimed_by": dispatcher_id})
            metadata["handoff"] = handoff
            self._update_lifecycle(connection, row, metadata, "pending", now, "dispatch-claimed")
            result = self._load_task(connection, ready["handoff_id"])
            result["dispatch_payload"] = self._dispatch_payload(result)
            return result

    def dispatcher_record_thread(self, handoff_id: str, thread_id: str, dispatcher_id: str) -> dict[str, Any]:
        handoff_id = self._handoff_id(handoff_id)
        dispatcher_id = self._developer_id(dispatcher_id)
        thread_id = self._thread_id(thread_id)
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            row = self._handoff_row(connection, handoff_id)
            metadata = self._object(row["data_json"])
            handoff = metadata.get("handoff")
            result = self._attested_result(connection, dict(row), metadata, handoff)
            if handoff.get("orchestration") is not None:
                raise HandoffError("orchestrated handoff requires Strategy completion")
            lifecycle = handoff["lifecycle"]
            if lifecycle.get("claimed_by") != dispatcher_id:
                raise HandoffError("handoff is claimed by another dispatcher")
            existing = lifecycle.get("executor_thread_id")
            if existing is not None:
                if existing != thread_id:
                    raise HandoffError("handoff is already linked to a different executor thread")
                return result
            if result["status"] != "dispatching":
                raise HandoffError("handoff must be dispatching before recording an executor thread")
            now = _utc_text()
            lifecycle.update({"status": "in_progress", "executor_thread_id": thread_id, "started_at": now})
            metadata["handoff"] = handoff
            self._update_lifecycle(connection, row, metadata, "in_progress", now, "executor-thread-recorded")
            return self._load_task(connection, handoff_id)

    def dispatcher_complete(self, handoff_id: str, commit_hash: str, result: str, dispatcher_id: str) -> dict[str, Any]:
        return self._complete(handoff_id, commit_hash, result, dispatcher_id, require_thread=True)

    def coordinator_claim(self, handoff_id: str, coordinator_id: str) -> dict[str, Any]:
        handoff_id = self._handoff_id(handoff_id)
        coordinator_id = self._developer_id(coordinator_id)
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            row = self._handoff_row(connection, handoff_id)
            metadata = self._object(row["data_json"])
            handoff = metadata.get("handoff")
            result = self._attested_result(connection, dict(row), metadata, handoff)
            orchestration = handoff.get("orchestration")
            if not isinstance(orchestration, dict):
                raise HandoffError("handoff is not routed to a coordinator")
            lifecycle = orchestration["lifecycle"]
            if lifecycle.get("coordinator_id") is not None:
                if lifecycle.get("coordinator_id") != coordinator_id:
                    raise HandoffError("coordinator route is claimed by another coordinator")
                return result
            if result["status"] != "ready" or lifecycle.get("stage") != "routed":
                raise HandoffError("coordinator route cannot be claimed at this stage")
            lifecycle.update({"stage": "coordinator_claimed", "coordinator_id": coordinator_id, "claimed_at": _utc_text()})
            metadata["handoff"] = handoff
            self._update_lifecycle(connection, row, metadata, "pending", _utc_text(), "coordinator-claimed")
            return self._load_task(connection, handoff_id)

    def delegate_child(self, handoff_id: str, coordinator_id: str, worker_id: str, delegation: dict[str, Any]) -> dict[str, Any]:
        handoff_id = self._handoff_id(handoff_id)
        coordinator_id = self._developer_id(coordinator_id)
        worker_id = self._developer_id(worker_id)
        if not isinstance(delegation, dict) or set(delegation) != {"child_card", "selected_skills", "research_branches", "delegation_depth"}:
            raise HandoffError("delegation must declare child_card, selected_skills, research_branches and delegation_depth")
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            row = self._handoff_row(connection, handoff_id)
            metadata = self._object(row["data_json"])
            handoff = metadata.get("handoff")
            result = self._attested_result(connection, dict(row), metadata, handoff)
            orchestration = handoff.get("orchestration")
            if not isinstance(orchestration, dict):
                raise HandoffError("handoff is not routed to a coordinator")
            lifecycle = orchestration["lifecycle"]
            if lifecycle.get("coordinator_id") != coordinator_id:
                raise HandoffError("wrong coordinator")
            if delegation.get("delegation_depth") != 2:
                raise HandoffError("maximum delegation depth is Strategy to coordinator to worker")
            profile = COORDINATOR_PROFILES[orchestration["profile_id"]]
            research_branches = delegation.get("research_branches")
            if not isinstance(research_branches, int) or isinstance(research_branches, bool) or not 0 <= research_branches <= profile["maximum_research_branches"]:
                raise HandoffError("research_branches must be between zero and three")
            child_card = _child_card(delegation.get("child_card"), handoff)
            selected = _selected_skills(delegation.get("selected_skills"), profile, orchestration["task_type"])
            exact = {"worker_id": worker_id, "delegation_depth": 2, "child_card": child_card,
                     "selected_skills": selected, "research_branches": research_branches}
            existing = orchestration.get("delegation")
            if existing == exact:
                return result
            if lifecycle.get("stage") != "coordinator_claimed":
                raise HandoffError("coordinator must claim the route before delegation")
            orchestration["delegation"] = exact
            lifecycle.update({"stage": "delegated", "delegated_at": _utc_text()})
            metadata["handoff"] = handoff
            self._update_lifecycle(connection, row, metadata, "pending", _utc_text(), "child-delegated")
            return self._load_task(connection, handoff_id)

    def claim_worker(self, handoff_id: str, worker_id: str) -> dict[str, Any]:
        return self.claim(handoff_id, worker_id)

    def worker_submit(self, handoff_id: str, worker_id: str, evidence: dict[str, Any]) -> dict[str, Any]:
        handoff_id = self._handoff_id(handoff_id)
        worker_id = self._developer_id(worker_id)
        if not isinstance(evidence, dict) or set(evidence) != {"commit_hash", "checks", "acceptance", "clean_git", "result"}:
            raise HandoffError("worker evidence is incomplete")
        commit_hash = self._git_hash(evidence.get("commit_hash"), "commit_hash")
        checks = _text_list(evidence, "checks")
        acceptance = _text_list(evidence, "acceptance")
        result_text = _required_text(evidence, "result")
        if evidence.get("clean_git") is not True:
            raise HandoffError("worker evidence must attest clean Git")
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            row = self._handoff_row(connection, handoff_id)
            metadata = self._object(row["data_json"])
            handoff = metadata.get("handoff")
            current = self._attested_result(connection, dict(row), metadata, handoff)
            orchestration = handoff.get("orchestration")
            if not isinstance(orchestration, dict) or current["status"] != "in_progress":
                raise HandoffError("worker must own an in-progress orchestrated handoff")
            lifecycle = orchestration["lifecycle"]
            if handoff["lifecycle"].get("claimed_by") != worker_id or orchestration.get("delegation", {}).get("worker_id") != worker_id:
                raise HandoffError("wrong worker")
            submission = {"commit_hash": commit_hash, "checks": checks, "acceptance": acceptance,
                          "clean_git": True, "result": result_text}
            if lifecycle.get("stage") in {"worker_submitted", "domain_approved", "integrating", "integrated"} \
                    and orchestration.get("submission") == submission:
                return current
            if lifecycle.get("stage") not in {"worker_in_progress", "delegated"}:
                raise HandoffError("worker cannot submit at this orchestration stage")
            card = orchestration["delegation"]["child_card"]
            if card["first_check"] not in checks or not all(item in acceptance for item in card["acceptance"]):
                raise HandoffError("worker evidence does not satisfy the child execution card")
            prior = orchestration.get("submission")
            if prior is not None:
                orchestration.setdefault("attempts", []).append({"submission": prior, "review": orchestration.get("review")})
            orchestration["submission"] = submission
            orchestration.pop("review", None)
            lifecycle.update({"stage": "worker_submitted", "submitted_at": _utc_text()})
            metadata["handoff"] = handoff
            self._update_lifecycle(connection, row, metadata, "in_progress", _utc_text(), "worker-submitted")
            return self._load_task(connection, handoff_id)

    def coordinator_review(self, handoff_id: str, coordinator_id: str, decision: str, evidence: list[str]) -> dict[str, Any]:
        handoff_id = self._handoff_id(handoff_id)
        coordinator_id = self._developer_id(coordinator_id)
        if decision not in {"approve", "reject"}:
            raise HandoffError("coordinator decision must be approve or reject")
        evidence_items = _text_list({"evidence": evidence}, "evidence")
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            row = self._handoff_row(connection, handoff_id)
            metadata = self._object(row["data_json"])
            handoff = metadata.get("handoff")
            current = self._attested_result(connection, dict(row), metadata, handoff)
            orchestration = handoff.get("orchestration")
            if not isinstance(orchestration, dict) or orchestration["lifecycle"].get("coordinator_id") != coordinator_id:
                raise HandoffError("wrong coordinator")
            lifecycle = orchestration["lifecycle"]
            exact = {"decision": decision, "evidence": evidence_items}
            if lifecycle.get("stage") in {"domain_approved", "integrating", "integrated"} and orchestration.get("review") == exact:
                return current
            if lifecycle.get("stage") == "delegated" and decision == "reject" and orchestration.get("review") == exact:
                return current
            if lifecycle.get("stage") != "worker_submitted":
                raise HandoffError("coordinator review requires worker submission")
            orchestration["review"] = exact
            if decision == "approve":
                lifecycle.update({"stage": "domain_approved", "reviewed_at": _utc_text()})
            else:
                orchestration.setdefault("attempts", []).append({"submission": orchestration.get("submission"), "review": exact})
                orchestration.pop("submission", None)
                lifecycle.update({"stage": "delegated", "reviewed_at": _utc_text()})
            metadata["handoff"] = handoff
            self._update_lifecycle(connection, row, metadata, "in_progress", _utc_text(), f"domain-{decision}")
            return self._load_task(connection, handoff_id)

    def claim(self, handoff_id: str, developer_id: str) -> dict[str, Any]:
        handoff_id = self._handoff_id(handoff_id)
        developer_id = self._developer_id(developer_id)
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            row = self._handoff_row(connection, handoff_id)
            metadata = self._object(row["data_json"])
            handoff = metadata.get("handoff")
            result = self._attested_result(connection, dict(row), metadata, handoff)
            orchestration = handoff.get("orchestration")
            if isinstance(orchestration, dict):
                orchestration_lifecycle = orchestration["lifecycle"]
                delegation = orchestration.get("delegation")
                if not isinstance(delegation, dict) or delegation.get("worker_id") != developer_id:
                    raise HandoffError("worker is not the delegated writer")
                if result["status"] == "in_progress" and handoff["lifecycle"].get("claimed_by") == developer_id:
                    return result
                if orchestration_lifecycle.get("stage") not in {"delegated", "worker_in_progress"}:
                    raise HandoffError("worker cannot claim at this orchestration stage")
            if result["status"] == "in_progress":
                if handoff["lifecycle"].get("claimed_by") != developer_id:
                    raise HandoffError("handoff is already claimed by another developer")
                return result
            if result["status"] != "ready":
                raise HandoffError("handoff is not ready to claim")
            blocker = self._claim_blocker(connection, result)
            if blocker is not None:
                raise HandoffError(blocker)
            now = _utc_text()
            lifecycle = handoff["lifecycle"]
            lifecycle.update({"status": "in_progress", "claimed_at": now, "claimed_by": developer_id})
            if isinstance(orchestration, dict):
                orchestration["lifecycle"].update({"stage": "worker_in_progress", "worker_started_at": now})
            metadata["handoff"] = handoff
            self._update_lifecycle(connection, row, metadata, "in_progress", now, "claimed")
            return self._load_task(connection, handoff_id)

    def complete(self, handoff_id: str, commit_hash: str, developer_id: str) -> dict[str, Any]:
        return self._complete(handoff_id, commit_hash, "Legacy handoff completion.", developer_id, require_thread=False)

    def begin_integration(self, handoff_id: str, developer_id: str, expected_base_head: str, current_base_head: str, conflict_free: bool) -> dict[str, Any]:
        handoff_id = self._handoff_id(handoff_id)
        developer_id = self._developer_id(developer_id)
        expected = self._git_hash(expected_base_head, "expected_base_head")
        current = self._git_hash(current_base_head, "current_base_head")
        if expected != current:
            raise HandoffError("stale base blocks integration")
        if conflict_free is not True:
            raise HandoffError("merge conflict blocks integration")
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            row = self._handoff_row(connection, handoff_id)
            metadata = self._object(row["data_json"])
            handoff = metadata.get("handoff")
            result = self._attested_result(connection, dict(row), metadata, handoff)
            lifecycle = handoff["lifecycle"]
            orchestration = handoff.get("orchestration")
            evidence = {"status": "integrating", "expected_base_head": expected, "current_base_head": current,
                        "conflict_free": True, "claimed_by": developer_id}
            existing = lifecycle.get("integration")
            if existing is not None:
                comparable = {key: existing.get(key) for key in evidence}
                if comparable.get("status") == "integrated":
                    comparable["status"] = "integrating"
                if comparable != evidence:
                    raise HandoffError("integration lease already has different evidence")
                return result
            if isinstance(orchestration, dict) and orchestration["lifecycle"].get("stage") != "domain_approved":
                raise HandoffError("coordinator domain approval is required before integration")
            if result["status"] != "in_progress" or lifecycle.get("claimed_by") != developer_id:
                raise HandoffError("writer must own an in-progress handoff before integration")
            if result.get("execution_resources") is None:
                raise HandoffError("integration requires declared execution resources")
            for active in self._active_results(connection):
                integration = active["lifecycle"].get("integration")
                if active["handoff_id"] != handoff_id and isinstance(integration, dict) and integration.get("status") == "integrating":
                    raise HandoffError(f"integration is already in progress: {active['handoff_id']}")
            lifecycle["integration"] = evidence
            if isinstance(orchestration, dict):
                orchestration["lifecycle"].update({"stage": "integrating", "integration_started_at": _utc_text()})
            metadata["handoff"] = handoff
            self._update_lifecycle(connection, row, metadata, "in_progress", _utc_text(), "integration-started")
            return self._load_task(connection, handoff_id)

    def integration_result(self, handoff_id: str, developer_id: str, commit_hash: str, result_text: str) -> dict[str, Any]:
        handoff_id = self._handoff_id(handoff_id)
        developer_id = self._developer_id(developer_id)
        commit_hash = self._git_hash(commit_hash, "commit_hash")
        result_text = _required_text({"result": result_text}, "result")
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            row = self._handoff_row(connection, handoff_id)
            metadata = self._object(row["data_json"])
            handoff = metadata.get("handoff")
            current = self._attested_result(connection, dict(row), metadata, handoff)
            orchestration = handoff.get("orchestration")
            integration = handoff["lifecycle"].get("integration")
            if not isinstance(orchestration, dict) or not isinstance(integration, dict):
                raise HandoffError("orchestrated integration lease is required")
            if integration.get("claimed_by") != developer_id or handoff["lifecycle"].get("claimed_by") != developer_id:
                raise HandoffError("integration is owned by another worker")
            exact = {**integration, "status": "integrated", "commit_hash": commit_hash, "result": result_text}
            if integration.get("status") == "integrated":
                if integration != exact:
                    raise HandoffError("integration already has different result evidence")
                return current
            if integration.get("status") != "integrating" or orchestration["lifecycle"].get("stage") != "integrating":
                raise HandoffError("integration result cannot be recorded at this stage")
            if orchestration.get("submission", {}).get("commit_hash") != commit_hash:
                raise HandoffError("integration commit must match the worker submission")
            handoff["lifecycle"]["integration"] = exact
            orchestration["lifecycle"].update({"stage": "integrated", "integrated_at": _utc_text()})
            metadata["handoff"] = handoff
            self._update_lifecycle(connection, row, metadata, "in_progress", _utc_text(), "integration-completed")
            return self._load_task(connection, handoff_id)

    def strategy_complete(self, handoff_id: str, strategy_id: str, parent_context_pack_id: str,
                          pack_status: str, clean_delivery: bool) -> dict[str, Any]:
        handoff_id = self._handoff_id(handoff_id)
        strategy_id = self._developer_id(strategy_id)
        parent_context_pack_id = _required_text({"parent_context_pack_id": parent_context_pack_id}, "parent_context_pack_id")
        if pack_status != "closed" or clean_delivery is not True:
            raise HandoffError("Strategy completion requires a closed parent context pack and clean delivery evidence")
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            row = self._handoff_row(connection, handoff_id)
            metadata = self._object(row["data_json"])
            handoff = metadata.get("handoff")
            current = self._attested_result(connection, dict(row), metadata, handoff)
            orchestration = handoff.get("orchestration")
            if not isinstance(orchestration, dict):
                raise HandoffError("handoff is not orchestrated")
            lifecycle = orchestration["lifecycle"]
            integration = handoff["lifecycle"].get("integration")
            completion = {"strategy_id": strategy_id, "parent_context_pack_id": parent_context_pack_id,
                          "pack_status": "closed", "clean_delivery": True}
            if current["status"] == "completed":
                if orchestration.get("strategy_completion") != completion:
                    raise HandoffError("completed orchestration has different Strategy evidence")
                return current
            if lifecycle.get("stage") != "integrated" or not isinstance(integration, dict) or integration.get("status") != "integrated":
                raise HandoffError("Strategy completion requires coordinator approval and completed integration")
            if orchestration.get("review", {}).get("decision") != "approve":
                raise HandoffError("Strategy completion requires valid coordinator approval")
            if orchestration["parent_context_pack_id"] != parent_context_pack_id:
                raise HandoffError("closed context pack evidence belongs to another pack")
            context_pack = connection.execute(
                "SELECT status FROM context_packs WHERE id=?", (parent_context_pack_id,),
            ).fetchone()
            if context_pack is None or context_pack["status"] != "closed":
                raise HandoffError("Strategy completion requires the original context pack to be closed in the control plane")
            orchestration["strategy_completion"] = completion
            lifecycle.update({"stage": "completed", "completed_at": _utc_text()})
            main = handoff["lifecycle"]
            main.update({"status": "completed", "completed_at": _utc_text(),
                         "commit_hash": integration["commit_hash"], "result": integration["result"]})
            metadata["handoff"] = handoff
            self._update_lifecycle(connection, row, metadata, "completed", _utc_text(), "strategy-completed", integration["commit_hash"])
            return self._load_task(connection, handoff_id)

    def _complete(self, handoff_id: str, commit_hash: str, result_text: str, developer_id: str, *, require_thread: bool) -> dict[str, Any]:
        handoff_id = self._handoff_id(handoff_id)
        developer_id = self._developer_id(developer_id)
        if not isinstance(commit_hash, str):
            raise HandoffError("commit_hash must be a 7-64 character hexadecimal Git commit hash")
        commit_hash = commit_hash.strip().lower()
        if not re.fullmatch(r"[0-9a-f]{7,64}", commit_hash):
            raise HandoffError("commit_hash must be a 7-64 character hexadecimal Git commit hash")
        result_text = _required_text({"result": result_text}, "result")
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            row = self._handoff_row(connection, handoff_id)
            metadata = self._object(row["data_json"])
            handoff = metadata.get("handoff")
            result = self._attested_result(connection, dict(row), metadata, handoff)
            if handoff.get("orchestration") is not None:
                raise HandoffError("orchestrated handoff requires Strategy completion")
            lifecycle = handoff["lifecycle"]
            if result["status"] == "completed":
                if lifecycle.get("commit_hash") != commit_hash:
                    raise HandoffError("completed handoff is already linked to a different commit hash")
                if lifecycle.get("claimed_by") != developer_id or lifecycle.get("result") != result_text:
                    raise HandoffError("completed handoff is already linked to a different result")
                return result
            if result["status"] != "in_progress":
                raise HandoffError("handoff must be claimed before completion")
            if lifecycle.get("claimed_by") != developer_id:
                raise HandoffError("handoff is claimed by another developer")
            if require_thread and not lifecycle.get("executor_thread_id"):
                raise HandoffError("dispatcher completion requires an executor thread")
            if result.get("execution_resources") is not None and lifecycle.get("integration", {}).get("status") != "integrating":
                raise HandoffError("declared parallel writer must acquire the integration lease before completion")
            now = _utc_text()
            lifecycle.update({"status": "completed", "completed_at": now, "commit_hash": commit_hash, "result": result_text})
            metadata["handoff"] = handoff
            self._update_lifecycle(connection, row, metadata, "completed", now, "completed", commit_hash)
            return self._load_task(connection, handoff_id)

    @staticmethod
    def _handoff_id(value: str) -> str:
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-a[0-9a-f]{3}-[0-9a-f]{12}", value):
            raise HandoffError("handoff_id must be a handoff UUID")
        return value

    @staticmethod
    def _developer_id(value: str) -> str:
        if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}", value):
            raise HandoffError("developer_id must be a 1-64 character identifier")
        return value

    @staticmethod
    def _thread_id(value: str) -> str:
        if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}", value):
            raise HandoffError("thread_id must be a 1-128 character identifier")
        return value

    @staticmethod
    def _git_hash(value: str, name: str) -> str:
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{7,64}", value.strip()):
            raise HandoffError(f"{name} must be a 7-64 character hexadecimal Git commit hash")
        return value.strip().lower()

    def _next_ready(self, connection: sqlite3.Connection) -> dict[str, Any] | None:
        ready = self._ready_results(connection)
        return ready[0] if ready else None

    def _ready_results(self, connection: sqlite3.Connection) -> list[dict[str, Any]]:
        rows = connection.execute(
            """SELECT id,title,content,data_json,status,source_id,created_at
               FROM tasks WHERE type='standalone_task' AND status='pending' ORDER BY created_at,id"""
        ).fetchall()
        parsed_rows = []
        for row in rows:
            metadata = self._object(row["data_json"])
            priority = metadata.get("priority", "normal")
            priority_rank = {"high": 0, "normal": 1, "low": 2}.get(priority, 2) if isinstance(priority, str) else 2
            parsed_rows.append((priority_rank, row, metadata))
        ready = []
        for _, row, metadata in sorted(parsed_rows, key=lambda item: (item[0], item[1]["created_at"], item[1]["id"])):
            handoff = metadata.get("handoff")
            if isinstance(handoff, dict) and handoff.get("kind") == "codex_engineering":
                try:
                    result = self._attested_result(connection, dict(row), metadata, handoff)
                    if result["status"] == "ready":
                        ready.append(result)
                except HandoffError:
                    continue
        return ready

    @staticmethod
    def _dispatch_payload(result: dict[str, Any]) -> dict[str, Any]:
        return {
            "idempotency_key": result["lifecycle"]["idempotency_key"],
            "task_id": result["task_id"],
            "goal": result["goal"], "scope": result["scope"],
            "constraints": result["constraints"], "acceptance": result["acceptance"],
            "execution_resources": result.get("execution_resources"),
        }

    def _handoff_row(self, connection: sqlite3.Connection, handoff_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT id,title,content,data_json,status,source_id,author,created_at,updated_at,version FROM tasks WHERE id=? AND type='standalone_task'",
            (handoff_id,),
        ).fetchone()
        if row is None:
            raise HandoffError("handoff was not found")
        return row

    def _active_results(self, connection: sqlite3.Connection) -> list[dict[str, Any]]:
        rows = connection.execute(
            "SELECT id,data_json,status,source_id,created_at FROM tasks WHERE type='standalone_task' AND status IN ('pending','in_progress') ORDER BY created_at,id",
        ).fetchall()
        active = []
        for row in rows:
            metadata = self._object(row["data_json"])
            handoff = metadata.get("handoff")
            if not isinstance(handoff, dict) or handoff.get("kind") != "codex_engineering":
                continue
            try:
                result = self._attested_result(connection, dict(row), metadata, handoff)
                if result["status"] in {"dispatching", "in_progress"}:
                    active.append(result)
            except HandoffError:
                continue
        return active

    def _active_handoff_id(self, connection: sqlite3.Connection) -> str | None:
        active = self._active_results(connection)
        return active[0]["handoff_id"] if active else None

    def _claim_blocker(self, connection: sqlite3.Connection, candidate: dict[str, Any]) -> str | None:
        active = [item for item in self._active_results(connection) if item["handoff_id"] != candidate["handoff_id"]]
        if not active:
            return None
        if len(active) >= 2:
            return "maximum active writer leases is two"
        resources = candidate.get("execution_resources")
        if resources is None:
            return "another developer handoff is already in progress: missing execution resource declaration blocks concurrent writer"
        if _exclusive_resources(resources):
            return "exclusive core or shared resource blocks concurrent writer"
        for other in active:
            existing = other.get("execution_resources")
            if existing is None:
                return f"legacy exclusive writer is already in progress: {other['handoff_id']}"
            if _exclusive_resources(existing):
                return f"exclusive core or shared resource is already leased: {other['handoff_id']}"
            if resources["worktree"].casefold() == existing["worktree"].casefold():
                return "writers must use distinct worktrees"
            if resources["branch"].casefold() == existing["branch"].casefold():
                return "writers must use distinct branches"
            if any(_paths_overlap(left, right) for left in resources["paths"] for right in existing["paths"]):
                return "path resource overlap blocks concurrent writer"
            if {item.casefold() for item in resources["sqlite"]}.intersection(item.casefold() for item in existing["sqlite"]):
                return "same SQLite resource blocks concurrent writer"
            if set(resources["shared"]).intersection(existing["shared"]):
                return "shared resource overlap blocks concurrent writer"
        return None

    def _update_lifecycle(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        metadata: dict[str, Any],
        status: str,
        now: str,
        action: str,
        commit_hash: str | None = None,
    ) -> None:
        new_version = int(row["version"]) + 1
        connection.execute(
            "UPDATE tasks SET data_json=?,status=?,updated_at=?,version=? WHERE id=?",
            (json.dumps(metadata, ensure_ascii=False, sort_keys=True), status, now, new_version, row["id"]),
        )
        data = {"old": {"status": row["status"], "version": row["version"]}, "new": {"status": status, "version": new_version}}
        if commit_hash:
            data["new"]["commit_hash"] = commit_hash
        connection.execute(
            "INSERT INTO audit_log (id,type,title,data_json,author,created_at,updated_at,access_level,version,entity_type,entity_id,action) VALUES (?, 'task_change', ?, ?, ?, ?, ?, 'restricted', 1, 'task', ?, 'update')",
            (_uuid(f"audit:{action}:{row['id']}:{new_version}"), f"Codex engineering handoff {action}", json.dumps(data, ensure_ascii=False, sort_keys=True), row["author"], now, now, row["id"]),
        )

    def _load_task(self, connection: sqlite3.Connection, task_id: str) -> dict[str, Any]:
        row = connection.execute(
            "SELECT id,title,content,data_json,status,source_id,created_at FROM tasks WHERE id=?", (task_id,),
        ).fetchone()
        if row is None:
            raise HandoffError("approved handoff is missing its engineering task")
        metadata = self._object(row["data_json"])
        handoff = metadata.get("handoff")
        if not isinstance(handoff, dict) or handoff.get("kind") != "codex_engineering":
            raise HandoffError("engineering task has invalid handoff metadata")
        return self._attested_result(connection, dict(row), metadata, handoff)

    def _attested_result(
        self,
        connection: sqlite3.Connection,
        row: dict[str, Any],
        metadata: dict[str, Any],
        handoff: dict[str, Any],
    ) -> dict[str, Any]:
        result = self._result(row, handoff)
        if row.get("source_id") != handoff["source_id"] or metadata.get("project_id") != handoff.get("project_id"):
            raise HandoffError("engineering task has inconsistent handoff linkage")
        candidate = connection.execute(
            "SELECT semantic_key,status,source_id,data_json FROM memory_candidates WHERE id=?",
            (handoff["decision_candidate_id"],),
        ).fetchone()
        if (
            candidate is None
            or candidate["status"] != "approved"
            or candidate["semantic_key"] != handoff["decision_semantic_key"]
            or candidate["source_id"] != handoff["source_id"]
            or self._object(candidate["data_json"]).get("handoff_task_id") != row["id"]
        ):
            raise HandoffError("engineering task is not linked to an approved decision")
        source = connection.execute(
            "SELECT status FROM sources WHERE id=?", (handoff["source_id"],),
        ).fetchone()
        if source is None or source["status"] != "active":
            raise HandoffError("engineering task is not linked to an active source")
        if result["project_id"]:
            project = connection.execute(
                "SELECT 1 FROM documents WHERE id=? AND type='project'", (result["project_id"],),
            ).fetchone()
            if project is None:
                raise HandoffError("engineering task has an invalid project linkage")
        return result

    @staticmethod
    def _object(value: object) -> dict[str, Any]:
        try:
            parsed = json.loads(str(value))
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _result(row: dict[str, Any], handoff: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(handoff, dict):
            raise HandoffError("engineering task has invalid handoff metadata")
        required_strings = ("goal", "source", "decision_candidate_id", "decision_semantic_key", "source_id")
        if any(not isinstance(handoff.get(key), str) or not handoff[key].strip() for key in required_strings):
            raise HandoffError("engineering task has invalid handoff metadata")
        for key in ("acceptance", "constraints", "scope"):
            value = handoff.get(key)
            if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item.strip() for item in value):
                raise HandoffError("engineering task has invalid handoff metadata")
        project_id = handoff.get("project_id")
        if project_id is not None and (not isinstance(project_id, str) or not project_id.strip()):
            raise HandoffError("engineering task has invalid handoff metadata")
        lifecycle = handoff.get("lifecycle")
        if not isinstance(lifecycle, dict) or lifecycle.get("status") not in {"ready", "dispatching", "in_progress", "completed"}:
            raise HandoffError("engineering task has invalid handoff lifecycle")
        status = lifecycle["status"]
        expected_task_status = {"ready": "pending", "dispatching": "pending", "in_progress": "in_progress", "completed": "completed"}[status]
        if row.get("status") != expected_task_status:
            raise HandoffError("engineering task lifecycle is inconsistent with task status")
        commit_hash = lifecycle.get("commit_hash")
        if status == "completed":
            if not isinstance(commit_hash, str) or not re.fullmatch(r"[0-9a-f]{7,64}", commit_hash):
                raise HandoffError("completed handoff has an invalid commit hash")
            if lifecycle.get("result") is not None and (not isinstance(lifecycle["result"], str) or not lifecycle["result"].strip()):
                raise HandoffError("completed handoff has an invalid result")
        elif commit_hash is not None:
            raise HandoffError("open handoff cannot have a commit hash")
        if status in {"dispatching", "in_progress", "completed"} and not isinstance(lifecycle.get("claimed_by"), str):
            raise HandoffError("claimed handoff has an invalid developer identifier")
        if status in {"in_progress", "completed"} and lifecycle.get("executor_thread_id") is not None and not isinstance(lifecycle["executor_thread_id"], str):
            raise HandoffError("engineering task has an invalid executor thread")
        resources = _execution_resources(handoff.get("execution_resources"))
        orchestration = _validated_orchestration(handoff.get("orchestration"))
        if orchestration is not None and isinstance(orchestration.get("delegation"), dict):
            _child_card(orchestration["delegation"].get("child_card"), handoff)
        integration = lifecycle.get("integration")
        if integration is not None:
            if resources is None or not isinstance(integration, dict) or integration.get("status") not in {"integrating", "integrated"}:
                raise HandoffError("engineering task has an invalid integration lease")
            if any(not isinstance(integration.get(key), str) for key in ("expected_base_head", "current_base_head", "claimed_by")):
                raise HandoffError("engineering task has an invalid integration lease")
            if integration.get("conflict_free") is not True:
                raise HandoffError("engineering task has an invalid integration lease")
            if integration.get("status") == "integrated" and (
                not isinstance(integration.get("commit_hash"), str)
                or not re.fullmatch(r"[0-9a-f]{7,64}", integration["commit_hash"])
                or not isinstance(integration.get("result"), str) or not integration["result"].strip()
            ):
                raise HandoffError("engineering task has invalid integration result evidence")
        return {
            "acceptance": list(handoff["acceptance"]),
            "constraints": list(handoff["constraints"]),
            "decision": {
                "candidate_id": handoff["decision_candidate_id"],
                "semantic_key": handoff["decision_semantic_key"],
                "source_id": handoff["source_id"],
                "source": handoff["source"],
            },
            "goal": handoff["goal"],
            "project_id": project_id,
            "execution_resources": resources,
            "orchestration": orchestration,
            "scope": list(handoff["scope"]),
            "handoff_id": row["id"],
            "lifecycle": {**lifecycle, "idempotency_key": handoff["idempotency_key"]},
            "status": status,
            "task_id": row["id"],
        }


def format_handoff(value: dict[str, Any] | None) -> str:
    if value is None:
        return "No active Codex handoff.\n"
    lines = ["# Codex engineering handoff", "", f"Goal: {value['goal']}", "", "Scope:"]
    lines.extend(f"- {item}" for item in value["scope"])
    lines.extend(["", "Constraints:"])
    lines.extend(f"- {item}" for item in value["constraints"])
    lines.extend(["", "Acceptance:"])
    lines.extend(f"- {item}" for item in value["acceptance"])
    decision = value["decision"]
    lines.extend(["", f"Decision: {decision['semantic_key']} ({decision['candidate_id']})", f"Source: {decision['source']} ({decision['source_id']})"])
    if value.get("project_id"):
        lines.append(f"Project: {value['project_id']}")
    lines.extend([f"Handoff: {value['handoff_id']}", f"Status: {value['status']}"])
    if value["status"] == "completed":
        lines.append(f"Commit: {value['lifecycle']['commit_hash']}")
    return "\n".join(lines) + "\n"

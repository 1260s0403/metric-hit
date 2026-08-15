from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .database import read_only_database


class HandoffError(ValueError):
    pass


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
        "source", "project_id", "approved_by", "supersedes_candidate_id",
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
        }
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
                "source_id": source_id, **delta,
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
            rows = connection.execute(
                """SELECT id,title,content,data_json,status,source_id,created_at
                   FROM tasks
                   WHERE type='standalone_task' AND status IN ('pending','in_progress')
                   ORDER BY created_at,id"""
            ).fetchall()
            parsed_rows = []
            for row in rows:
                metadata = self._object(row["data_json"])
                priority = metadata.get("priority", "normal")
                priority_rank = {"high": 0, "normal": 1, "low": 2}.get(priority, 2) if isinstance(priority, str) else 2
                parsed_rows.append((priority_rank, row, metadata))
            parsed_rows.sort(key=lambda item: (item[0], item[1]["created_at"], item[1]["id"]))
            for _, row, metadata in parsed_rows:
                handoff = metadata.get("handoff")
                if isinstance(handoff, dict) and handoff.get("kind") == "codex_engineering":
                    try:
                        return self._attested_result(connection, dict(row), metadata, handoff)
                    except HandoffError:
                        continue
        return None

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
            "scope": list(handoff["scope"]),
            "status": "open" if row["status"] in {"pending", "in_progress"} else row["status"],
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
    lines.append(f"Task: {value['task_id']}")
    return "\n".join(lines) + "\n"

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from .config import EDITORIAL_DATABASE, EDITORIAL_MIGRATIONS, MEMORY_DATABASE, repository_path


PENDING_EDITORIAL_MIGRATIONS = repository_path("data", "editorial", "pending-migrations")
_WORKING_EDITORIAL_MVP_CAPABILITY = object()


class WorkflowError(RuntimeError):
    """Base error for rejected workflow operations."""


class InvalidTransitionError(WorkflowError):
    pass


class IdempotencyConflictError(WorkflowError):
    pass


class WorkingDatabaseWriteError(WorkflowError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_text(value: datetime | None = None) -> str:
    moment = (value or utc_now()).astimezone(timezone.utc)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def payload_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def assert_writable_target(path: Path, *, capability: object | None = None) -> Path:
    resolved = path.resolve()
    editorial = EDITORIAL_DATABASE.resolve()
    protected_databases = [editorial, MEMORY_DATABASE.resolve()]
    protected = [
        candidate
        for database in protected_databases
        for candidate in (
            database,
            *(database.with_name(database.name + suffix) for suffix in ("-wal", "-shm", "-journal")),
        )
    ]
    for candidate in protected:
        same_file = resolved.exists() and candidate.exists() and resolved.samefile(candidate)
        if resolved == candidate or same_file:
            if capability is _WORKING_EDITORIAL_MVP_CAPABILITY and resolved == editorial and candidate == editorial:
                continue
            raise WorkingDatabaseWriteError("Working SQLite databases and sidecars are read-only in this stage")
    if not resolved.parent.is_dir():
        raise WorkingDatabaseWriteError("Database parent directory must already exist")
    return resolved


def migration_files() -> list[Path]:
    files = list(EDITORIAL_MIGRATIONS.glob("*.sql")) + list(PENDING_EDITORIAL_MIGRATIONS.glob("*.sql"))
    return sorted(files, key=lambda path: (int(path.stem.split("_", 1)[0]), path.name))


def migration_manifest() -> list[tuple[int, str, str]]:
    return [
        (
            int(path.stem.split("_", 1)[0]),
            path.name,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in migration_files()
    ]


def schema_signature(connection: sqlite3.Connection) -> str:
    objects = [tuple(row) for row in connection.execute(
        """
        SELECT type, name, tbl_name, sql
        FROM sqlite_master
        WHERE name NOT LIKE 'sqlite_%'
        ORDER BY type, name
        """
    )]
    return payload_sha256(objects)


@lru_cache(maxsize=1)
def expected_schema_signature() -> str:
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        for migration in migration_files():
            connection.executescript(migration.read_text(encoding="utf-8"))
        return schema_signature(connection)
    finally:
        connection.close()


def initialize_workflow_database(
    path: Path,
    *,
    capability: object | None = None,
) -> dict[str, object]:
    database_path = assert_writable_target(path, capability=capability)
    connection = sqlite3.connect(assert_writable_target(
        database_path,
        capability=capability,
    ))
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        has_registry = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone()
        applied = {}
        if has_registry:
            applied = {
                row["version"]: row["checksum"]
                for row in connection.execute("SELECT version, checksum FROM schema_migrations")
            }
        applied_now: list[int] = []
        for migration in migration_files():
            version = int(migration.stem.split("_", 1)[0])
            sql = migration.read_text(encoding="utf-8")
            checksum = hashlib.sha256(migration.read_bytes()).hexdigest()
            if version in applied:
                if applied[version] != checksum:
                    raise WorkflowError(f"Migration {migration.name} changed after application")
                continue
            name = migration.name.replace("'", "''")
            script = "\n".join([
                "BEGIN IMMEDIATE;",
                sql,
                "INSERT INTO schema_migrations (version, name, checksum) "
                f"VALUES ({version}, '{name}', '{checksum}');",
                "COMMIT;",
            ])
            try:
                connection.executescript(script)
            except Exception:
                if connection.in_transaction:
                    connection.rollback()
                raise
            applied_now.append(version)
        versions = [row[0] for row in connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        )]
        return {"migration_versions": versions, "applied_now": applied_now}
    finally:
        connection.close()


class EditorialStore:
    def __init__(
        self,
        path: Path,
        clock: Callable[[], datetime] = utc_now,
        *,
        capability: object | None = None,
    ):
        self._capability = capability
        self.path = assert_writable_target(
            path,
            capability=capability,
        )
        self.clock = clock
        self._assert_workflow_schema()

    def _assert_workflow_schema(self) -> None:
        with self.read_connection() as connection:
            applied = [tuple(row) for row in connection.execute(
                "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
            )]
            if applied != migration_manifest():
                raise WorkflowError("Workflow database migration attestation failed")
            if schema_signature(connection) != expected_schema_signature():
                raise WorkflowError("Workflow database schema attestation failed")
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise WorkflowError("Workflow database integrity check failed")
            if connection.execute("PRAGMA foreign_key_check").fetchone():
                raise WorkflowError("Workflow database foreign-key check failed")

    def _connect(self, *, read_only: bool) -> sqlite3.Connection:
        if read_only:
            uri = f"file:{quote(self.path.as_posix(), safe='/:')}?mode=ro"
            connection = sqlite3.connect(uri, uri=True)
            connection.execute("PRAGMA query_only = ON")
        else:
            writable_path = assert_writable_target(
                self.path,
                capability=self._capability,
            )
            connection = sqlite3.connect(writable_path, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def read_connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect(read_only=True)
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect(read_only=False)
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def idempotent_write(
        self,
        scope: str,
        key: str,
        payload: dict[str, object],
        operation: Callable[[sqlite3.Connection, str], dict[str, object]],
    ) -> dict[str, object]:
        request_hash = payload_sha256({"scope": scope, "payload": payload})
        with self.transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM idempotency_keys WHERE scope = ? AND key_value = ?",
                (scope, key),
            ).fetchone()
            if existing:
                if existing["request_sha256"] != request_hash:
                    raise IdempotencyConflictError("Idempotency key was already used with different data")
                if existing["status"] != "consumed" or not existing["response_json"]:
                    raise WorkflowError("Previous idempotent operation has no committed result")
                response = json.loads(existing["response_json"])
                response["idempotent_replay"] = True
                return response

            key_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO idempotency_keys (id, scope, key_value, status, request_sha256)
                VALUES (?, ?, ?, 'active', ?)
                """,
                (key_id, scope, key, request_hash),
            )
            response = operation(connection, key_id)
            stored_response = {**response, "idempotent_replay": False}
            connection.execute(
                """
                UPDATE idempotency_keys
                SET status='consumed', result_entity_type=?, result_entity_id=?, response_json=?
                WHERE id=?
                """,
                (
                    response.get("entity_type"), response.get("id"),
                    canonical_json(stored_response), key_id,
                ),
            )
            return stored_response

    def idempotent_result(
        self,
        scope: str,
        key: str,
        payload: dict[str, object],
    ) -> dict[str, object] | None:
        request_hash = payload_sha256({"scope": scope, "payload": payload})
        with self.read_connection() as connection:
            existing = connection.execute(
                "SELECT * FROM idempotency_keys WHERE scope=? AND key_value=?",
                (scope, key),
            ).fetchone()
        if not existing:
            return None
        if existing["request_sha256"] != request_hash:
            raise IdempotencyConflictError("Idempotency key was already used with different data")
        if existing["status"] != "consumed" or not existing["response_json"]:
            raise WorkflowError("Previous idempotent operation has no committed result")
        response = json.loads(existing["response_json"])
        response["idempotent_replay"] = True
        return response

    def reserve_idempotency(
        self,
        scope: str,
        key: str,
        payload: dict[str, object],
    ) -> dict[str, object] | None:
        request_hash = payload_sha256({"scope": scope, "payload": payload})
        with self.transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM idempotency_keys WHERE scope=? AND key_value=?",
                (scope, key),
            ).fetchone()
            if existing:
                if existing["request_sha256"] != request_hash:
                    raise IdempotencyConflictError("Idempotency key was already used with different data")
                if existing["status"] == "consumed" and existing["response_json"]:
                    response = json.loads(existing["response_json"])
                    response["idempotent_replay"] = True
                    return response
                raise WorkflowError("Equivalent idempotent operation is already in progress")
            connection.execute(
                """
                INSERT INTO idempotency_keys (id, scope, key_value, status, request_sha256)
                VALUES (?, ?, ?, 'active', ?)
                """,
                (str(uuid4()), scope, key, request_hash),
            )
        return None

    def complete_reserved_idempotency(
        self,
        scope: str,
        key: str,
        payload: dict[str, object],
        response: dict[str, object],
        operation: Callable[[sqlite3.Connection], None],
    ) -> dict[str, object]:
        request_hash = payload_sha256({"scope": scope, "payload": payload})
        with self.transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM idempotency_keys WHERE scope=? AND key_value=?",
                (scope, key),
            ).fetchone()
            if not existing or existing["request_sha256"] != request_hash or existing["status"] != "active":
                raise WorkflowError("Reserved idempotent operation is missing or changed")
            operation(connection)
            stored_response = {**response, "idempotent_replay": False}
            connection.execute(
                """
                UPDATE idempotency_keys
                SET status='consumed', result_entity_type=?, result_entity_id=?, response_json=?
                WHERE id=?
                """,
                (
                    response.get("entity_type"), response.get("id"),
                    canonical_json(stored_response), existing["id"],
                ),
            )
            return stored_response

    def abandon_reserved_idempotency(
        self,
        scope: str,
        key: str,
        payload: dict[str, object],
    ) -> None:
        request_hash = payload_sha256({"scope": scope, "payload": payload})
        with self.transaction() as connection:
            connection.execute(
                """
                DELETE FROM idempotency_keys
                WHERE scope=? AND key_value=? AND status='active' AND request_sha256=?
                """,
                (scope, key, request_hash),
            )

    def audit(
        self,
        connection: sqlite3.Connection,
        *,
        run_id: str | None,
        actor_type: str,
        actor_id: str,
        event_type: str,
        entity_type: str,
        entity_id: str,
        data: dict[str, object],
    ) -> str:
        event_id = str(uuid4())
        created_at = utc_text(self.clock())
        previous = connection.execute(
            "SELECT event_hash FROM audit_events ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        previous_hash = previous["event_hash"] if previous else None
        event_data = {
            "id": event_id,
            "run_id": run_id,
            "actor_type": actor_type,
            "actor_id": actor_id,
            "event_type": event_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "data": data,
            "created_at": created_at,
            "prev_hash": previous_hash,
        }
        event_hash = payload_sha256(event_data)
        connection.execute(
            """
            INSERT INTO audit_events
              (id, run_id, actor_type, actor_id, event_type, entity_type, entity_id,
               data_json, created_at, prev_hash, event_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id, run_id, actor_type, actor_id, event_type, entity_type,
                entity_id, canonical_json(data), created_at, previous_hash, event_hash,
            ),
        )
        return event_id


def row_dict(row: sqlite3.Row | None, message: str = "Record does not exist") -> dict[str, object]:
    if row is None:
        raise WorkflowError(message)
    return dict(row)

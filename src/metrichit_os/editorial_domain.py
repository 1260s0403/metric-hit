from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4

from .config import PROJECT_EDITORIAL_MIGRATIONS
from .database import read_only_database
from .project_scope import DEFAULT_PROJECT_ID
from .project_storage import canonical_project_id


EDITORIAL_TABLES = {
    "editorial_schema_migrations",
    "editorial_memory",
    "editorial_topics",
    "editorial_materials",
    "editorial_publications",
    "editorial_results",
}


class EditorialDomainError(ValueError):
    """Raised when editorial data cannot be routed or changed safely."""


def _migration_files(path: Path) -> list[Path]:
    files = sorted(path.glob("*.sql"))
    if not files:
        raise EditorialDomainError("editorial project migrations are missing")
    versions = [int(item.stem.split("_", 1)[0]) for item in files]
    if versions != list(range(1, len(files) + 1)):
        raise EditorialDomainError("editorial project migration sequence is invalid")
    return files


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _identity(connection: sqlite3.Connection, expected_project_id: str) -> None:
    expected = canonical_project_id(expected_project_id)
    row = connection.execute(
        "SELECT project_id,storage_format FROM project_storage_metadata WHERE singleton=1"
    ).fetchone()
    count = connection.execute("SELECT count(*) FROM project_storage_metadata").fetchone()[0]
    if count != 1 or row is None or row[0] != expected or row[1] != 1:
        raise EditorialDomainError("editorial storage does not belong to the requested managed project")
    required = {"memory_candidates", "project_storage_metadata"}
    tables = {
        str(item[0])
        for item in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    if not required <= tables:
        raise EditorialDomainError("managed project storage schema is incomplete")


def initialize_editorial_domain(
    database_path: Path,
    *,
    project_id: str = DEFAULT_PROJECT_ID,
    migrations_path: Path = PROJECT_EDITORIAL_MIGRATIONS,
) -> dict[str, object]:
    """Idempotently add the editorial domain to one validated project SQLite."""
    path = database_path.resolve()
    if not path.is_file():
        raise EditorialDomainError("managed project database does not exist")
    migrations = _migration_files(migrations_path.resolve())
    applied_now: list[int] = []
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        _identity(connection, project_id)
        has_migrations = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='editorial_schema_migrations'"
        ).fetchone()
        applied = (
            {
                int(row[0]): (str(row[1]), str(row[2]))
                for row in connection.execute(
                    "SELECT version,name,checksum FROM editorial_schema_migrations"
                )
            }
            if has_migrations
            else {}
        )
        expected_versions = {int(item.stem.split("_", 1)[0]) for item in migrations}
        if set(applied) - expected_versions:
            raise EditorialDomainError("editorial project database has unknown migrations")
        for migration in migrations:
            version = int(migration.stem.split("_", 1)[0])
            expected = (migration.name, _checksum(migration))
            if version in applied:
                if applied[version] != expected:
                    raise EditorialDomainError("applied editorial migration was modified")
                continue
            script = migration.read_text(encoding="utf-8")
            try:
                connection.executescript(
                    "BEGIN IMMEDIATE;\n"
                    + script
                    + "\nINSERT INTO editorial_schema_migrations(version,name,checksum) VALUES "
                    + f"({version},{_sql_literal(migration.name)},{_sql_literal(expected[1])});\nCOMMIT;"
                )
            except sqlite3.Error:
                if connection.in_transaction:
                    connection.rollback()
                raise
            applied_now.append(version)
    checked = check_editorial_domain(path, project_id=project_id, migrations_path=migrations_path)
    return {**checked, "applied_now": applied_now}


def check_editorial_domain(
    database_path: Path,
    *,
    project_id: str = DEFAULT_PROJECT_ID,
    migrations_path: Path = PROJECT_EDITORIAL_MIGRATIONS,
) -> dict[str, object]:
    migrations = _migration_files(migrations_path.resolve())
    with read_only_database(database_path.resolve()) as connection:
        _identity(connection, project_id)
        if [tuple(row) for row in connection.execute("PRAGMA integrity_check")] != [("ok",)]:
            raise EditorialDomainError("editorial project database failed integrity check")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise EditorialDomainError("editorial project database failed foreign-key check")
        tables = {
            str(row["name"])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if not EDITORIAL_TABLES <= tables:
            raise EditorialDomainError("editorial project schema is incomplete")
        applied = [
            tuple(row)
            for row in connection.execute(
                "SELECT version,name,checksum FROM editorial_schema_migrations ORDER BY version"
            )
        ]
        expected = [
            (int(item.stem.split("_", 1)[0]), item.name, _checksum(item))
            for item in migrations
        ]
        if applied != expected:
            raise EditorialDomainError("editorial project migrations do not match canonical files")
        counts = {
            name.removeprefix("editorial_"): connection.execute(
                f'SELECT count(*) FROM "{name}"'
                + (" WHERE status='active'" if name == "editorial_memory" else "")
            ).fetchone()[0]
            for name in sorted(EDITORIAL_TABLES - {"editorial_schema_migrations"})
        }
    return {
        "project_id": canonical_project_id(project_id),
        "integrity": "ok",
        "foreign_keys": "ok",
        "migration_versions": [item[0] for item in expected],
        "counts": counts,
    }


def _text(value: object, field: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip():
        raise EditorialDomainError(f"{field} must not be empty")
    return value.strip()


def _direction(value: object, *, allow_common: bool = False) -> str:
    direction = _text(value, "direction")
    allowed = {"articles", "social"} | ({"common"} if allow_common else set())
    if direction not in allowed:
        raise EditorialDomainError(
            "direction must be " + ", ".join(sorted(allowed))
        )
    return direction


class EditorialStore:
    """Small project-local editorial registry with bounded context retrieval."""

    def __init__(self, database_path: Path, *, project_id: str = DEFAULT_PROJECT_ID):
        self.path = database_path.resolve()
        self.project_id = canonical_project_id(project_id)
        check_editorial_domain(self.path, project_id=self.project_id)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        return dict(row)

    @staticmethod
    def _replay(
        connection: sqlite3.Connection, table: str, key: str, expected: dict[str, object]
    ) -> dict[str, Any] | None:
        row = connection.execute(
            f'SELECT * FROM "{table}" WHERE idempotency_key=?', (key,)
        ).fetchone()
        if row is None:
            return None
        actual = dict(row)
        if any(actual.get(field) != value for field, value in expected.items()):
            raise EditorialDomainError("idempotency key was already used with different data")
        actual["idempotent_replay"] = True
        return actual

    def remember(
        self, *, semantic_key: str, category: str, title: str, content: str,
        direction: str = "common", source_type: str = "owner",
        source_ref: str | None = None,
    ) -> dict[str, Any]:
        values = (
            _text(semantic_key, "semantic_key"), _text(category, "category"),
            _text(title, "title"), _text(content, "content"),
            _text(source_type, "source_type"), _text(source_ref, "source_ref", optional=True),
            _direction(direction, allow_common=True),
        )
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM editorial_memory WHERE semantic_key=?", (values[0],)
            ).fetchone()
            if row is None:
                identity = str(uuid4())
                connection.execute(
                    "INSERT INTO editorial_memory(id,semantic_key,category,title,content,source_type,source_ref,direction) "
                    "VALUES(?,?,?,?,?,?,?,?)", (identity, *values),
                )
            else:
                identity = str(row["id"])
                connection.execute(
                    "UPDATE editorial_memory SET category=?,title=?,content=?,source_type=?,source_ref=?,direction=?,status='active' WHERE id=?",
                    (*values[1:], identity),
                )
            return self._row(connection.execute(
                "SELECT * FROM editorial_memory WHERE id=?", (identity,)
            ).fetchone())

    def create_topic(
        self, *, idempotency_key: str, title: str, primary_intent: str,
        primary_query: str | None = None, cluster_name: str | None = None,
        priority: int = 50, notes: str | None = None, direction: str = "articles",
    ) -> dict[str, Any]:
        key = _text(idempotency_key, "idempotency_key")
        if not isinstance(priority, int) or not 0 <= priority <= 100:
            raise EditorialDomainError("priority must be between 0 and 100")
        expected = {
            "title": _text(title, "title"),
            "primary_intent": _text(primary_intent, "primary_intent"),
            "primary_query": _text(primary_query, "primary_query", optional=True),
            "cluster_name": _text(cluster_name, "cluster_name", optional=True),
            "priority": priority,
            "notes": _text(notes, "notes", optional=True),
            "direction": _direction(direction),
        }
        with self._connect() as connection:
            replay = self._replay(connection, "editorial_topics", key, expected)
            if replay is not None:
                return replay
            identity = str(uuid4())
            connection.execute(
                "INSERT INTO editorial_topics(id,idempotency_key,title,primary_intent,primary_query,cluster_name,priority,notes,direction) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (identity, key, *expected.values()),
            )
            return self._row(connection.execute(
                "SELECT * FROM editorial_topics WHERE id=?", (identity,)
            ).fetchone())

    def create_material(
        self, *, idempotency_key: str, topic_id: str, material_type: str,
        title: str, parent_material_id: str | None = None, content_ref: str | None = None,
        direction: str | None = None,
    ) -> dict[str, Any]:
        key = _text(idempotency_key, "idempotency_key")
        normalized_type = _text(material_type, "material_type")
        inferred_direction = "social" if normalized_type in {"telegram_post", "vk_post"} else "articles"
        normalized_direction = _direction(direction or inferred_direction)
        expected = {
            "topic_id": _text(topic_id, "topic_id"),
            "parent_material_id": _text(parent_material_id, "parent_material_id", optional=True),
            "material_type": normalized_type,
            "title": _text(title, "title"),
            "content_ref": _text(content_ref, "content_ref", optional=True),
            "direction": normalized_direction,
        }
        with self._connect() as connection:
            replay = self._replay(connection, "editorial_materials", key, expected)
            if replay is not None:
                return replay
            identity = str(uuid4())
            connection.execute(
                "INSERT INTO editorial_materials(id,idempotency_key,topic_id,parent_material_id,material_type,title,content_ref,direction) "
                "VALUES(?,?,?,?,?,?,?,?)", (identity, key, *expected.values()),
            )
            return self._row(connection.execute(
                "SELECT * FROM editorial_materials WHERE id=?", (identity,)
            ).fetchone())

    def record_publication(
        self, *, idempotency_key: str, material_id: str, platform: str,
        published_at: str, url: str | None = None, owner_confirmed_by: str | None = None,
        account_ref: str | None = None, external_id: str | None = None,
    ) -> dict[str, Any]:
        key = _text(idempotency_key, "idempotency_key")
        confirmation_kind = "verified_url" if url else "owner"
        confirmation_ref = url or _text(owner_confirmed_by, "owner_confirmed_by")
        expected = {
            "material_id": _text(material_id, "material_id"),
            "platform": _text(platform, "platform"),
            "account_ref": _text(account_ref, "account_ref", optional=True),
            "url": _text(url, "url", optional=True),
            "external_id": _text(external_id, "external_id", optional=True),
            "published_at": _text(published_at, "published_at"),
            "confirmation_kind": confirmation_kind,
            "confirmation_ref": confirmation_ref,
        }
        with self._connect() as connection:
            replay = self._replay(connection, "editorial_publications", key, expected)
            if replay is not None:
                return replay
            identity = str(uuid4())
            connection.execute(
                "INSERT INTO editorial_publications(id,idempotency_key,material_id,platform,account_ref,status,url,external_id,published_at,confirmation_kind,confirmation_ref,confirmed_at) "
                "VALUES(?,?,?,?,?,'published',?,?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
                (identity, key, *expected.values()),
            )
            connection.execute(
                "UPDATE editorial_materials SET status='published' WHERE id=?", (expected["material_id"],)
            )
            return self._row(connection.execute(
                "SELECT * FROM editorial_publications WHERE id=?", (identity,)
            ).fetchone())

    def record_result(
        self, *, idempotency_key: str, publication_id: str, metric_name: str,
        metric_value: float, unit: str, observed_at: str, source: str,
        period_start: str | None = None, period_end: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        key = _text(idempotency_key, "idempotency_key")
        if isinstance(metric_value, bool) or not isinstance(metric_value, (int, float)):
            raise EditorialDomainError("metric_value must be numeric")
        expected = {
            "publication_id": _text(publication_id, "publication_id"),
            "metric_name": _text(metric_name, "metric_name"),
            "metric_value": float(metric_value),
            "unit": _text(unit, "unit"),
            "period_start": _text(period_start, "period_start", optional=True),
            "period_end": _text(period_end, "period_end", optional=True),
            "observed_at": _text(observed_at, "observed_at"),
            "source": _text(source, "source"),
            "notes": _text(notes, "notes", optional=True),
        }
        with self._connect() as connection:
            replay = self._replay(connection, "editorial_results", key, expected)
            if replay is not None:
                return replay
            identity = str(uuid4())
            connection.execute(
                "INSERT INTO editorial_results(id,idempotency_key,publication_id,metric_name,metric_value,unit,period_start,period_end,observed_at,source,notes) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)", (identity, key, *expected.values()),
            )
            return self._row(connection.execute(
                "SELECT * FROM editorial_results WHERE id=?", (identity,)
            ).fetchone())

    def context(
        self, *, direction: str, query: str = "", topic_id: str | None = None,
        material_id: str | None = None, limit: int = 8,
    ) -> dict[str, object]:
        if not isinstance(limit, int) or not 1 <= limit <= 25:
            raise EditorialDomainError("limit must be between 1 and 25")
        search = " ".join(query.split())[:200]
        selected_direction = _direction(direction)
        pattern = f"%{search}%"
        with read_only_database(self.path) as connection:
            where = "(?='' OR title LIKE ? COLLATE NOCASE OR primary_intent LIKE ? COLLATE NOCASE OR coalesce(primary_query,'') LIKE ? COLLATE NOCASE OR coalesce(cluster_name,'') LIKE ? COLLATE NOCASE)"
            topics = [dict(row) for row in connection.execute(
                "SELECT * FROM editorial_topics WHERE (id=? OR ((direction=? OR EXISTS ("
                "SELECT 1 FROM editorial_materials linked WHERE linked.topic_id=editorial_topics.id AND linked.direction=?"
                ")) AND " + where + ")) "
                "AND status<>'archived' ORDER BY (id=?) DESC,priority DESC,updated_at DESC LIMIT ?",
                (topic_id or "", selected_direction, selected_direction, search, pattern, pattern, pattern, pattern, topic_id or "", limit),
            )]
            topic_ids = [str(row["id"]) for row in topics]
            clauses = ["m.id=?"]
            arguments: list[object] = [material_id or ""]
            if topic_ids:
                clauses.append("m.topic_id IN (" + ",".join("?" for _ in topic_ids) + ")")
                arguments.extend(topic_ids)
            if search:
                clauses.append("(m.title LIKE ? COLLATE NOCASE OR coalesce(m.content_ref,'') LIKE ? COLLATE NOCASE)")
                arguments.extend((pattern, pattern))
            materials = [dict(row) for row in connection.execute(
                "SELECT m.* FROM editorial_materials m WHERE (" + " OR ".join(clauses) + ") "
                "AND m.direction=? AND m.status<>'archived' ORDER BY (m.id=?) DESC,m.updated_at DESC LIMIT ?",
                (*arguments, selected_direction, material_id or "", limit),
            )]
            if selected_direction == "social" and materials:
                parent_ids = [str(row["parent_material_id"]) for row in materials if row["parent_material_id"]]
                if parent_ids:
                    parent_placeholders = ",".join("?" for _ in parent_ids)
                    remaining = max(0, limit - len(materials))
                    if remaining:
                        materials.extend(dict(row) for row in connection.execute(
                            f"SELECT * FROM editorial_materials WHERE id IN ({parent_placeholders}) "
                            "AND direction='articles' AND status<>'archived' ORDER BY updated_at DESC LIMIT ?",
                            (*parent_ids, remaining),
                        ))
            material_ids = [str(row["id"]) for row in materials]
            publications: list[dict[str, Any]] = []
            results: list[dict[str, Any]] = []
            if material_ids:
                placeholders = ",".join("?" for _ in material_ids)
                publications = [dict(row) for row in connection.execute(
                    f"SELECT * FROM editorial_publications WHERE material_id IN ({placeholders}) "
                    "ORDER BY coalesce(published_at,created_at) DESC LIMIT ?",
                    (*material_ids, limit),
                )]
                publication_ids = [str(row["id"]) for row in publications]
                if publication_ids:
                    result_placeholders = ",".join("?" for _ in publication_ids)
                    results = [dict(row) for row in connection.execute(
                        f"SELECT * FROM editorial_results WHERE publication_id IN ({result_placeholders}) "
                        "ORDER BY observed_at DESC LIMIT ?", (*publication_ids, limit),
                    )]
            memory = [dict(row) for row in connection.execute(
                "SELECT * FROM editorial_memory WHERE status='active' AND direction IN ('common',?) AND "
                "(?='' OR category='rule' OR title LIKE ? COLLATE NOCASE OR content LIKE ? COLLATE NOCASE OR semantic_key LIKE ? COLLATE NOCASE) "
                "ORDER BY (category='rule') DESC,updated_at DESC,semantic_key LIMIT ?",
                (selected_direction, search, pattern, pattern, pattern, limit),
            )]
            totals = {
                "memory": connection.execute(
                    "SELECT count(*) FROM editorial_memory WHERE status='active' AND direction IN ('common',?)",
                    (selected_direction,),
                ).fetchone()[0],
                "topics": connection.execute(
                    "SELECT count(*) FROM editorial_topics WHERE status<>'archived' AND (direction=? OR EXISTS ("
                    "SELECT 1 FROM editorial_materials linked WHERE linked.topic_id=editorial_topics.id AND linked.direction=?))",
                    (selected_direction, selected_direction),
                ).fetchone()[0],
                "materials": connection.execute(
                    "SELECT count(*) FROM editorial_materials WHERE direction=?", (selected_direction,)
                ).fetchone()[0],
                "publications": connection.execute(
                    "SELECT count(*) FROM editorial_publications p JOIN editorial_materials m ON m.id=p.material_id WHERE m.direction=?",
                    (selected_direction,),
                ).fetchone()[0],
                "results": connection.execute(
                    "SELECT count(*) FROM editorial_results r JOIN editorial_publications p ON p.id=r.publication_id "
                    "JOIN editorial_materials m ON m.id=p.material_id WHERE m.direction=?",
                    (selected_direction,),
                ).fetchone()[0],
            }
        return {
            "scope": "editorial",
            "direction": selected_direction,
            "project_id": self.project_id,
            "query": search,
            "limit_per_section": limit,
            "totals": totals,
            "memory": memory,
            "topics": topics,
            "materials": materials,
            "publications": publications,
            "results": results,
        }

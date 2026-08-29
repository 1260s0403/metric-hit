from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from .config import PROJECT_STORAGE_ROOT
from .database import read_only_database


STORAGE_FORMAT_VERSION = 1
DATABASE_FILENAME = "project.sqlite"
PACKAGE_FORMAT_VERSION = 1
PACKAGE_MANIFEST_FILENAME = "manifest.json"
PACKAGE_METADATA_FILENAME = "project.json"
PACKAGE_COMPONENTS = {DATABASE_FILENAME, PACKAGE_METADATA_FILENAME}
MAX_DATABASE_BYTES = 1024 * 1024 * 1024
MAX_METADATA_BYTES = 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024


class ProjectStorageError(ValueError):
    """Base error for an invalid or conflicting project storage."""


class InvalidProjectIdError(ProjectStorageError):
    """Raised when a project ID cannot safely identify one storage."""


class ProjectStorageConflictError(ProjectStorageError):
    """Raised when an existing path does not belong to the requested project."""


class ProjectPackageError(ProjectStorageError):
    """Raised when a project transfer package fails validation."""


@dataclass(frozen=True)
class ProjectStorageLocation:
    project_id: str
    directory: Path
    database: Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o600 << 16
    return info


def _schema_hash(connection: sqlite3.Connection) -> str:
    rows = connection.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master "
        "WHERE sql IS NOT NULL ORDER BY type,name,tbl_name,sql"
    ).fetchall()
    payload = [[row["type"], row["name"], row["tbl_name"], row["sql"]] for row in rows]
    return hashlib.sha256(_json_bytes(payload)).hexdigest()


def _database_metadata(database: Path, expected_project_id: str) -> dict[str, Any]:
    try:
        with read_only_database(database) as connection:
            if [tuple(row) for row in connection.execute("PRAGMA integrity_check")] != [("ok",)]:
                raise ProjectPackageError("project database failed integrity check")
            if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise ProjectPackageError("project database failed foreign key check")
            identity = connection.execute(
                "SELECT singleton,project_id,storage_format FROM project_storage_metadata"
            ).fetchall()
            if len(identity) != 1 or tuple(identity[0]) != (
                1,
                expected_project_id,
                STORAGE_FORMAT_VERSION,
            ):
                raise ProjectPackageError("project database identity does not match the package")
            has_migrations = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
            ).fetchone()
            schema_version = (
                connection.execute("SELECT coalesce(max(version),0) FROM schema_migrations").fetchone()[0]
                if has_migrations
                else 0
            )
            has_editorial_migrations = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='editorial_schema_migrations'"
            ).fetchone()
            editorial_schema_version = (
                connection.execute(
                    "SELECT coalesce(max(version),0) FROM editorial_schema_migrations"
                ).fetchone()[0]
                if has_editorial_migrations
                else 0
            )
            has_documents = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='documents'"
            ).fetchone()
            project = None
            if has_documents:
                row = connection.execute(
                    "SELECT id,type,title,content,data_json,status,author,created_at,updated_at,"
                    "access_level,version FROM documents WHERE id=? AND type='project'",
                    (expected_project_id,),
                ).fetchone()
                if row is not None:
                    project = dict(row)
            return {
                "projectId": expected_project_id,
                "storageFormatVersion": STORAGE_FORMAT_VERSION,
                "schemaVersion": int(schema_version),
                "editorialSchemaVersion": int(editorial_schema_version),
                "schemaSha256": _schema_hash(connection),
                "project": project,
            }
    except ProjectPackageError:
        raise
    except (sqlite3.Error, FileNotFoundError, OSError) as error:
        raise ProjectPackageError("project database is not a valid transferable SQLite file") from error


def canonical_project_id(project_id: str) -> str:
    if not isinstance(project_id, str) or not project_id:
        raise InvalidProjectIdError("project ID must be a canonical UUID")
    try:
        parsed = UUID(project_id)
    except (ValueError, AttributeError) as error:
        raise InvalidProjectIdError("project ID must be a canonical UUID") from error
    if str(parsed) != project_id or parsed.version != 4:
        raise InvalidProjectIdError("project ID must be a canonical version 4 UUID")
    return project_id


class ProjectStorage:
    """Resolves and initializes one physically isolated SQLite file per project."""

    def __init__(self, root: Path = PROJECT_STORAGE_ROOT):
        self.root = root.resolve()

    def location(self, project_id: str) -> ProjectStorageLocation:
        canonical = canonical_project_id(project_id)
        expected_directory = self.root / canonical
        directory = expected_directory.resolve()
        expected_database = directory / DATABASE_FILENAME
        database = expected_database.resolve()
        if not directory.is_relative_to(self.root) or not database.is_relative_to(directory):
            raise InvalidProjectIdError("project storage path escapes its configured root")
        if directory != expected_directory or database != expected_database:
            raise ProjectStorageConflictError("project storage path is redirected or shared")
        return ProjectStorageLocation(canonical, directory, database)

    def initialize(self, project_id: str) -> ProjectStorageLocation:
        location = self.location(project_id)
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise ProjectStorageConflictError(
                "project storage root cannot be initialized"
            ) from error
        location = self.location(project_id)
        try:
            location.directory.mkdir(exist_ok=True)
        except OSError as error:
            raise ProjectStorageConflictError(
                "project storage directory conflicts with an existing path"
            ) from error
        location = self.location(project_id)

        if location.database.exists():
            self._validate_existing(location)
            return location

        if location.database.parent != location.directory:
            raise InvalidProjectIdError("project database path is not isolated")
        with sqlite3.connect(location.database) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(
                """
                CREATE TABLE project_storage_metadata (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    project_id TEXT NOT NULL UNIQUE,
                    storage_format INTEGER NOT NULL CHECK (storage_format = 1)
                )
                """
            )
            connection.execute(
                "INSERT INTO project_storage_metadata(singleton, project_id, storage_format) VALUES (1, ?, ?)",
                (location.project_id, STORAGE_FORMAT_VERSION),
            )
        self._validate_existing(location)
        return location

    def export_package(self, project_id: str, destination: Path) -> dict[str, object]:
        location = self.location(project_id)
        self._validate_existing(location)
        output = destination.resolve()
        if output == location.database or output.is_dir():
            raise ProjectPackageError("project export destination is invalid")
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary_directory = Path(
            tempfile.mkdtemp(prefix=".project-export-", dir=output.parent)
        )
        temporary_package = temporary_directory / output.name
        database_copy = temporary_directory / DATABASE_FILENAME
        try:
            with read_only_database(location.database) as source, sqlite3.connect(
                database_copy
            ) as target:
                source.backup(target)
            metadata = _database_metadata(database_copy, location.project_id)
            metadata_bytes = _json_bytes(metadata)
            manifest = {
                "packageFormatVersion": PACKAGE_FORMAT_VERSION,
                "projectId": location.project_id,
                "storageFormatVersion": STORAGE_FORMAT_VERSION,
                "schemaVersion": metadata["schemaVersion"],
                "editorialSchemaVersion": metadata["editorialSchemaVersion"],
                "schemaSha256": metadata["schemaSha256"],
                "components": {
                    DATABASE_FILENAME: {
                        "role": "project_database",
                        "size": database_copy.stat().st_size,
                        "sha256": _sha256(database_copy),
                    },
                    PACKAGE_METADATA_FILENAME: {
                        "role": "project_metadata",
                        "size": len(metadata_bytes),
                        "sha256": hashlib.sha256(metadata_bytes).hexdigest(),
                    },
                },
            }
            with zipfile.ZipFile(temporary_package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(_zip_info(PACKAGE_MANIFEST_FILENAME), _json_bytes(manifest))
                with database_copy.open("rb") as source, archive.open(
                    _zip_info(DATABASE_FILENAME), "w"
                ) as target:
                    shutil.copyfileobj(source, target, length=1024 * 1024)
                archive.writestr(_zip_info(PACKAGE_METADATA_FILENAME), metadata_bytes)
            if output.exists():
                if not output.is_file() or _sha256(output) != _sha256(temporary_package):
                    raise ProjectStorageConflictError("project export destination already exists")
            else:
                os.replace(temporary_package, output)
            return {
                "exported": True,
                "package": str(output),
                "projectId": location.project_id,
                "sha256": _sha256(output),
                "manifest": manifest,
            }
        finally:
            shutil.rmtree(temporary_directory, ignore_errors=True)

    def import_package(self, package: Path) -> dict[str, object]:
        package_path = package.resolve()
        if not package_path.is_file():
            raise ProjectPackageError("project package does not exist")
        try:
            with zipfile.ZipFile(package_path) as archive:
                names = archive.namelist()
                expected_names = {PACKAGE_MANIFEST_FILENAME, *PACKAGE_COMPONENTS}
                if len(names) != len(set(names)) or set(names) != expected_names:
                    raise ProjectPackageError("project package component inventory is invalid")
                manifest_info = archive.getinfo(PACKAGE_MANIFEST_FILENAME)
                metadata_info = archive.getinfo(PACKAGE_METADATA_FILENAME)
                database_info = archive.getinfo(DATABASE_FILENAME)
                if (
                    manifest_info.file_size > MAX_MANIFEST_BYTES
                    or metadata_info.file_size > MAX_METADATA_BYTES
                    or database_info.file_size > MAX_DATABASE_BYTES
                ):
                    raise ProjectPackageError("project package component is too large")
                manifest = json.loads(archive.read(PACKAGE_MANIFEST_FILENAME))
                metadata_bytes = archive.read(PACKAGE_METADATA_FILENAME)
                metadata = json.loads(metadata_bytes)
        except ProjectPackageError:
            raise
        except (OSError, zipfile.BadZipFile, KeyError, json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ProjectPackageError("project package is invalid") from error

        if not isinstance(manifest, dict) or not isinstance(metadata, dict):
            raise ProjectPackageError("project package metadata is invalid")
        # Packages created before the embedded editorial domain did not expose
        # a separate editorial schema version. Their database has version 0.
        metadata.setdefault("editorialSchemaVersion", 0)
        project_id = manifest.get("projectId")
        try:
            canonical_project_id(project_id)
        except InvalidProjectIdError as error:
            raise ProjectPackageError("project package has an invalid project UUID") from error
        components = manifest.get("components")
        if (
            manifest.get("packageFormatVersion") != PACKAGE_FORMAT_VERSION
            or manifest.get("storageFormatVersion") != STORAGE_FORMAT_VERSION
            or not isinstance(components, dict)
            or set(components) != PACKAGE_COMPONENTS
        ):
            raise ProjectPackageError("project package format is unsupported")
        for name, role in (
            (DATABASE_FILENAME, "project_database"),
            (PACKAGE_METADATA_FILENAME, "project_metadata"),
        ):
            component = components.get(name)
            if (
                not isinstance(component, dict)
                or component.get("role") != role
                or not isinstance(component.get("size"), int)
                or not isinstance(component.get("sha256"), str)
            ):
                raise ProjectPackageError("project package manifest is invalid")
        metadata_component = components[PACKAGE_METADATA_FILENAME]
        if (
            metadata_component["size"] != len(metadata_bytes)
            or metadata_component["sha256"] != hashlib.sha256(metadata_bytes).hexdigest()
        ):
            raise ProjectPackageError("project metadata hash does not match the manifest")

        location = self.location(project_id)
        self.root.mkdir(parents=True, exist_ok=True)
        staging_directory = Path(
            tempfile.mkdtemp(prefix=f".{project_id}-import-", dir=self.root)
        )
        staged_database = staging_directory / DATABASE_FILENAME
        try:
            digest = hashlib.sha256()
            size = 0
            with zipfile.ZipFile(package_path) as archive, archive.open(
                DATABASE_FILENAME
            ) as source, staged_database.open("wb") as target:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    size += len(chunk)
                    if size > MAX_DATABASE_BYTES:
                        raise ProjectPackageError("project database component is too large")
                    digest.update(chunk)
                    target.write(chunk)
            database_component = components[DATABASE_FILENAME]
            if (
                size != database_component["size"]
                or digest.hexdigest() != database_component["sha256"]
            ):
                raise ProjectPackageError("project database hash does not match the manifest")
            actual_metadata = _database_metadata(staged_database, project_id)
            if metadata != actual_metadata:
                raise ProjectPackageError("project metadata does not match the project database")
            if (
                manifest.get("schemaVersion") != actual_metadata["schemaVersion"]
                or manifest.get("editorialSchemaVersion", 0) != actual_metadata["editorialSchemaVersion"]
                or manifest.get("schemaSha256") != actual_metadata["schemaSha256"]
            ):
                raise ProjectPackageError("project schema does not match the manifest")
            if location.directory.exists():
                self._validate_existing(location)
                if _sha256(location.database) != database_component["sha256"]:
                    raise ProjectStorageConflictError("project storage already exists with different content")
                return {
                    "imported": False,
                    "projectId": project_id,
                    "database": str(location.database),
                    "sha256": database_component["sha256"],
                }
            os.replace(staging_directory, location.directory)
            return {
                "imported": True,
                "projectId": project_id,
                "database": str(location.database),
                "sha256": database_component["sha256"],
            }
        finally:
            shutil.rmtree(staging_directory, ignore_errors=True)

    @staticmethod
    def _validate_existing(location: ProjectStorageLocation) -> None:
        if not location.database.is_file():
            raise ProjectStorageConflictError("project database path is not a regular file")
        try:
            with read_only_database(location.database) as connection:
                integrity = connection.execute("PRAGMA integrity_check").fetchall()
                row = connection.execute(
                    "SELECT singleton, project_id, storage_format FROM project_storage_metadata"
                ).fetchone()
                count = connection.execute(
                    "SELECT count(*) FROM project_storage_metadata"
                ).fetchone()[0]
        except (sqlite3.Error, FileNotFoundError) as error:
            raise ProjectStorageConflictError(
                "existing project storage is not a valid initialized database"
            ) from error
        if [tuple(item) for item in integrity] != [("ok",)]:
            raise ProjectStorageConflictError("existing project storage failed integrity check")
        if (
            count != 1
            or row is None
            or row["singleton"] != 1
            or row["project_id"] != location.project_id
            or row["storage_format"] != STORAGE_FORMAT_VERSION
        ):
            raise ProjectStorageConflictError(
                "existing project storage belongs to another project or format"
            )

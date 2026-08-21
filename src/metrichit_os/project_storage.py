from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from .config import PROJECT_STORAGE_ROOT
from .database import read_only_database


STORAGE_FORMAT_VERSION = 1
DATABASE_FILENAME = "project.sqlite"


class ProjectStorageError(ValueError):
    """Base error for an invalid or conflicting project storage."""


class InvalidProjectIdError(ProjectStorageError):
    """Raised when a project ID cannot safely identify one storage."""


class ProjectStorageConflictError(ProjectStorageError):
    """Raised when an existing path does not belong to the requested project."""


@dataclass(frozen=True)
class ProjectStorageLocation:
    project_id: str
    directory: Path
    database: Path


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

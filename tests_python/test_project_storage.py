from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from metrichit_os.project_storage import (
    InvalidProjectIdError,
    ProjectStorage,
    ProjectStorageConflictError,
)


PROJECT_A = "10000000-0000-4000-a000-000000000001"
PROJECT_B = "20000000-0000-4000-a000-000000000002"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_two_projects_get_distinct_physical_databases(tmp_path: Path) -> None:
    storage = ProjectStorage(tmp_path / "projects")

    first = storage.initialize(PROJECT_A)
    second = storage.initialize(PROJECT_B)

    assert first.database.is_file()
    assert second.database.is_file()
    assert first.directory != second.directory
    assert first.database != second.database
    assert first.database.parent == first.directory
    assert second.database.parent == second.directory
    with sqlite3.connect(first.database) as connection:
        assert connection.execute(
            "SELECT project_id FROM project_storage_metadata"
        ).fetchone()[0] == PROJECT_A
    with sqlite3.connect(second.database) as connection:
        assert connection.execute(
            "SELECT project_id FROM project_storage_metadata"
        ).fetchone()[0] == PROJECT_B


@pytest.mark.parametrize(
    "project_id",
    [
        "../escape",
        "10000000-0000-4000-a000-000000000001/../../escape",
        "C:\\escape",
        "10000000-0000-4000-A000-000000000001",
        "00000000-0000-0000-0000-000000000000",
        "",
    ],
)
def test_invalid_or_traversing_project_id_is_rejected(
    tmp_path: Path, project_id: str
) -> None:
    storage = ProjectStorage(tmp_path / "projects")

    with pytest.raises(InvalidProjectIdError, match="project ID"):
        storage.initialize(project_id)

    assert not storage.root.exists()


def test_repeated_initialization_is_idempotent(tmp_path: Path) -> None:
    storage = ProjectStorage(tmp_path / "projects")
    first = storage.initialize(PROJECT_A)
    before = _sha256(first.database)

    second = storage.initialize(PROJECT_A)

    assert second == first
    assert _sha256(second.database) == before


def test_existing_storage_with_different_identity_is_rejected(tmp_path: Path) -> None:
    storage = ProjectStorage(tmp_path / "projects")
    location = storage.initialize(PROJECT_A)
    with sqlite3.connect(location.database) as connection:
        connection.execute(
            "UPDATE project_storage_metadata SET project_id=?", (PROJECT_B,)
        )

    with pytest.raises(ProjectStorageConflictError, match="another project"):
        storage.initialize(PROJECT_A)


def test_existing_non_directory_project_path_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "projects"
    root.mkdir()
    (root / PROJECT_A).write_text("conflict", encoding="utf-8")

    with pytest.raises(ProjectStorageConflictError, match="conflicts"):
        ProjectStorage(root).initialize(PROJECT_A)

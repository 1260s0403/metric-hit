from __future__ import annotations

import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from metrichit_os import cli
from metrichit_os.project_storage import (
    InvalidProjectIdError,
    ProjectPackageError,
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


def _add_transfer_data(database: Path) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("CREATE TABLE parent (id TEXT PRIMARY KEY)")
        connection.execute(
            "CREATE TABLE child (id TEXT PRIMARY KEY, parent_id TEXT NOT NULL REFERENCES parent(id))"
        )
        connection.execute("INSERT INTO parent VALUES ('parent')")
        connection.execute("INSERT INTO child VALUES ('child','parent')")
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, "
            "checksum TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO schema_migrations VALUES "
            "(7,'007_test.sql','abc','2026-08-28T00:00:00Z')"
        )


def _rewrite_package(package: Path, replacements: dict[str, bytes]) -> None:
    with zipfile.ZipFile(package) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    members.update(replacements)
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in members.items():
            archive.writestr(name, value)


def test_export_import_round_trip_is_atomic_and_idempotent(tmp_path: Path) -> None:
    source_storage = ProjectStorage(tmp_path / "source")
    source = source_storage.initialize(PROJECT_A)
    _add_transfer_data(source.database)
    source_before = _sha256(source.database)
    package = tmp_path / "project.mhproject"

    exported = source_storage.export_package(PROJECT_A, package)
    first_package_hash = _sha256(package)
    repeated_export = source_storage.export_package(PROJECT_A, package)

    assert exported["projectId"] == PROJECT_A
    assert repeated_export["sha256"] == first_package_hash
    assert _sha256(source.database) == source_before
    with zipfile.ZipFile(package) as archive:
        assert set(archive.namelist()) == {"manifest.json", "project.json", "project.sqlite"}
        manifest = json.loads(archive.read("manifest.json"))
        metadata = json.loads(archive.read("project.json"))
    assert manifest["packageFormatVersion"] == 1
    assert manifest["storageFormatVersion"] == 1
    assert manifest["schemaVersion"] == 7
    assert manifest["schemaSha256"] == metadata["schemaSha256"]
    assert metadata["projectId"] == PROJECT_A

    target_storage = ProjectStorage(tmp_path / "target")
    imported = target_storage.import_package(package)
    repeated = target_storage.import_package(package)

    assert imported["imported"] is True
    assert repeated["imported"] is False
    target = target_storage.location(PROJECT_A)
    assert _sha256(target.database) == manifest["components"]["project.sqlite"]["sha256"]
    with sqlite3.connect(target.database) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("SELECT id,parent_id FROM child").fetchone() == ("child", "parent")


def test_import_rejects_tampered_database_before_creating_target(tmp_path: Path) -> None:
    source_storage = ProjectStorage(tmp_path / "source")
    source_storage.initialize(PROJECT_A)
    package = tmp_path / "project.mhproject"
    source_storage.export_package(PROJECT_A, package)
    with zipfile.ZipFile(package) as archive:
        database = bytearray(archive.read("project.sqlite"))
    database[-1] ^= 1
    _rewrite_package(package, {"project.sqlite": bytes(database)})
    target_storage = ProjectStorage(tmp_path / "target")

    with pytest.raises(ProjectPackageError, match="hash"):
        target_storage.import_package(package)

    assert not target_storage.location(PROJECT_A).directory.exists()


def test_import_rejects_foreign_key_failure_even_with_matching_hash(tmp_path: Path) -> None:
    source_storage = ProjectStorage(tmp_path / "source")
    source = source_storage.initialize(PROJECT_A)
    _add_transfer_data(source.database)
    package = tmp_path / "project.mhproject"
    source_storage.export_package(PROJECT_A, package)
    with zipfile.ZipFile(package) as archive:
        database_path = tmp_path / "tampered.sqlite"
        database_path.write_bytes(archive.read("project.sqlite"))
        manifest = json.loads(archive.read("manifest.json"))
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("UPDATE child SET parent_id='missing'")
    database = database_path.read_bytes()
    manifest["components"]["project.sqlite"].update(
        size=len(database), sha256=hashlib.sha256(database).hexdigest()
    )
    _rewrite_package(
        package,
        {
            "project.sqlite": database,
            "manifest.json": (json.dumps(manifest, sort_keys=True) + "\n").encode(),
        },
    )

    with pytest.raises(ProjectPackageError, match="foreign key"):
        ProjectStorage(tmp_path / "target").import_package(package)


def test_import_rejects_invalid_uuid_and_existing_content_conflict(tmp_path: Path) -> None:
    source_storage = ProjectStorage(tmp_path / "source")
    source_storage.initialize(PROJECT_A)
    package = tmp_path / "project.mhproject"
    source_storage.export_package(PROJECT_A, package)
    with zipfile.ZipFile(package) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    manifest["projectId"] = "../escape"
    invalid_package = tmp_path / "invalid.mhproject"
    invalid_package.write_bytes(package.read_bytes())
    _rewrite_package(
        invalid_package,
        {"manifest.json": (json.dumps(manifest, sort_keys=True) + "\n").encode()},
    )
    target_storage = ProjectStorage(tmp_path / "target")

    with pytest.raises(ProjectPackageError, match="UUID"):
        target_storage.import_package(invalid_package)

    target = target_storage.initialize(PROJECT_A)
    with sqlite3.connect(target.database) as connection:
        connection.execute("CREATE TABLE local_change (id INTEGER PRIMARY KEY)")
    with pytest.raises(ProjectStorageConflictError, match="different content"):
        target_storage.import_package(package)


def test_import_accepts_pre_editorial_package_metadata(tmp_path: Path) -> None:
    source_storage = ProjectStorage(tmp_path / "source")
    source_storage.initialize(PROJECT_A)
    package = tmp_path / "legacy-project.mhproject"
    source_storage.export_package(PROJECT_A, package)
    with zipfile.ZipFile(package) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        metadata = json.loads(archive.read("project.json"))
    manifest.pop("editorialSchemaVersion")
    metadata.pop("editorialSchemaVersion")
    metadata_bytes = (json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    manifest["components"]["project.json"].update(
        size=len(metadata_bytes), sha256=hashlib.sha256(metadata_bytes).hexdigest()
    )
    _rewrite_package(
        package,
        {
            "manifest.json": (json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(),
            "project.json": metadata_bytes,
        },
    )

    imported = ProjectStorage(tmp_path / "target").import_package(package)

    assert imported["imported"] is True


def test_project_transfer_cli_round_trip(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source_root = tmp_path / "source"
    ProjectStorage(source_root).initialize(PROJECT_A)
    package = tmp_path / "project.mhproject"
    target_root = tmp_path / "target"

    assert cli.run_workflow_command(
        [
            "project-export",
            "--project-id",
            PROJECT_A,
            "--storage-root",
            str(source_root),
            "--output",
            str(package),
        ]
    ) == 0
    exported = json.loads(capsys.readouterr().out)
    assert exported["projectId"] == PROJECT_A

    assert cli.run_workflow_command(
        ["project-import", "--package", str(package), "--storage-root", str(target_root)]
    ) == 0
    imported = json.loads(capsys.readouterr().out)
    assert imported["imported"] is True
    assert ProjectStorage(target_root).location(PROJECT_A).database.is_file()

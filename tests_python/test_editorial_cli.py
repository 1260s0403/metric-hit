from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from metrichit_os.config import EDITORIAL_DATABASE, MEMORY_DATABASE
from metrichit_os.database import sha256_file
from metrichit_os.editorial_store import (
    EditorialStore,
    WorkflowError,
    WorkingDatabaseWriteError,
    assert_writable_target,
    initialize_workflow_database,
)

from workflow_helpers import digest


def run_cli(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "metrichit_os", *arguments],
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_cli_initializes_explicit_database_and_returns_json(tmp_path):
    database = tmp_path / "cli.sqlite"
    initialized = json.loads(run_cli("init-editorial-db", "--db", str(database)).stdout)
    assert initialized["migration_versions"] == [1, 2]
    request = json.dumps({
        "idempotency_key": "cli-run",
        "business_date": "2026-08-14",
        "timezone": "Europe/Moscow",
        "mode": "simulation",
        "config_sha256": digest("cli-config"),
    })
    run = json.loads(run_cli("create-run", "--db", str(database), "--data", request).stdout)
    shown = json.loads(run_cli("show-run", "--db", str(database), "--run-id", run["id"]).stdout)
    actions = json.loads(run_cli("next-actions", "--db", str(database), "--run-id", run["id"]).stdout)
    audit = json.loads(run_cli("audit-trail", "--db", str(database), "--run-id", run["id"]).stdout)
    assert shown["run"]["workflow_stage"] == "research"
    assert "add_research" in actions["actions"]
    assert audit["chain_valid"] is True


def test_cli_refuses_working_editorial_database(tmp_path):
    before = sha256_file(EDITORIAL_DATABASE)
    result = run_cli("init-editorial-db", "--db", str(EDITORIAL_DATABASE), check=False)
    assert result.returncode == 2
    assert json.loads(result.stdout)["error"] == "WorkingDatabaseWriteError"
    assert sha256_file(EDITORIAL_DATABASE) == before


def test_all_working_database_family_paths_are_protected():
    for database in (EDITORIAL_DATABASE, MEMORY_DATABASE):
        for path in (
            database,
            database.with_name(database.name + "-wal"),
            database.with_name(database.name + "-shm"),
            database.with_name(database.name + "-journal"),
        ):
            with pytest.raises(WorkingDatabaseWriteError):
                assert_writable_target(path)


def test_write_command_requires_explicit_database():
    result = run_cli("create-run", "--data", "{}", check=False)
    assert result.returncode == 2
    assert json.loads(result.stdout)["error"] == "ValueError"


def test_schema_attestation_rejects_missing_trigger(tmp_path):
    database = tmp_path / "tampered.sqlite"
    initialize_workflow_database(database)
    import sqlite3
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TRIGGER material_versions_prevent_delete")
    with pytest.raises(WorkflowError, match="schema attestation"):
        EditorialStore(database)


def test_writable_connection_rechecks_hardlink_swap(tmp_path):
    database = tmp_path / "swapped.sqlite"
    initialize_workflow_database(database)
    store = EditorialStore(database)
    database.unlink()
    try:
        os.link(EDITORIAL_DATABASE, database)
    except OSError as error:
        pytest.skip(f"hard links unavailable: {error}")
    with pytest.raises(WorkingDatabaseWriteError):
        with store.transaction():
            pass

import sqlite3

import pytest

from metrichit_os.config import EDITORIAL_DATABASE, MEMORY_DATABASE, repository_path
from metrichit_os.database import read_only_database, sha256_file
from metrichit_os.services import current_context, editorial_status, memory_summary


def database_family_state(path):
    state = {}
    for suffix in ("", "-wal", "-shm"):
        member = path.with_name(path.name + suffix)
        if member.exists():
            metadata = member.stat()
            state[suffix] = {
                "sha256": sha256_file(member),
                "size": metadata.st_size,
            }
    return state


def test_python_checks_do_not_change_database_bytes():
    before = {
        path: database_family_state(path)
        for path in (MEMORY_DATABASE, EDITORIAL_DATABASE)
    }
    memory_summary()
    editorial_status()
    current_context()
    after = {
        path: database_family_state(path)
        for path in (MEMORY_DATABASE, EDITORIAL_DATABASE)
    }
    assert after == before


def test_database_connections_reject_writes():
    for path in (MEMORY_DATABASE,):
        with read_only_database(path) as database:
            with pytest.raises(sqlite3.OperationalError):
                database.execute("CREATE TABLE forbidden_write(value TEXT)")


def test_absent_editorial_database_is_reported_as_paused():
    assert not EDITORIAL_DATABASE.exists()
    assert editorial_status() == {
        "exists": False,
        "state": "paused",
        "integrity": "not_applicable",
        "migration_count": 0,
        "tables": [],
        "entities": {
            table: {"count": 0, "statuses": {}}
            for table in ("editorial_runs", "daily_plans", "materials", "approvals", "publication_jobs")
        },
    }


def test_repository_path_rejects_traversal():
    with pytest.raises(ValueError, match="escapes the repository"):
        repository_path("..", "outside")

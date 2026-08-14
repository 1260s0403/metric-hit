import json
import subprocess

import pytest

from metrichit_os.config import EDITORIAL_DATABASE, MEMORY_DATABASE
from metrichit_os.database import sha256_file
from metrichit_os.services import current_context, editorial_status, memory_summary


def node_snapshot() -> dict[str, object]:
    result = subprocess.run(
        ["node", "scripts/compatibility-snapshot.mjs"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def parity_snapshots():
    before = {
        "memory": sha256_file(MEMORY_DATABASE),
        "editorial": sha256_file(EDITORIAL_DATABASE),
    }
    snapshots = {
        "node": node_snapshot(),
        "python": {
            "memory": memory_summary(),
            "editorial": editorial_status(),
            "context": current_context(),
        },
    }
    after = {
        "memory": sha256_file(MEMORY_DATABASE),
        "editorial": sha256_file(EDITORIAL_DATABASE),
    }
    assert after == before
    return snapshots


def test_python_matches_node_memory_contract(parity_snapshots):
    assert parity_snapshots["python"]["memory"] == parity_snapshots["node"]["memory"]


def test_python_matches_node_editorial_contract(parity_snapshots):
    assert parity_snapshots["python"]["editorial"] == parity_snapshots["node"]["editorial"]


def test_python_matches_node_current_context_bytes(parity_snapshots):
    assert parity_snapshots["python"]["context"] == parity_snapshots["node"]["context"]

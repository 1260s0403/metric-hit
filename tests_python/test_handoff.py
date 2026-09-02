from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys

import pytest

from metrichit_os.config import MEMORY_DATABASE
from metrichit_os.handoff import HandoffError, HandoffStore, format_handoff
from metrichit_os.knowledge_store import KnowledgeStore


def temporary_database(tmp_path):
    database = tmp_path / "memory.sqlite"
    subprocess.run(["node", "scripts/init-memory.mjs", str(database)], check=True, capture_output=True, text=True)
    return database


def payload(**changes):
    value = {
        "idempotency_key": "handoff-unified-inbox-v1",
        "semantic_key": "architecture.unified_inbox_mvp",
        "goal": "Реализовать единый входящий поток",
        "scope": ["Текст", "Ссылки", "Файлы"],
        "constraints": ["Без UI", "Без фонового процесса"],
        "acceptance": ["Focused tests проходят", "Git остаётся чистым после коммита"],
        "source": "owner decision 2026-08-15",
        "project_id": None,
        "approved_by": "owner",
    }
    value.update(changes)
    return value


def resources(tmp_path, name, *, paths=None, sqlite_resources=None, shared=None):
    return {
        "canonical_worktree": str(tmp_path / "canonical"),
        "worktree": str(tmp_path / name),
        "branch": f"codex/{name}",
        "base_head": "a" * 40,
        "paths": paths or [f"work/{name}"],
        "sqlite": sqlite_resources or [],
        "shared": shared or [],
    }


def parallel_payload(tmp_path, name, **resource_changes):
    declaration = resources(tmp_path, name, **resource_changes)
    return payload(
        idempotency_key=f"parallel-{name}", semantic_key=f"architecture.parallel_{name}",
        goal=f"Parallel writer {name}", execution_resources=declaration,
    )


def orchestration_payload(tmp_path, name="editorial-orchestration"):
    value = parallel_payload(tmp_path, name, paths=[f"work/{name}"])
    value["orchestration"] = {
        "profile_id": "metrichit.editorial.v1",
        "parent_context_pack_id": "pack-editorial-v1",
        "task_scope_id": "scope:task:editorial-v1",
        "task_type": "editorial",
        "scope_chain": [
            "scope:core", "scope:project:metrichit", "scope:subproject:editorial", "scope:task:editorial-v1",
        ],
    }
    return value


def delegation_for(handoff, **changes):
    value = {
        "delegation_depth": 2,
        "selected_skills": ["copywriting", "seo-strategy"],
        "research_branches": 3,
        "child_card": {
            "result": "Editorial result is ready",
            "scope": list(handoff["scope"]),
            "resources": handoff["execution_resources"],
            "mandatory_rules": ["AGENTS.md", "Editorial scoped rules"],
            "first_check": "focused editorial check",
            "acceptance": ["domain evidence exists"],
            "forbidden_changes": ["publication"],
        },
    }
    value.update(changes)
    return value


def worker_evidence(commit="3" * 40):
    return {
        "commit_hash": commit,
        "checks": ["focused editorial check"],
        "acceptance": ["domain evidence exists"],
        "clean_git": True,
        "result": "Verified editorial result",
    }


def test_approved_decision_creates_linked_existing_task_and_is_idempotent(tmp_path):
    database = temporary_database(tmp_path)
    store = HandoffStore(database)
    first = store.create_approved(payload())
    second = store.create_approved(payload())
    assert second == first == store.next()
    assert first["handoff_id"] == first["task_id"]
    assert first["status"] == "ready"
    assert first["decision"]["semantic_key"] == "architecture.unified_inbox_mvp"
    assert first["goal"] == "Реализовать единый входящий поток"

    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        candidate = connection.execute("SELECT * FROM memory_candidates WHERE id=?", (first["decision"]["candidate_id"],)).fetchone()
        task = connection.execute("SELECT * FROM tasks WHERE id=?", (first["task_id"],)).fetchone()
        assert candidate["status"] == "approved"
        assert task["type"] == "standalone_task"
        assert task["source_id"] == first["decision"]["source_id"]
        assert json.loads(task["data_json"])["handoff"]["decision_candidate_id"] == candidate["id"]
        assert json.loads(task["data_json"])["handoff"]["lifecycle"] == {"status": "ready"}
        assert connection.execute("SELECT count(*) FROM memory_candidates WHERE semantic_key=?", (candidate["semantic_key"],)).fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM tasks WHERE id=?", (task["id"],)).fetchone()[0] == 1


def test_idempotency_conflict_semantic_duplicate_and_explicit_evolution(tmp_path):
    database = temporary_database(tmp_path)
    store = HandoffStore(database)
    first = store.create_approved(payload())
    with pytest.raises(HandoffError, match="idempotency key"):
        store.create_approved(payload(goal="Другая цель"))
    with pytest.raises(HandoffError, match="semantic evolution"):
        store.create_approved(payload(idempotency_key="second"))
    evolved = store.create_approved(payload(
        idempotency_key="second",
        goal="Реализовать единый входящий поток v2",
        supersedes_candidate_id=first["decision"]["candidate_id"],
    ))
    assert evolved["decision"]["candidate_id"] != first["decision"]["candidate_id"]
    assert store.next()["task_id"] == evolved["task_id"]
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT status FROM tasks WHERE id=?", (first["task_id"],)).fetchone()[0] == "cancelled"

    duplicate = payload(
        idempotency_key="duplicate",
        semantic_key="architecture.different_key",
        supersedes_candidate_id=None,
        goal="Реализовать единый входящий поток v2",
    )
    with pytest.raises(HandoffError, match="semantic duplicate"):
        store.create_approved(duplicate)


def test_next_returns_only_active_handoffs_and_does_not_break_user_tasks(tmp_path):
    database = temporary_database(tmp_path)
    knowledge = KnowledgeStore(database)
    entry = knowledge.add(kind="idea", topic="Пользовательская задача", text="Не handoff")
    user_task = knowledge.to_task(entry_id=str(entry["id"]))
    handoff = HandoffStore(database).create_approved(payload())
    assert HandoffStore(database).next()["task_id"] == handoff["task_id"]
    assert {item["id"] for item in knowledge.list_tasks()} == {user_task["id"], handoff["task_id"]}
    claimed = HandoffStore(database).claim(handoff["handoff_id"], "developer-a")
    assert claimed["status"] == "in_progress"
    completed = HandoffStore(database).complete(handoff["handoff_id"], "a" * 40, "developer-a")
    assert completed["status"] == "completed"
    assert HandoffStore(database).next() is None
    assert knowledge.list_tasks(status="open")[0]["id"] == user_task["id"]


def test_project_link_must_be_active(tmp_path):
    database = temporary_database(tmp_path)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO documents (id,type,title,content,data_json,status,author,access_level) VALUES ('30000000-0000-4000-a000-000000000000','project','Active','Active','{}','active','owner','internal')"
        )
        connection.execute(
            "INSERT INTO documents (id,type,title,content,data_json,status,author,access_level) VALUES ('30000000-0000-4000-a000-000000000001','project','Archive','Archive','{}','archived','owner','internal')"
        )
    linked = HandoffStore(database).create_approved(payload(project_id="30000000-0000-4000-a000-000000000000"))
    assert linked["project_id"] == "30000000-0000-4000-a000-000000000000"
    with sqlite3.connect(database) as connection:
        task_data = json.loads(connection.execute("SELECT data_json FROM tasks WHERE id=?", (linked["task_id"],)).fetchone()[0])
        assert task_data["project_id"] == linked["project_id"]
    with pytest.raises(HandoffError, match="active"):
        HandoffStore(database).create_approved(payload(idempotency_key="archived-project", semantic_key="architecture.archived-project", project_id="30000000-0000-4000-a000-000000000001"))


def test_pending_duplicate_and_memory_conflict_block_atomic_handoff(tmp_path):
    database = temporary_database(tmp_path)
    with sqlite3.connect(database) as connection:
        source_id = "40000000-0000-4000-a000-000000000001"
        connection.execute(
            "INSERT INTO sources (id,type,title,content,status,author,access_level) VALUES (?, 'owner_decision', 'Pending', 'Pending', 'active', 'owner', 'internal')",
            (source_id,),
        )
        connection.execute(
            "INSERT INTO memory_candidates (id,type,semantic_key,title,content,status,source_id,author,access_level) VALUES ('40000000-0000-4000-a000-000000000002','decision','architecture.unified_inbox_mvp','Pending','Pending','pending',?,'owner','internal')",
            (source_id,),
        )
    with pytest.raises(HandoffError, match="pending semantic duplicate"):
        HandoffStore(database).create_approved(payload())

    conflicted_directory = tmp_path / "conflicted"
    conflicted_directory.mkdir()
    conflicted = temporary_database(conflicted_directory)
    with sqlite3.connect(conflicted) as connection:
        source_id = "50000000-0000-4000-a000-000000000001"
        item_id = "50000000-0000-4000-a000-000000000002"
        connection.execute(
            "INSERT INTO sources (id,type,title,content,status,author,access_level) VALUES (?, 'owner_decision', 'Existing', 'Existing', 'active', 'owner', 'internal')",
            (source_id,),
        )
        connection.execute(
            "INSERT INTO memory_items (id,type,semantic_key,title,content,data_json,status,source_id,author,access_level) VALUES (?, 'decision','architecture.unified_inbox_mvp','Existing','Different','{}','active',?,'owner','internal')",
            (item_id, source_id),
        )
    with pytest.raises(HandoffError, match="produced a memory conflict"):
        HandoffStore(conflicted).create_approved(payload())
    with sqlite3.connect(conflicted) as connection:
        assert connection.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM memory_candidates").fetchone()[0] == 0


def test_cli_create_and_next_return_stable_json_and_text(tmp_path):
    database = temporary_database(tmp_path)
    created = subprocess.run(
        [sys.executable, "-m", "metrichit_os", "handoff-create", "--db", str(database), "--stdin"],
        input=json.dumps(payload(), ensure_ascii=False), capture_output=True, text=True, encoding="utf-8", check=True,
    )
    first = json.loads(created.stdout)
    machine = subprocess.run(
        [sys.executable, "-m", "metrichit_os", "handoff-next", "--db", str(database)],
        capture_output=True, text=True, encoding="utf-8", check=True,
    )
    assert json.loads(machine.stdout)["handoff"] == first
    text = subprocess.run(
        [sys.executable, "-m", "metrichit_os", "handoff-next", "--db", str(database), "--format", "text"],
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout
    assert text == format_handoff(first)
    assert "# Codex engineering handoff" in text
    assert "Decision: architecture.unified_inbox_mvp" in text
    claimed = subprocess.run(
        [sys.executable, "-m", "metrichit_os", "handoff-claim", "--db", str(database), "--id", first["handoff_id"], "--developer", "developer-a"],
        capture_output=True, text=True, encoding="utf-8", check=True,
    )
    assert json.loads(claimed.stdout)["status"] == "in_progress"
    completed = subprocess.run(
        [sys.executable, "-m", "metrichit_os", "handoff-complete", "--db", str(database), "--id", first["handoff_id"], "--commit", "b" * 40, "--developer", "developer-a"],
        capture_output=True, text=True, encoding="utf-8", check=True,
    )
    assert json.loads(completed.stdout)["lifecycle"]["commit_hash"] == "b" * 40


def test_lifecycle_is_idempotent_and_allows_only_one_active_developer_handoff(tmp_path):
    database = temporary_database(tmp_path)
    store = HandoffStore(database)
    first = store.create_approved(payload())
    second = store.create_approved(payload(
        idempotency_key="handoff-second-v1",
        semantic_key="architecture.second_handoff_mvp",
        goal="Р РµР°Р»РёР·РѕРІР°С‚СЊ РІС‚РѕСЂРѕР№ РїРѕС‚РѕРє",
    ))
    claimed = store.claim(first["handoff_id"], "developer-a")
    assert store.claim(first["handoff_id"], "developer-a") == claimed
    with pytest.raises(HandoffError, match="another developer"):
        store.claim(first["handoff_id"], "developer-b")
    with pytest.raises(HandoffError, match="already in progress"):
        store.claim(second["handoff_id"], "developer-b")
    with pytest.raises(HandoffError, match="claimed before completion"):
        store.complete(second["handoff_id"], "c" * 40, "developer-b")
    completed = store.complete(first["handoff_id"], "c" * 40, "developer-a")
    assert store.complete(first["handoff_id"], "c" * 40, "developer-a") == completed
    with pytest.raises(HandoffError, match="different commit hash"):
        store.complete(first["handoff_id"], "d" * 40, "developer-a")
    assert store.next()["handoff_id"] == second["handoff_id"]


def test_parallel_v1_allows_two_isolated_writers_blocks_third_and_serializes_integration(tmp_path):
    store = HandoffStore(temporary_database(tmp_path))
    first = store.create_approved(parallel_payload(
        tmp_path, "articles", sqlite_resources=["data/projects/project-a/project.sqlite"],
    ))
    second = store.create_approved(parallel_payload(
        tmp_path, "landing", sqlite_resources=["data/projects/project-b/project.sqlite"],
    ))
    third = store.create_approved(parallel_payload(tmp_path, "project-c"))
    first_claim = store.claim(first["handoff_id"], "writer-a")
    assert store.claim(first["handoff_id"], "writer-a") == first_claim
    second_claim = store.claim(second["handoff_id"], "writer-b")
    assert second_claim["status"] == "in_progress"
    with pytest.raises(HandoffError, match="maximum active writer leases is two"):
        store.claim(third["handoff_id"], "writer-c")

    integration = store.begin_integration(first["handoff_id"], "writer-a", "b" * 40, "b" * 40, True)
    assert integration["lifecycle"]["integration"]["status"] == "integrating"
    assert store.begin_integration(first["handoff_id"], "writer-a", "b" * 40, "b" * 40, True) == integration
    with pytest.raises(HandoffError, match="integration is already in progress"):
        store.begin_integration(second["handoff_id"], "writer-b", "b" * 40, "b" * 40, True)
    with pytest.raises(HandoffError, match="stale base"):
        store.begin_integration(second["handoff_id"], "writer-b", "b" * 40, "c" * 40, True)
    with pytest.raises(HandoffError, match="merge conflict"):
        store.begin_integration(second["handoff_id"], "writer-b", "c" * 40, "c" * 40, False)
    store.complete(first["handoff_id"], "1" * 40, "writer-a")
    store.begin_integration(second["handoff_id"], "writer-b", "c" * 40, "c" * 40, True)
    store.complete(second["handoff_id"], "2" * 40, "writer-b")
    assert store.claim(third["handoff_id"], "writer-c")["status"] == "in_progress"


@pytest.mark.parametrize(
    ("first_changes", "second_changes", "message"),
    [
        ({"paths": ["work/articles"]}, {"paths": ["work/articles/drafts"]}, "path resource overlap"),
        ({"sqlite_resources": ["data/projects/a/project.sqlite"]}, {"sqlite_resources": ["data/projects/a/project.sqlite"]}, "same SQLite"),
        ({"shared": ["runtime:owner-panel"]}, {"shared": ["runtime:owner-panel"]}, "shared resource overlap"),
        ({"shared": ["core"]}, {}, "exclusive core or shared resource"),
        ({"paths": ["AGENTS.md"]}, {}, "exclusive core or shared resource"),
    ],
)
def test_parallel_v1_blocks_overlapping_or_exclusive_resources(tmp_path, first_changes, second_changes, message):
    store = HandoffStore(temporary_database(tmp_path))
    first = store.create_approved(parallel_payload(tmp_path, "first", **first_changes))
    second = store.create_approved(parallel_payload(tmp_path, "second", **second_changes))
    store.claim(first["handoff_id"], "writer-a")
    with pytest.raises(HandoffError, match=message):
        store.claim(second["handoff_id"], "writer-b")


def test_parallel_v1_fails_closed_on_missing_invalid_or_canonical_declarations(tmp_path):
    database = temporary_database(tmp_path)
    store = HandoffStore(database)
    declared = store.create_approved(parallel_payload(tmp_path, "declared"))
    legacy = store.create_approved(payload(
        idempotency_key="legacy-exclusive", semantic_key="architecture.legacy_exclusive", goal="Legacy exclusive",
    ))
    store.claim(declared["handoff_id"], "writer-a")
    with pytest.raises(HandoffError, match="missing execution resource declaration"):
        store.claim(legacy["handoff_id"], "writer-b")

    incomplete = resources(tmp_path, "incomplete")
    incomplete.pop("paths")
    with pytest.raises(HandoffError, match="must declare"):
        store.create_approved(payload(
            idempotency_key="invalid-incomplete", semantic_key="architecture.invalid_incomplete",
            goal="Invalid incomplete", execution_resources=incomplete,
        ))
    canonical = resources(tmp_path, "canonical-invalid")
    canonical["worktree"] = canonical["canonical_worktree"]
    with pytest.raises(HandoffError, match="canonical worktree"):
        store.create_approved(payload(
            idempotency_key="invalid-canonical", semantic_key="architecture.invalid_canonical",
            goal="Invalid canonical", execution_resources=canonical,
        ))


def test_parallel_v1_declared_writer_requires_integration_lease_before_completion(tmp_path):
    store = HandoffStore(temporary_database(tmp_path))
    created = store.create_approved(parallel_payload(tmp_path, "requires-integration"))
    store.claim(created["handoff_id"], "writer-a")
    with pytest.raises(HandoffError, match="integration lease"):
        store.complete(created["handoff_id"], "f" * 40, "writer-a")


@pytest.mark.parametrize(("field", "message"), [("worktree", "distinct worktrees"), ("branch", "distinct branches")])
def test_parallel_v1_requires_distinct_worktrees_and_branches(tmp_path, field, message):
    store = HandoffStore(temporary_database(tmp_path))
    first_resources = resources(tmp_path, "first")
    second_resources = resources(tmp_path, "second")
    second_resources[field] = first_resources[field]
    first = store.create_approved(payload(
        idempotency_key="distinct-first", semantic_key="architecture.distinct_first",
        goal="Distinct first", execution_resources=first_resources,
    ))
    second = store.create_approved(payload(
        idempotency_key="distinct-second", semantic_key="architecture.distinct_second",
        goal="Distinct second", execution_resources=second_resources,
    ))
    store.claim(first["handoff_id"], "writer-a")
    with pytest.raises(HandoffError, match=message):
        store.claim(second["handoff_id"], "writer-b")


def test_orchestration_v1_enforces_order_ownership_review_integration_and_strategy_completion(tmp_path):
    store = HandoffStore(temporary_database(tmp_path))
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "INSERT INTO context_packs (id,scope_id,task_type,compiler_version,input_hash,payload_json,compiled_bytes,status,created_at) "
            "VALUES ('pack-editorial-v1','scope:subproject:editorial','editorial',6,?,'{}',2,'open','2026-09-02T00:00:00.000Z')",
            ("a" * 64,),
        )
    created = store.create_approved(orchestration_payload(tmp_path))
    assert created["orchestration"]["lifecycle"]["stage"] == "routed"
    assert store.create_approved(orchestration_payload(tmp_path)) == created
    with pytest.raises(HandoffError, match="coordinator domain approval"):
        store.begin_integration(created["handoff_id"], "editorial-writer", "a" * 40, "a" * 40, True)
    with pytest.raises(HandoffError, match="not the delegated writer"):
        store.claim_worker(created["handoff_id"], "editorial-writer")

    claimed = store.coordinator_claim(created["handoff_id"], "editorial-coordinator")
    assert store.coordinator_claim(created["handoff_id"], "editorial-coordinator") == claimed
    with pytest.raises(HandoffError, match="another coordinator"):
        store.coordinator_claim(created["handoff_id"], "wrong-coordinator")
    delegated = store.delegate_child(
        created["handoff_id"], "editorial-coordinator", "editorial-writer", delegation_for(created),
    )
    assert delegated["orchestration"]["delegation"]["selected_skills"] == ["copywriting", "seo-strategy"]
    assert delegated["orchestration"]["delegation"]["research_branches"] == 3
    assert store.delegate_child(
        created["handoff_id"], "editorial-coordinator", "editorial-writer", delegation_for(created),
    ) == delegated
    with pytest.raises(HandoffError, match="wrong coordinator"):
        store.delegate_child(created["handoff_id"], "wrong-coordinator", "editorial-writer", delegation_for(created))

    started = store.claim_worker(created["handoff_id"], "editorial-writer")
    assert started["orchestration"]["lifecycle"]["stage"] == "worker_in_progress"
    with pytest.raises(HandoffError, match="another developer|delegated writer"):
        store.claim_worker(created["handoff_id"], "wrong-writer")
    submitted = store.worker_submit(created["handoff_id"], "editorial-writer", worker_evidence())
    assert store.worker_submit(created["handoff_id"], "editorial-writer", worker_evidence()) == submitted
    with pytest.raises(HandoffError, match="wrong coordinator"):
        store.coordinator_review(created["handoff_id"], "wrong-coordinator", "approve", ["domain QA passed"])
    approved = store.coordinator_review(
        created["handoff_id"], "editorial-coordinator", "approve", ["domain QA passed"],
    )
    assert approved["orchestration"]["lifecycle"]["stage"] == "domain_approved"
    assert store.coordinator_review(
        created["handoff_id"], "editorial-coordinator", "approve", ["domain QA passed"],
    ) == approved
    with pytest.raises(HandoffError, match="closed parent context pack"):
        store.strategy_complete(created["handoff_id"], "strategy", "pack-editorial-v1", "open", True)
    integration = store.begin_integration(created["handoff_id"], "editorial-writer", "a" * 40, "a" * 40, True)
    assert integration["orchestration"]["lifecycle"]["stage"] == "integrating"
    integrated = store.integration_result(
        created["handoff_id"], "editorial-writer", "3" * 40, "Integrated editorial result",
    )
    assert integrated["lifecycle"]["integration"]["status"] == "integrated"
    with pytest.raises(HandoffError, match="another pack"):
        store.strategy_complete(created["handoff_id"], "strategy", "wrong-pack", "closed", True)
    with pytest.raises(HandoffError, match="original context pack"):
        store.strategy_complete(created["handoff_id"], "strategy", "pack-editorial-v1", "closed", True)
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "UPDATE context_packs SET status='closed',closed_at='2026-09-02T00:00:00.000Z' WHERE id='pack-editorial-v1'",
        )
    completed = store.strategy_complete(
        created["handoff_id"], "strategy", "pack-editorial-v1", "closed", True,
    )
    assert completed["status"] == "completed"
    assert completed["lifecycle"]["commit_hash"] == "3" * 40
    assert store.strategy_complete(
        created["handoff_id"], "strategy", "pack-editorial-v1", "closed", True,
    ) == completed
    with pytest.raises(HandoffError, match="orchestration stage"):
        store.claim_worker(created["handoff_id"], "editorial-writer")


def test_orchestration_v1_rejects_invalid_delegation_and_preserves_rejected_attempt(tmp_path):
    store = HandoffStore(temporary_database(tmp_path))
    created = store.create_approved(orchestration_payload(tmp_path, "editorial-reject"))
    store.coordinator_claim(created["handoff_id"], "coordinator")
    incomplete = delegation_for(created)
    incomplete["child_card"].pop("acceptance")
    with pytest.raises(HandoffError, match="incomplete"):
        store.delegate_child(created["handoff_id"], "coordinator", "writer", incomplete)
    with pytest.raises(HandoffError, match="maximum delegation depth"):
        store.delegate_child(created["handoff_id"], "coordinator", "writer", delegation_for(created, delegation_depth=3))
    with pytest.raises(HandoffError, match="between zero and three"):
        store.delegate_child(created["handoff_id"], "coordinator", "writer", delegation_for(created, research_branches=4))
    with pytest.raises(HandoffError, match="unknown or disallowed skill"):
        store.delegate_child(created["handoff_id"], "coordinator", "writer", delegation_for(created, selected_skills=["auto-install-me"]))

    store.delegate_child(created["handoff_id"], "coordinator", "writer", delegation_for(created))
    store.claim_worker(created["handoff_id"], "writer")
    store.worker_submit(created["handoff_id"], "writer", worker_evidence("4" * 40))
    rejected = store.coordinator_review(created["handoff_id"], "coordinator", "reject", ["revise evidence"])
    assert rejected["orchestration"]["lifecycle"]["stage"] == "delegated"
    assert rejected["orchestration"]["attempts"][0]["review"]["decision"] == "reject"
    with pytest.raises(HandoffError, match="domain approval"):
        store.begin_integration(created["handoff_id"], "writer", "a" * 40, "a" * 40, True)
    store.worker_submit(created["handoff_id"], "writer", worker_evidence("5" * 40))
    approved = store.coordinator_review(created["handoff_id"], "coordinator", "approve", ["revision accepted"])
    assert approved["orchestration"]["lifecycle"]["stage"] == "domain_approved"
    with sqlite3.connect(store.path) as connection:
        actions = [row[0] for row in connection.execute(
            "SELECT title FROM audit_log WHERE entity_id=? ORDER BY created_at,id", (created["handoff_id"],),
        )]
    assert any("domain-reject" in item for item in actions)
    assert any("domain-approve" in item for item in actions)


def test_dispatcher_claims_once_records_thread_and_completes_idempotently(tmp_path):
    production_before = hashlib.sha256(MEMORY_DATABASE.read_bytes()).hexdigest()
    database = temporary_database(tmp_path)
    store = HandoffStore(database)
    created = store.create_approved(payload(idempotency_key="dispatcher-once-v1", semantic_key="architecture.dispatcher_once"))

    assert store.dispatcher_next()["task_id"] == created["task_id"]
    claimed = store.dispatcher_claim_next("dispatcher-a")
    assert claimed is not None
    assert claimed["task_id"] == created["task_id"]
    assert claimed["status"] == "dispatching"
    assert claimed["dispatch_payload"]["idempotency_key"] == "dispatcher-once-v1"
    assert store.dispatcher_claim_next("dispatcher-a") is None
    assert store.dispatcher_next() is None

    started = store.dispatcher_record_thread(created["handoff_id"], "01a00703-dispatcher-test", "dispatcher-a")
    assert started["status"] == "in_progress"
    assert started["lifecycle"]["executor_thread_id"] == "01a00703-dispatcher-test"
    assert store.dispatcher_record_thread(created["handoff_id"], "01a00703-dispatcher-test", "dispatcher-a") == started
    with pytest.raises(HandoffError, match="different executor thread"):
        store.dispatcher_record_thread(created["handoff_id"], "01a00703-other", "dispatcher-a")

    completed = store.dispatcher_complete(created["handoff_id"], "e" * 40, "Dispatcher test completed.", "dispatcher-a")
    assert completed["status"] == "completed"
    assert completed["lifecycle"]["commit_hash"] == "e" * 40
    assert completed["lifecycle"]["result"] == "Dispatcher test completed."
    assert store.dispatcher_complete(created["handoff_id"], "e" * 40, "Dispatcher test completed.", "dispatcher-a") == completed
    assert store.dispatcher_claim_next("dispatcher-a") is None
    assert hashlib.sha256(MEMORY_DATABASE.read_bytes()).hexdigest() == production_before


def test_focused_workflow_never_writes_working_database(tmp_path):
    before = hashlib.sha256(MEMORY_DATABASE.read_bytes()).hexdigest()
    database = temporary_database(tmp_path)
    HandoffStore(database).create_approved(payload())
    assert hashlib.sha256(MEMORY_DATABASE.read_bytes()).hexdigest() == before


def test_next_skips_malformed_legacy_handoff_metadata(tmp_path):
    database = temporary_database(tmp_path)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO tasks (id,type,title,content,data_json,status,author,access_level) VALUES ('60000000-0000-4000-a000-000000000001','standalone_task','Legacy','Legacy','{\"priority\":\"high\",\"handoff\":{\"kind\":\"codex_engineering\"}}','pending','owner','internal')"
        )
    assert HandoffStore(database).next() is None


def test_next_skips_broken_decision_linkage(tmp_path):
    database = temporary_database(tmp_path)
    valid = HandoffStore(database).create_approved(payload())
    with sqlite3.connect(database) as connection:
        broken = {
            "priority": "high",
            "handoff": {
                "kind": "codex_engineering",
                "goal": "Broken",
                "scope": ["Broken"],
                "constraints": ["Broken"],
                "acceptance": ["Broken"],
                "source": "Broken",
                "source_id": valid["decision"]["source_id"],
                "decision_candidate_id": valid["decision"]["candidate_id"],
                "decision_semantic_key": valid["decision"]["semantic_key"],
                "project_id": None,
            },
        }
        connection.execute(
            "INSERT INTO tasks (id,type,title,content,data_json,status,source_id,author,access_level) VALUES ('60000000-0000-4000-a000-000000000002','standalone_task','Broken','Broken',?,'pending',?,'owner','internal')",
            (json.dumps(broken), valid["decision"]["source_id"]),
        )
    assert HandoffStore(database).next()["task_id"] == valid["task_id"]


def test_next_skips_legacy_handoff_with_invalid_json_types(tmp_path):
    database = temporary_database(tmp_path)
    valid = HandoffStore(database).create_approved(payload())
    malformed = {
        "priority": [],
        "project_id": [],
        "handoff": {
            "kind": "codex_engineering",
            "goal": "Malformed",
            "scope": ["Malformed"],
            "constraints": ["Malformed"],
            "acceptance": ["Malformed"],
            "source": "Malformed",
            "source_id": valid["decision"]["source_id"],
            "decision_candidate_id": valid["decision"]["candidate_id"],
            "decision_semantic_key": valid["decision"]["semantic_key"],
            "project_id": [],
        },
    }
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO tasks (id,type,title,content,data_json,status,source_id,author,access_level) VALUES ('60000000-0000-4000-a000-000000000003','standalone_task','Malformed','Malformed',?,'pending',?,'owner','internal')",
            (json.dumps(malformed), valid["decision"]["source_id"]),
        )
    assert HandoffStore(database).next()["task_id"] == valid["task_id"]

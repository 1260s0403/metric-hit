from __future__ import annotations

import sqlite3
from datetime import timedelta
from uuid import uuid4

import pytest

from metrichit_os.editorial_models import (
    AddMaterialVersionInput,
    AddResearchItemInput,
    CompleteNoPublishInput,
    CreateMaterialInput,
    CreateRunInput,
    PreparePublicationJobInput,
    RecordApprovalDecisionInput,
    RequestApprovalInput,
)
from metrichit_os.editorial_store import (
    IdempotencyConflictError,
    InvalidTransitionError,
    WorkflowError,
    initialize_workflow_database,
)

from workflow_helpers import digest, make_workflow


def test_complete_path_prepares_job_without_publishing(tmp_path):
    fixture = make_workflow(tmp_path)
    state = fixture.reach_content_approved()
    scheduled = fixture.now + timedelta(hours=1)
    expires = scheduled + timedelta(minutes=10)
    publish_approval = fixture.service.request_approval(RequestApprovalInput(
        idempotency_key="publish-approval-1", run_id=state["run"]["id"], scope="publish",
        material_version_id=state["version"]["id"], subject_hash=digest("version-1"),
        platform="telegram", target="test-channel", scheduled_at=scheduled, expires_at=expires,
    ))
    fixture.service.record_approval_decision(RecordApprovalDecisionInput(
        idempotency_key="publish-decision-1", run_id=state["run"]["id"],
        approval_id=publish_approval["id"], decision="approved", actor_id="owner",
    ))
    job = fixture.service.prepare_publication_job(PreparePublicationJobInput(
        idempotency_key="job-1", run_id=state["run"]["id"], approval_id=publish_approval["id"],
        material_version_id=state["version"]["id"], content_sha256=digest("version-1"),
        platform="telegram", target="test-channel", scheduled_at=scheduled,
    ))

    assert job["status"] == "scheduled"
    assert job["network_action"] is False
    run = fixture.service.show_run(state["run"]["id"])
    assert run["run"]["workflow_stage"] == "publishing"
    assert run["counts"]["publication_jobs"] == 1
    assert fixture.service.next_actions(state["run"]["id"])["actions"] == ["await_external_publication"]
    trail = fixture.service.audit_trail(state["run"]["id"])
    assert trail["chain_valid"] is True
    assert trail["events"][-1]["event_type"] == "publication_job.prepared"
    with sqlite3.connect(fixture.database_path) as database:
        assert database.execute("SELECT count(*) FROM approvals").fetchone()[0] == 3
        assert database.execute("SELECT count(*) FROM publication_jobs WHERE status='published'").fetchone()[0] == 0


def test_no_publish_is_successful_terminal_outcome(tmp_path):
    fixture = make_workflow(tmp_path)
    run = fixture.create_run()
    result = fixture.service.complete_no_publish(CompleteNoPublishInput(
        idempotency_key="no-publish-1", run_id=run["id"], reason="No strong topic",
    ))
    assert result["status"] == "no_publish"
    assert fixture.service.next_actions(run["id"])["actions"] == []


def test_service_rejects_operation_in_wrong_stage(tmp_path):
    fixture = make_workflow(tmp_path)
    run = fixture.create_run()
    with pytest.raises(InvalidTransitionError):
        fixture.service.create_material(CreateMaterialInput(
            idempotency_key="bad-material", run_id=run["id"], plan_item_id=str(uuid4()),
            kind="article", canonical_title="Too early",
        ))


def test_database_rejects_every_forbidden_stage_transition(tmp_path):
    fixture = make_workflow(tmp_path)
    allowed = {
        "research": {"planning", "terminal"},
        "planning": {"writing", "terminal"},
        "writing": {"review", "terminal"},
        "review": {"writing", "approval", "terminal"},
        "approval": {"writing", "publishing", "terminal"},
        "publishing": {"measurement", "terminal"},
        "measurement": {"terminal"},
        "terminal": set(),
    }
    stages = set(allowed)
    paths = {
        "research": [],
        "planning": ["planning"],
        "writing": ["planning", "writing"],
        "review": ["planning", "writing", "review"],
        "approval": ["planning", "writing", "review", "approval"],
        "publishing": ["planning", "writing", "review", "approval", "publishing"],
        "measurement": ["planning", "writing", "review", "approval", "publishing", "measurement"],
        "terminal": ["terminal"],
    }
    with sqlite3.connect(fixture.database_path) as database:
        database.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.IntegrityError):
            database.execute(
                """
                INSERT INTO editorial_runs
                  (id, business_date, timezone, mode, status, config_sha256, started_at, workflow_stage)
                VALUES (?, '2026-09-01', 'Europe/Moscow', 'simulation', 'running', ?, ?, 'publishing')
                """,
                (str(uuid4()), digest("invalid-start"), fixture.now.isoformat()),
            )
        database.rollback()
        for index, source in enumerate(sorted(stages)):
            run_id = str(uuid4())
            database.execute(
                """
                INSERT INTO editorial_runs
                  (id, business_date, timezone, mode, status, config_sha256, started_at, workflow_stage)
                VALUES (?, ?, 'Europe/Moscow', 'simulation', ?, ?, ?, ?)
                """,
                (
                    run_id, f"2026-08-{14 + index:02d}", "running", digest(run_id),
                    fixture.now.isoformat(), "research",
                ),
            )
            for stage in paths[source]:
                if stage == "terminal":
                    database.execute(
                        """
                        UPDATE editorial_runs
                        SET workflow_stage='terminal', status='completed', finished_at=?
                        WHERE id=?
                        """,
                        (fixture.now.isoformat(), run_id),
                    )
                else:
                    database.execute("UPDATE editorial_runs SET workflow_stage=? WHERE id=?", (stage, run_id))
            database.commit()
            for target in stages - {source}:
                if target in allowed[source]:
                    continue
                with pytest.raises(sqlite3.IntegrityError):
                    database.execute("UPDATE editorial_runs SET workflow_stage=? WHERE id=?", (target, run_id))
                database.rollback()


def test_database_rejects_inconsistent_run_status_and_timestamps(tmp_path):
    fixture = make_workflow(tmp_path)
    run = fixture.create_run()
    with sqlite3.connect(fixture.database_path) as database:
        for statement in (
            "UPDATE editorial_runs SET status='completed' WHERE id=?",
            "UPDATE editorial_runs SET finished_at='2026-08-14T12:00:00Z' WHERE id=?",
            "UPDATE editorial_runs SET started_at=NULL WHERE id=?",
            "UPDATE editorial_runs SET workflow_stage='terminal', status='completed' WHERE id=?",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                database.execute(statement, (run["id"],))
            database.rollback()
        database.execute("UPDATE editorial_runs SET status='needs_owner' WHERE id=?", (run["id"],))
        assert database.execute(
            "SELECT workflow_stage, status FROM editorial_runs WHERE id=?", (run["id"],)
        ).fetchone() == ("research", "needs_owner")


def test_approval_scopes_are_not_interchangeable(tmp_path):
    fixture = make_workflow(tmp_path)
    state = fixture.reach_content_approved()
    with pytest.raises(WorkflowError, match="exact active approval"):
        fixture.service.prepare_publication_job(PreparePublicationJobInput(
            idempotency_key="job-with-content-approval", run_id=state["run"]["id"],
            approval_id=state["content_approval"]["id"], material_version_id=state["version"]["id"],
            content_sha256=digest("version-1"), platform="telegram", target="test-channel",
            scheduled_at=fixture.now + timedelta(hours=1),
        ))


def test_stale_material_version_cannot_be_approved(tmp_path):
    fixture = make_workflow(tmp_path)
    state = fixture.reach_writing()
    material = fixture.service.create_material(CreateMaterialInput(
        idempotency_key="material", run_id=state["run"]["id"],
        plan_item_id=state["plan"]["plan_item_ids"][0], kind="article", canonical_title="Material",
    ))
    version_one = fixture.service.add_material_version(AddMaterialVersionInput(
        idempotency_key="v1", run_id=state["run"]["id"], material_id=material["id"],
        file_path="work/articles/drafts/test/v01.md", sha256=digest("v1"), created_by="service",
    ))
    approval = fixture.service.request_approval(RequestApprovalInput(
        idempotency_key="approve-v1", run_id=state["run"]["id"], scope="content",
        material_version_id=version_one["id"], subject_hash=digest("v1"),
    ))
    fixture.service.add_material_version(AddMaterialVersionInput(
        idempotency_key="v2", run_id=state["run"]["id"], material_id=material["id"],
        file_path="work/articles/drafts/test/v02.md", sha256=digest("v2"), created_by="service",
    ))
    with pytest.raises(InvalidTransitionError):
        fixture.service.record_approval_decision(RecordApprovalDecisionInput(
            idempotency_key="decide-v1", run_id=state["run"]["id"], approval_id=approval["id"],
            decision="approved", actor_id="owner",
        ))


def test_idempotent_replay_returns_same_result_without_duplicates(tmp_path):
    fixture = make_workflow(tmp_path)
    request = CreateRunInput(
        idempotency_key="same-run", business_date="2026-08-14", timezone="Europe/Moscow",
        mode="simulation", config_sha256=digest("config"),
    )
    first = fixture.service.create_run(request)
    second = fixture.service.create_run(request)
    assert second["id"] == first["id"]
    assert second["idempotent_replay"] is True
    with sqlite3.connect(fixture.database_path) as database:
        assert database.execute("SELECT count(*) FROM editorial_runs").fetchone()[0] == 1
        assert database.execute("SELECT count(*) FROM audit_events").fetchone()[0] == 1


def test_conflicting_idempotency_payload_is_rejected(tmp_path):
    fixture = make_workflow(tmp_path)
    fixture.create_run(key="conflict")
    with pytest.raises(IdempotencyConflictError):
        fixture.service.create_run(CreateRunInput(
            idempotency_key="conflict", business_date="2026-08-15", timezone="Europe/Moscow",
            mode="simulation", config_sha256=digest("different"),
        ))


def test_failed_operation_rolls_back_idempotency_and_audit(tmp_path):
    fixture = make_workflow(tmp_path)
    run = fixture.create_run()
    before = fixture.service.audit_trail(run["id"])
    with pytest.raises(WorkflowError):
        fixture.service.add_research_item(AddResearchItemInput(
            idempotency_key="will-rollback", run_id=run["id"], source_id=str(uuid4()),
            canonical_url="https://example.com/missing", content_sha256=digest("missing"),
            received_at=fixture.now, expires_at=fixture.now + timedelta(days=1),
            source_class="primary", reliability="high",
        ))
    with sqlite3.connect(fixture.database_path) as database:
        assert database.execute("SELECT count(*) FROM idempotency_keys WHERE key_value='will-rollback'").fetchone()[0] == 0
        assert database.execute("SELECT count(*) FROM research_items").fetchone()[0] == 0
    assert fixture.service.audit_trail(run["id"])["events"] == before["events"]


def test_transaction_rolls_back_partial_writes(tmp_path):
    fixture = make_workflow(tmp_path)

    def failing_operation(connection, _key_id):
        connection.execute(
            """
            INSERT INTO research_sources
              (id, host, path_prefix, transport, source_class, reliability)
            VALUES (?, 'rollback.example', '/', 'https', 'primary', 'high')
            """,
            (str(uuid4()),),
        )
        raise WorkflowError("forced rollback")

    with pytest.raises(WorkflowError, match="forced rollback"):
        fixture.service.store.idempotent_write(
            "test.rollback", "partial-write", {"value": 1}, failing_operation
        )
    with sqlite3.connect(fixture.database_path) as database:
        assert database.execute("SELECT count(*) FROM research_sources WHERE host='rollback.example'").fetchone()[0] == 0
        assert database.execute("SELECT count(*) FROM idempotency_keys WHERE key_value='partial-write'").fetchone()[0] == 0


def test_material_versions_and_audit_are_append_only(tmp_path):
    fixture = make_workflow(tmp_path)
    state = fixture.reach_content_approved()
    with sqlite3.connect(fixture.database_path) as database:
        for statement, identifier in (
            ("UPDATE material_versions SET status='approved' WHERE id=?", state["version"]["id"]),
            ("DELETE FROM material_versions WHERE id=?", state["version"]["id"]),
            ("UPDATE audit_events SET actor_id='other' WHERE run_id=?", state["run"]["id"]),
            ("DELETE FROM audit_events WHERE run_id=?", state["run"]["id"]),
        ):
            with pytest.raises(sqlite3.IntegrityError):
                database.execute(statement, (identifier,))
            database.rollback()


def test_approval_binding_and_terminal_decision_are_immutable(tmp_path):
    fixture = make_workflow(tmp_path)
    state = fixture.reach_content_approved()
    with sqlite3.connect(fixture.database_path) as database:
        for statement in (
            "UPDATE approvals SET target='changed' WHERE id=?",
            "UPDATE approvals SET status='rejected' WHERE id=?",
            "DELETE FROM approvals WHERE id=?",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                database.execute(statement, (state["content_approval"]["id"],))
            database.rollback()
        with pytest.raises(sqlite3.IntegrityError):
            database.execute(
                """
                INSERT INTO approvals
                  (id, material_version_id, scope, subject_hash, status, actor_id, decided_at)
                VALUES (?, ?, 'content', ?, 'approved', 'owner', '2026-08-14T12:00:00Z')
                """,
                (str(uuid4()), state["version"]["id"], digest("version-1")),
            )


def test_pending_approval_cannot_be_preloaded_with_decision_identity(tmp_path):
    fixture = make_workflow(tmp_path)
    state = fixture.reach_writing()
    with sqlite3.connect(fixture.database_path) as database:
        approval_id = str(uuid4())
        database.execute(
            """
            INSERT INTO approvals (id, plan_id, scope, subject_hash, status)
            VALUES (?, ?, 'plan', ?, 'pending')
            """,
            (approval_id, state["plan"]["id"], state["plan"]["subject_hash"]),
        )
        database.commit()
        for statement in (
            "UPDATE approvals SET actor_id='forged' WHERE id=?",
            "UPDATE approvals SET decided_at='2026-08-14T12:00:00Z' WHERE id=?",
            "UPDATE approvals SET actor_id='forged', decided_at='2026-08-14T12:00:00Z' WHERE id=?",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                database.execute(statement, (approval_id,))
            database.rollback()


def test_database_rejects_noncanonical_publish_timestamps(tmp_path):
    fixture = make_workflow(tmp_path)
    state = fixture.reach_content_approved()
    with sqlite3.connect(fixture.database_path) as database:
        database.execute("PRAGMA foreign_keys=ON")
        for scheduled_at, expires_at in (
            ("garbage", "zzzz"),
            ("2026-08-14T12:00:00Z", "2026-08-14T12:10:00Z"),
            ("2999-08-14T12:00:00.000Z", "2999-08-14T12:10:00.000Z"),
        ):
            with pytest.raises(sqlite3.IntegrityError):
                database.execute(
                    """
                    INSERT INTO approvals
                      (id, material_version_id, scope, subject_hash, platform, target,
                       scheduled_at, expires_at, status)
                    VALUES (?, ?, 'publish', ?, 'telegram', 'test-channel', ?, ?, 'pending')
                    """,
                    (
                        str(uuid4()), state["version"]["id"], digest("version-1"),
                        scheduled_at, expires_at,
                    ),
                )
            database.rollback()


def test_expired_publish_approval_is_closed_before_replacement(tmp_path):
    fixture = make_workflow(tmp_path)
    state = fixture.reach_content_approved()
    scheduled = fixture.now + timedelta(hours=1)
    first = fixture.service.request_approval(RequestApprovalInput(
        idempotency_key="publish-expiring", run_id=state["run"]["id"], scope="publish",
        material_version_id=state["version"]["id"], subject_hash=digest("version-1"),
        platform="telegram", target="test-channel", scheduled_at=scheduled,
        expires_at=fixture.now + timedelta(minutes=15),
    ))
    later = fixture.now + timedelta(minutes=20)
    fixture.service.store.clock = lambda: later
    replacement = fixture.service.request_approval(RequestApprovalInput(
        idempotency_key="publish-replacement", run_id=state["run"]["id"], scope="publish",
        material_version_id=state["version"]["id"], subject_hash=digest("version-1"),
        platform="telegram", target="test-channel", scheduled_at=scheduled,
        expires_at=scheduled + timedelta(minutes=10),
    ))
    assert replacement["id"] != first["id"]
    with sqlite3.connect(fixture.database_path) as database:
        assert database.execute("SELECT status FROM approvals WHERE id=?", (first["id"],)).fetchone()[0] == "expired"
        assert database.execute("SELECT status FROM approvals WHERE id=?", (replacement["id"],)).fetchone()[0] == "pending"


def test_cross_run_approval_cannot_be_decided_or_published(tmp_path):
    fixture = make_workflow(tmp_path)
    state = fixture.reach_content_approved()
    other = fixture.service.create_run(CreateRunInput(
        idempotency_key="other-run", business_date="2026-08-15", timezone="Europe/Moscow",
        mode="simulation", config_sha256=digest("other"),
    ))
    with pytest.raises(WorkflowError, match="does not belong"):
        fixture.service.record_approval_decision(RecordApprovalDecisionInput(
            idempotency_key="cross-run-decision", run_id=other["id"],
            approval_id=state["content_approval"]["id"], decision="approved", actor_id="owner",
        ))


def test_publication_execution_states_are_disabled(tmp_path):
    fixture = make_workflow(tmp_path)
    state = fixture.reach_content_approved()
    scheduled = fixture.now + timedelta(hours=1)
    approval = fixture.service.request_approval(RequestApprovalInput(
        idempotency_key="publish-request", run_id=state["run"]["id"], scope="publish",
        material_version_id=state["version"]["id"], subject_hash=digest("version-1"),
        platform="telegram", target="test-channel", scheduled_at=scheduled,
        expires_at=scheduled + timedelta(minutes=10),
    ))
    fixture.service.record_approval_decision(RecordApprovalDecisionInput(
        idempotency_key="publish-approved", run_id=state["run"]["id"],
        approval_id=approval["id"], decision="approved", actor_id="owner",
    ))
    job = fixture.service.prepare_publication_job(PreparePublicationJobInput(
        idempotency_key="prepared-job", run_id=state["run"]["id"], approval_id=approval["id"],
        material_version_id=state["version"]["id"], content_sha256=digest("version-1"),
        platform="telegram", target="test-channel", scheduled_at=scheduled,
    ))
    with sqlite3.connect(fixture.database_path) as database:
        for status in ("processing", "would_publish", "published", "failed", "uncertain"):
            with pytest.raises(sqlite3.IntegrityError):
                database.execute("UPDATE publication_jobs SET status=? WHERE id=?", (status, job["id"]))
            database.rollback()
        with pytest.raises(sqlite3.IntegrityError):
            database.execute("DELETE FROM publication_jobs WHERE id=?", (job["id"],))
        second_key = str(uuid4())
        database.execute(
            """
            INSERT INTO idempotency_keys (id, scope, key_value, status, request_sha256)
            VALUES (?, 'test', ?, 'consumed', ?)
            """,
            (second_key, second_key, digest("second-job")),
        )
        with pytest.raises(sqlite3.IntegrityError):
            database.execute(
                """
                INSERT INTO publication_jobs
                  (id, approval_id, material_version_id, idempotency_key_id, content_sha256,
                   platform, target, scheduled_at, status)
                SELECT ?, approval_id, material_version_id, ?, content_sha256,
                       platform, target, scheduled_at, status
                FROM publication_jobs WHERE id=?
                """,
                (str(uuid4()), second_key, job["id"]),
            )


def test_publication_job_without_exact_approval_is_rejected_by_database(tmp_path):
    fixture = make_workflow(tmp_path)
    state = fixture.reach_content_approved()
    with sqlite3.connect(fixture.database_path) as database:
        key_id = str(uuid4())
        database.execute(
            "INSERT INTO idempotency_keys (id, scope, key_value, status, request_sha256) VALUES (?, 'test', ?, 'consumed', ?)",
            (key_id, key_id, digest("request")),
        )
        with pytest.raises(sqlite3.IntegrityError):
            database.execute(
                """
                INSERT INTO publication_jobs
                  (id, approval_id, material_version_id, idempotency_key_id, content_sha256,
                   platform, target, scheduled_at, status)
                VALUES (?, ?, ?, ?, ?, 'telegram', 'test-channel', ?, 'scheduled')
                """,
                (
                    str(uuid4()), state["content_approval"]["id"], state["version"]["id"],
                    key_id, digest("version-1"), (fixture.now + timedelta(hours=1)).isoformat(),
                ),
            )


def test_migrations_are_repeatable(tmp_path):
    database_path = tmp_path / "repeat.sqlite"
    first = initialize_workflow_database(database_path)
    second = initialize_workflow_database(database_path)
    assert first == {"migration_versions": [1, 2], "applied_now": [1, 2]}
    assert second == {"migration_versions": [1, 2], "applied_now": []}


def test_audit_chain_remains_valid_across_multiple_runs(tmp_path):
    fixture = make_workflow(tmp_path)
    first = fixture.create_run("run-a")
    second = fixture.service.create_run(CreateRunInput(
        idempotency_key="run-b", business_date="2026-08-15", timezone="Europe/Moscow",
        mode="simulation", config_sha256=digest("config-b"),
    ))
    assert fixture.service.audit_trail(first["id"])["chain_valid"] is True
    assert fixture.service.audit_trail(second["id"])["chain_valid"] is True

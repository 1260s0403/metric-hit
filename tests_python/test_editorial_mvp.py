from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import metrichit_os.editorial_mvp as editorial_mvp_module
import metrichit_os.editorial_store as editorial_store_module
from metrichit_os import cli
from metrichit_os.config import EDITORIAL_MIGRATIONS
from metrichit_os.editorial_models import (
    EditorialMvpRunInput,
    RecordApprovalDecisionInput,
    RecordMaterialReviewInput,
)
from metrichit_os.editorial_mvp import (
    MODEL_LUNA,
    MODEL_ROUTING,
    MODEL_TERRA,
    EditorialMvpOrchestrator,
    RateCard,
    prepare_mvp_database,
)
from metrichit_os.editorial_store import WorkingDatabaseWriteError
from metrichit_os.editorial_store import WorkflowError
from metrichit_os.editorial_workflow import EditorialWorkflowService
from metrichit_os.text_providers import (
    DeterministicFakeProvider,
    OpenAIProvider,
    ProviderConfigurationError,
    TextGenerationRequest,
)


class CountingFakeProvider(DeterministicFakeProvider):
    def __init__(self):
        self.calls = []

    def generate(self, request):
        self.calls.append((request.task, request.model))
        return super().generate(request)


def mvp_request(key="mvp-test"):
    return EditorialMvpRunInput(
        idempotency_key=key,
        topic="Как провести первый управляемый тест ПФ",
        primary_query="улучшение поведенческих факторов сайта",
        article_platform="workspace",
        account_id="metric-hit-main",
        provider="fake",
        simulation=True,
    )


def test_simulation_run_reaches_owner_approval_without_publication(tmp_path):
    database = tmp_path / "editorial.sqlite"
    provider = CountingFakeProvider()
    now = datetime(2026, 8, 14, 12, 0, 0, 123456, tzinfo=timezone.utc)
    orchestrator = EditorialMvpOrchestrator(
        database,
        provider=provider,
        artifact_root=tmp_path,
        clock=lambda: now,
    )
    result = orchestrator.run(mvp_request())

    assert result["status"] == "awaiting_owner_approval"
    assert result["workflow_stage"] == "review"
    assert result["publication_jobs"] == 0
    assert len(result["materials"]) == 3
    assert len(result["approvals"]) == 3
    assert {item["status"] for item in result["approvals"]} == {"pending"}
    assert MODEL_ROUTING == {
        "research": MODEL_LUNA,
        "topic": MODEL_LUNA,
        "plan": MODEL_TERRA,
        "article": MODEL_TERRA,
        "telegram": MODEL_LUNA,
        "vk": MODEL_LUNA,
        "review": MODEL_TERRA,
    }
    assert all("sol" not in model for model in MODEL_ROUTING.values())
    assert len(provider.calls) == 9

    for material in result["materials"]:
        path = tmp_path / material["file_path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == material["sha256"]
        filename = path.name
        assert "2026-08-14" in filename
        assert result["id"] in filename
        assert material["material_type"] in filename
        assert material["article_platform"] in filename

    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        counts = {
            "runs": connection.execute("SELECT count(*) FROM editorial_runs").fetchone()[0],
            "research": connection.execute("SELECT count(*) FROM research_items").fetchone()[0],
            "topics": connection.execute("SELECT count(*) FROM topic_proposals").fetchone()[0],
            "plans": connection.execute("SELECT count(*) FROM daily_plans").fetchone()[0],
            "materials": connection.execute("SELECT count(*) FROM materials").fetchone()[0],
            "versions": connection.execute("SELECT count(*) FROM material_versions").fetchone()[0],
            "pending_content": connection.execute(
                "SELECT count(*) FROM approvals WHERE scope='content' AND status='pending'"
            ).fetchone()[0],
            "jobs": connection.execute("SELECT count(*) FROM publication_jobs").fetchone()[0],
            "reviews": connection.execute(
                "SELECT count(*) FROM audit_events WHERE event_type='material.review.completed.v2'"
            ).fetchone()[0],
        }
        assert counts == {
            "runs": 1, "research": 1, "topics": 1, "plans": 1,
            "materials": 3, "versions": 3, "pending_content": 3,
            "jobs": 0, "reviews": 3,
        }
        review_rows = connection.execute(
            "SELECT entity_id, data_json FROM audit_events WHERE event_type='material.review.completed.v2'"
        ).fetchall()
        version_hashes = {
            row["id"]: row["sha256"]
            for row in connection.execute("SELECT id, sha256 FROM material_versions")
        }
        for row in review_rows:
            review_data = json.loads(row["data_json"])
            assert review_data["subject_hash"] == version_hashes[row["entity_id"]]
            assert review_data["reviewed_input_sha256"] == version_hashes[row["entity_id"]]
        generation_inputs = {
            json.loads(row[0])["input_sha256"]
            for row in connection.execute(
                "SELECT data_json FROM audit_events WHERE event_type='model.generation.completed' "
                "AND json_extract(data_json, '$.task')='review'"
            )
        }
        assert generation_inputs == set(version_hashes.values())
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT reviewed_at FROM research_sources").fetchone()[0].endswith(".123Z")


def test_review_generation_cannot_be_cross_bound_to_another_material(tmp_path):
    database = tmp_path / "editorial.sqlite"
    now = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)
    orchestrator = EditorialMvpOrchestrator(
        database, provider=CountingFakeProvider(), artifact_root=tmp_path, clock=lambda: now,
    )
    result = orchestrator.run(mvp_request("review-cross-binding"))
    target = result["materials"][0]
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        wrong = next(
            json.loads(row["data_json"])
            for row in connection.execute(
                "SELECT data_json FROM audit_events WHERE event_type='model.generation.completed' "
                "AND json_extract(data_json, '$.task')='review'"
            )
            if json.loads(row["data_json"])["input_sha256"] != target["sha256"]
        )
    with pytest.raises(WorkflowError, match="exact audited generation"):
        orchestrator.workflow.record_material_review(RecordMaterialReviewInput(
            idempotency_key="cross-bound-review",
            run_id=result["id"],
            material_version_id=target["version_id"],
            subject_hash=target["sha256"],
            review_sha256=wrong["text_sha256"],
            provider=wrong["provider"],
            model=wrong["model"],
            input_tokens=wrong["input_tokens"],
            output_tokens=wrong["output_tokens"],
            estimated_cost=wrong["estimated_cost"],
        ))


def test_owner_can_decide_three_content_approvals_sequentially(tmp_path):
    database = tmp_path / "editorial.sqlite"
    now = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)
    orchestrator = EditorialMvpOrchestrator(
        database, provider=CountingFakeProvider(), artifact_root=tmp_path, clock=lambda: now,
    )
    result = orchestrator.run(mvp_request("three-owner-decisions"))
    for index, approval in enumerate(result["approvals"], start=1):
        orchestrator.workflow.record_approval_decision(RecordApprovalDecisionInput(
            idempotency_key=f"owner-decision-{index}",
            run_id=result["id"],
            approval_id=approval["approval_id"],
            decision="approved",
            actor_id="owner",
        ))
        expected_stage = "approval" if index == 3 else "review"
        assert orchestrator.workflow.show_run(result["id"])["run"]["workflow_stage"] == expected_stage
    state = orchestrator.workflow.show_run(result["id"])
    assert state["counts"]["publication_jobs"] == 0
    assert state["run"]["status"] == "running"


def test_mixed_content_decisions_return_to_writing_after_last_decision(tmp_path):
    database = tmp_path / "editorial.sqlite"
    now = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)
    orchestrator = EditorialMvpOrchestrator(
        database, provider=CountingFakeProvider(), artifact_root=tmp_path, clock=lambda: now,
    )
    result = orchestrator.run(mvp_request("mixed-owner-decisions"))
    decisions = ("rejected", "approved", "approved")
    for index, (approval, decision) in enumerate(zip(result["approvals"], decisions), start=1):
        orchestrator.workflow.record_approval_decision(RecordApprovalDecisionInput(
            idempotency_key=f"mixed-owner-decision-{index}",
            run_id=result["id"],
            approval_id=approval["approval_id"],
            decision=decision,
            actor_id="owner",
        ))
    assert orchestrator.workflow.show_run(result["id"])["run"]["workflow_stage"] == "writing"


def test_repeated_mvp_run_is_idempotent_and_does_not_call_provider(tmp_path):
    database = tmp_path / "editorial.sqlite"
    provider = CountingFakeProvider()
    now = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)
    orchestrator = EditorialMvpOrchestrator(
        database,
        provider=provider,
        artifact_root=tmp_path,
        clock=lambda: now,
    )
    first = orchestrator.run(mvp_request("same-key"))
    calls_after_first = list(provider.calls)
    second = orchestrator.run(mvp_request("same-key"))

    assert second["id"] == first["id"]
    assert second["idempotent_replay"] is True
    assert provider.calls == calls_after_first
    assert second["usage"] == first["usage"]
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM editorial_runs").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM materials").fetchone()[0] == 3
        assert connection.execute("SELECT count(*) FROM publication_jobs").fetchone()[0] == 0


def test_replay_recalculates_usage_from_complete_generation_audit(tmp_path):
    database = tmp_path / "editorial.sqlite"
    provider = CountingFakeProvider()
    now = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)
    request = mvp_request("usage-recalculation")
    orchestrator = EditorialMvpOrchestrator(
        database, provider=provider, artifact_root=tmp_path, clock=lambda: now,
    )
    first = orchestrator.run(request)
    orchestrator._generate(
        request,
        first["id"],
        "review",
        "additional exact review input",
        "Account for this audited remediation generation.",
        generation_key="usage-remediation",
    )
    calls_before_replay = list(provider.calls)
    replay = orchestrator.run(request)

    assert replay["usage"]["input_tokens"] > first["usage"]["input_tokens"]
    assert replay["usage"]["output_tokens"] > first["usage"]["output_tokens"]
    assert provider.calls == calls_before_replay


def test_replay_refuses_to_overwrite_or_accept_changed_artifact(tmp_path):
    database = tmp_path / "editorial.sqlite"
    provider = CountingFakeProvider()
    now = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)
    orchestrator = EditorialMvpOrchestrator(
        database, provider=provider, artifact_root=tmp_path, clock=lambda: now,
    )
    first = orchestrator.run(mvp_request("changed-artifact"))
    artifact = tmp_path / first["materials"][0]["file_path"]
    artifact.write_text("changed outside orchestration", encoding="utf-8")
    with pytest.raises(WorkflowError, match="artifact hash"):
        orchestrator.run(mvp_request("changed-artifact"))


def test_fake_provider_is_deterministic_and_rate_card_is_configurable():
    provider = DeterministicFakeProvider()
    request = TextGenerationRequest(
        task="telegram", model=MODEL_LUNA, topic="Тема", primary_query="запрос",
        article_platform="workspace", account_id="main", input_text="input", instructions="instructions",
    )
    assert provider.generate(request) == provider.generate(request)
    rate_card = RateCard()
    assert rate_card.estimate("fake", MODEL_LUNA, 1000, 2000) == 0
    assert rate_card.estimate("openai", MODEL_LUNA, 1_000_000, 1_000_000) == 7.0


def test_openai_provider_requires_environment_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ProviderConfigurationError, match="OPENAI_API_KEY"):
        OpenAIProvider()


def test_openai_provider_uses_responses_api_and_reports_usage(monkeypatch):
    captured = {}

    class FakeResponses:
        def create(self, **arguments):
            captured.update(arguments)
            return SimpleNamespace(
                output_text="Generated text",
                usage=SimpleNamespace(input_tokens=11, output_tokens=7),
            )

    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-value")
    monkeypatch.setattr("openai.OpenAI", lambda: SimpleNamespace(responses=FakeResponses()))
    provider = OpenAIProvider()
    request = TextGenerationRequest(
        task="article", model=MODEL_TERRA, topic="Тема", primary_query="запрос",
        article_platform="workspace", account_id="main", input_text="input", instructions="instructions",
    )
    result = provider.generate(request)

    assert captured["model"] == MODEL_TERRA
    assert captured["instructions"] == "instructions"
    assert captured["store"] is False
    assert json.loads(captured["input"]) == {
        "task": "article",
        "topic": "Тема",
        "primary_query": "запрос",
        "article_platform": "workspace",
        "account_id": "main",
        "stage_input": "input",
    }
    assert result.provider == "openai"
    assert result.model == MODEL_TERRA
    assert result.input_tokens == 11
    assert result.output_tokens == 7
    assert result.text == "Generated text\n"


def test_working_database_requires_mvp_entrypoint_and_gets_rollback(monkeypatch, tmp_path):
    database = tmp_path / "editorial.sqlite"
    migration = EDITORIAL_MIGRATIONS / "001_editorial_foundation.sql"
    checksum = hashlib.sha256(migration.read_bytes()).hexdigest()
    with sqlite3.connect(database) as connection:
        connection.executescript(migration.read_text(encoding="utf-8"))
        connection.execute(
            "INSERT INTO schema_migrations(version, name, checksum) VALUES (1, ?, ?)",
            (migration.name, checksum),
        )

    rollback_directory = tmp_path / "backups" / "editorial-mvp-rollback"
    monkeypatch.setattr(editorial_mvp_module, "EDITORIAL_DATABASE", database)
    monkeypatch.setattr(editorial_mvp_module, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(editorial_mvp_module, "ROLLBACK_DIRECTORY", rollback_directory)
    monkeypatch.setattr(editorial_store_module, "EDITORIAL_DATABASE", database)

    with pytest.raises(WorkingDatabaseWriteError):
        EditorialWorkflowService(database)
    prepared = prepare_mvp_database(
        database,
        clock=lambda: datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc),
    )
    assert prepared.applied_now == (2,)
    assert prepared.rollback_path is not None
    rollback = tmp_path / prepared.rollback_path
    assert rollback.is_file()
    with sqlite3.connect(rollback) as connection:
        assert connection.execute("SELECT max(version) FROM schema_migrations").fetchone()[0] == 1
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT max(version) FROM schema_migrations").fetchone()[0] == 2
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_cli_exposes_one_explicit_mvp_entrypoint(monkeypatch, tmp_path, capsys):
    captured = {}

    def fake_run(database_path, request):
        captured["database"] = database_path
        captured["request"] = request
        return {"status": "awaiting_owner_approval"}

    monkeypatch.setattr(cli, "run_editorial_mvp", fake_run)
    exit_code = cli.run_workflow_command([
        "editorial-mvp-run",
        "--db", str(tmp_path / "editorial.sqlite"),
        "--idempotency-key", "cli-mvp",
        "--topic", "Тема",
        "--primary-query", "запрос",
        "--article-platform", "workspace",
        "--account-id", "main",
        "--provider", "fake",
        "--simulation",
    ])
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {"status": "awaiting_owner_approval"}
    assert captured["request"].simulation is True
    assert captured["request"].provider == "fake"

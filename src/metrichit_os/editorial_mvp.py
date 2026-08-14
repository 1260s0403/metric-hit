from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from .config import EDITORIAL_DATABASE, REPOSITORY_ROOT, repository_path
from .database import read_only_database, sha256_file
from .editorial_models import (
    AddMaterialVersionInput,
    AddResearchItemInput,
    AddResearchSourceInput,
    CreateDailyPlanInput,
    CreateMaterialInput,
    CreateRunInput,
    CreateTopicProposalInput,
    EditorialMvpRunInput,
    PlanItemInput,
    RecordApprovalDecisionInput,
    RecordMaterialReviewInput,
    RequestApprovalInput,
)
from .editorial_store import (
    _WORKING_EDITORIAL_MVP_CAPABILITY,
    EditorialStore,
    WorkflowError,
    canonical_json,
    initialize_workflow_database,
    migration_manifest,
    payload_sha256,
    utc_now,
    utc_text,
)
from .editorial_workflow import EditorialWorkflowService
from .text_providers import (
    TextGenerationProvider,
    TextGenerationRequest,
    create_provider,
)


RATE_CARD_PATH = repository_path("config", "editorial-rate-card.json")
ROLLBACK_DIRECTORY = repository_path("backups", "editorial-mvp-rollback")
MODEL_LUNA = "gpt-5.6-luna"
MODEL_TERRA = "gpt-5.6-terra"
MODEL_ROUTING = {
    "research": MODEL_LUNA,
    "topic": MODEL_LUNA,
    "plan": MODEL_TERRA,
    "article": MODEL_TERRA,
    "telegram": MODEL_LUNA,
    "vk": MODEL_LUNA,
    "review": MODEL_TERRA,
}


@dataclass(frozen=True)
class PreparedDatabase:
    path: Path
    migration_versions: tuple[int, ...]
    applied_now: tuple[int, ...]
    rollback_path: str | None


class RateCard:
    def __init__(self, path: Path = RATE_CARD_PATH):
        self.path = path.resolve()
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.currency = str(data["currency"])
        self.rates = data["per_million_tokens"]
        self.sha256 = sha256_file(self.path)

    def estimate(self, provider: str, model: str, input_tokens: int, output_tokens: int) -> float:
        try:
            rate = self.rates[provider][model]
        except KeyError as error:
            raise WorkflowError(f"Rate card does not define {provider}:{model}") from error
        value = (input_tokens * float(rate["input"]) + output_tokens * float(rate["output"])) / 1_000_000
        return round(value, 8)


def _database_migrations(path: Path) -> list[tuple[int, str, str]]:
    with read_only_database(path) as connection:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise WorkflowError("Editorial database integrity_check failed")
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_keys:
            raise WorkflowError("Editorial database foreign_key_check failed")
        return [tuple(row) for row in connection.execute(
            "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
        )]


def _create_rollback_copy(path: Path, clock=utc_now) -> str:
    ROLLBACK_DIRECTORY.mkdir(parents=True, exist_ok=True)
    family_hashes = []
    for suffix in ("", "-wal", "-shm"):
        member = path.with_name(path.name + suffix)
        if member.exists():
            family_hashes.append(f"{suffix}:{sha256_file(member)}")
    source_fingerprint = hashlib.sha256("\n".join(family_hashes).encode("utf-8")).hexdigest()
    filename = f"{clock().date().isoformat()}-pre-migration-002-{source_fingerprint[:12]}.sqlite"
    destination = (ROLLBACK_DIRECTORY / filename).resolve()
    if not destination.is_relative_to(ROLLBACK_DIRECTORY):
        raise WorkflowError("Rollback path escaped its repository directory")
    if destination.exists():
        with read_only_database(destination) as connection:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise WorkflowError("Existing rollback copy is not valid")
        return destination.relative_to(REPOSITORY_ROOT).as_posix()

    temporary = destination.with_name(destination.name + f".{uuid4().hex}.tmp")
    source_uri = f"file:{quote(path.as_posix(), safe='/:')}?mode=ro"
    try:
        source = sqlite3.connect(source_uri, uri=True)
        target = sqlite3.connect(temporary)
        try:
            source.execute("PRAGMA query_only=ON")
            source.backup(target)
            target.commit()
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise WorkflowError("Rollback copy integrity_check failed")
        finally:
            target.close()
            source.close()
        os.replace(temporary, destination)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise
    return destination.relative_to(REPOSITORY_ROOT).as_posix()


def prepare_mvp_database(path: Path, *, clock=utc_now) -> PreparedDatabase:
    resolved = path.resolve()
    working = resolved == EDITORIAL_DATABASE.resolve()
    if not resolved.exists():
        if working:
            raise WorkflowError("Working editorial database does not exist")
        result = initialize_workflow_database(resolved)
        return PreparedDatabase(resolved, tuple(result["migration_versions"]), tuple(result["applied_now"]), None)

    applied = _database_migrations(resolved)
    expected = migration_manifest()
    if applied not in (expected[:1], expected):
        raise WorkflowError("Editorial database migration history does not match migration 001–002")
    rollback_path = None
    if working and applied == expected[:1]:
        rollback_path = _create_rollback_copy(resolved, clock=clock)
    result = initialize_workflow_database(
        resolved,
        capability=_WORKING_EDITORIAL_MVP_CAPABILITY if working else None,
    )
    _database_migrations(resolved)
    return PreparedDatabase(
        resolved,
        tuple(result["migration_versions"]),
        tuple(result["applied_now"]),
        rollback_path,
    )


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or f"platform-{hashlib.sha256(value.encode('utf-8')).hexdigest()[:8]}"


class EditorialMvpOrchestrator:
    def __init__(
        self,
        database_path: Path,
        *,
        provider: TextGenerationProvider,
        artifact_root: Path = REPOSITORY_ROOT,
        rate_card: RateCard | None = None,
        clock=utc_now,
    ):
        self.clock = clock
        self.provider = provider
        self.artifact_root = artifact_root.resolve()
        self.rate_card = rate_card or RateCard()
        prepared = prepare_mvp_database(database_path, clock=clock)
        self.prepared = prepared
        working = prepared.path == EDITORIAL_DATABASE.resolve()
        self.workflow = EditorialWorkflowService(
            prepared.path,
            clock=clock,
            capability=_WORKING_EDITORIAL_MVP_CAPABILITY if working else None,
        )

    def run(self, request: EditorialMvpRunInput) -> dict[str, object]:
        payload = request.model_dump(mode="json", exclude={"idempotency_key"})
        replay = self.workflow.store.idempotent_result("editorial.mvp.run", request.idempotency_key, payload)
        if replay:
            self._verify_replay(replay)
            self._ensure_exact_review_bindings(request, replay)
            replay["usage"] = self._usage_summary(str(replay["id"]))
            return replay

        now = self.clock()
        now = now.replace(microsecond=(now.microsecond // 1000) * 1000)
        business_date = now.date()
        config_hash = payload_sha256({
            "request": payload,
            "model_routing": MODEL_ROUTING,
            "rate_card_sha256": self.rate_card.sha256,
        })
        run = self.workflow.create_run(CreateRunInput(
            idempotency_key=f"{request.idempotency_key}:run",
            business_date=business_date,
            timezone="UTC",
            mode="simulation" if request.simulation else "manual",
            config_sha256=config_hash,
        ))
        run_id = str(run["id"])
        self._record_configuration(request, run_id)

        research_generation = self._generate(
            request, run_id, "research", request.topic,
            "Separate known product facts from editorial hypotheses. Do not browse or publish.",
        )
        source = self.workflow.add_research_source(AddResearchSourceInput(
            idempotency_key=f"{request.idempotency_key}:research-source",
            run_id=run_id,
            host=f"mvp-{run_id}.local",
            path_prefix="/research",
            transport="file",
            source_class="internal",
            reliability="high",
            reviewed_by=f"{research_generation['provider']}:{research_generation['model']}",
            reviewed_at=now,
        ))
        research_sha256 = hashlib.sha256(str(research_generation["text"]).encode("utf-8")).hexdigest()
        research = self.workflow.add_research_item(AddResearchItemInput(
            idempotency_key=f"{request.idempotency_key}:research-item",
            run_id=run_id,
            source_id=str(source["id"]),
            canonical_url=f"internal://editorial-mvp/{run_id}/research",
            content_sha256=research_sha256,
            title=f"MVP research: {request.topic}",
            author=f"{research_generation['provider']}:{research_generation['model']}",
            received_at=now,
            expires_at=now + timedelta(days=7),
            source_class="internal",
            reliability="high",
        ))

        topic_generation = self._generate(
            request, run_id, "topic", str(research_generation["text"]),
            "Assess the supplied topic for one article platform and one primary search intent.",
        )
        topic = self.workflow.create_topic_proposal(CreateTopicProposalInput(
            idempotency_key=f"{request.idempotency_key}:topic",
            run_id=run_id,
            research_item_id=str(research["id"]),
            topic=request.topic,
            platform=request.article_platform,
            format="article",
            score=90,
            rationale=str(topic_generation["text"]),
        ))

        plan_generation = self._generate(
            request, run_id, "plan", str(topic_generation["text"]),
            "Create a concise plan for an original article and independent Telegram and VK derivatives.",
        )
        plan = self.workflow.create_daily_plan(CreateDailyPlanInput(
            idempotency_key=f"{request.idempotency_key}:plan",
            run_id=run_id,
            business_date=business_date,
            version=1,
            estimated_cost=round(sum(float(item["estimated_cost"]) for item in (
                research_generation, topic_generation, plan_generation,
            )), 8),
            items=[PlanItemInput(topic_proposal_id=str(topic["id"]), decision="selected")],
        ))
        plan_approval = self.workflow.request_approval(RequestApprovalInput(
            idempotency_key=f"{request.idempotency_key}:plan-gate-request",
            run_id=run_id,
            scope="plan",
            plan_id=str(plan["id"]),
            subject_hash=str(plan["subject_hash"]),
        ))
        self.workflow.record_approval_decision(RecordApprovalDecisionInput(
            idempotency_key=f"{request.idempotency_key}:plan-gate-decision",
            run_id=run_id,
            approval_id=str(plan_approval["id"]),
            decision="approved",
            actor_id="editorial-mvp-plan-gate",
            actor_type="service",
        ))

        plan_item_id = str(plan["plan_item_ids"][0])
        material_specs = (
            ("article", "article", request.article_platform, f"{request.topic}"),
            ("telegram", "post", "telegram", f"Telegram: {request.topic}"),
            ("vk", "post", "vk", f"VK: {request.topic}"),
        )
        materials = []
        for material_type, kind, platform, title in material_specs:
            generated = self._generate(
                request,
                run_id,
                material_type,
                f"Research:\n{research_generation['text']}\n\nPlan:\n{plan_generation['text']}",
                self._material_instructions(material_type, platform),
            )
            relative_path = self._artifact_path(
                business_date.isoformat(), run_id, platform, material_type,
            )
            sha256 = self._write_artifact(relative_path, str(generated["text"]))
            material = self.workflow.create_material(CreateMaterialInput(
                idempotency_key=f"{request.idempotency_key}:material:{material_type}",
                run_id=run_id,
                plan_item_id=plan_item_id,
                kind=kind,
                canonical_title=title,
            ))
            version = self.workflow.add_material_version(AddMaterialVersionInput(
                idempotency_key=f"{request.idempotency_key}:version:{material_type}",
                run_id=run_id,
                material_id=str(material["id"]),
                file_path=relative_path,
                sha256=sha256,
                evidence_set_sha256=research_sha256,
                created_by=f"{generated['provider']}:{generated['model']}",
            ))
            materials.append({
                "material_type": material_type,
                "article_platform": platform,
                "account_id": request.account_id,
                "material_id": material["id"],
                "version_id": version["id"],
                "file_path": relative_path,
                "sha256": sha256,
                "provider": generated["provider"],
                "model": generated["model"],
            })
            self._record_material_binding(
                request,
                run_id,
                materials[-1],
            )

        approvals = []
        for material in materials:
            review = self._generate(
                request,
                run_id,
                "review",
                (self.artifact_root / str(material["file_path"])).read_text(encoding="utf-8"),
                f"Review the exact {material['material_type']} version. Do not approve or publish it.",
                generation_key=f"review:{material['material_type']}",
            )
            review_sha256 = hashlib.sha256(str(review["text"]).encode("utf-8")).hexdigest()
            review_record = self.workflow.record_material_review(RecordMaterialReviewInput(
                idempotency_key=f"{request.idempotency_key}:review-record:{material['material_type']}",
                run_id=run_id,
                material_version_id=str(material["version_id"]),
                subject_hash=str(material["sha256"]),
                review_sha256=review_sha256,
                provider=str(review["provider"]),
                model=str(review["model"]),
                input_tokens=int(review["input_tokens"]),
                output_tokens=int(review["output_tokens"]),
                estimated_cost=float(review["estimated_cost"]),
            ))
            approval = self.workflow.request_approval(RequestApprovalInput(
                idempotency_key=f"{request.idempotency_key}:content-approval:{material['material_type']}",
                run_id=run_id,
                scope="content",
                material_version_id=str(material["version_id"]),
                subject_hash=str(material["sha256"]),
            ))
            approvals.append({
                "material_type": material["material_type"],
                "approval_id": approval["id"],
                "status": approval["status"],
                "review": review_record,
            })

        state = self.workflow.show_run(run_id)
        if state["run"]["workflow_stage"] != "review" or state["counts"]["publication_jobs"] != 0:
            raise WorkflowError("MVP run did not stop safely in owner review without publication jobs")
        result = {
            "entity_type": "editorial_mvp_run",
            "id": run_id,
            "status": "awaiting_owner_approval",
            "workflow_stage": "review",
            "provider": request.provider,
            "model_routing": MODEL_ROUTING,
            "article_platform": request.article_platform,
            "account_id": request.account_id,
            "materials": materials,
            "approvals": approvals,
            "usage": self._usage_summary(run_id),
            "rollback_path": self.prepared.rollback_path,
            "migration_versions": list(self.prepared.migration_versions),
            "applied_now": list(self.prepared.applied_now),
            "publication_jobs": 0,
        }

        def finalize(connection, _key_id):
            self.workflow.store.audit(
                connection,
                run_id=run_id,
                actor_type="service",
                actor_id="editorial-mvp",
                event_type="mvp.awaiting_owner_approval",
                entity_type="editorial_run",
                entity_id=run_id,
                data={
                    "material_version_ids": [item["version_id"] for item in materials],
                    "approval_ids": [item["approval_id"] for item in approvals],
                    "publication_jobs": 0,
                },
            )
            return result

        return self.workflow.store.idempotent_write(
            "editorial.mvp.run", request.idempotency_key, payload, finalize,
        )

    def _record_configuration(self, request: EditorialMvpRunInput, run_id: str) -> None:
        payload = {
            "run_id": run_id,
            "provider": request.provider,
            "model_routing": MODEL_ROUTING,
            "article_platform": request.article_platform,
            "account_id": request.account_id,
            "material_types": ["article", "telegram", "vk"],
            "rate_card_sha256": self.rate_card.sha256,
        }

        def operation(connection, _key_id):
            self.workflow.store.audit(
                connection,
                run_id=run_id,
                actor_type="service",
                actor_id="editorial-mvp",
                event_type="mvp.configured",
                entity_type="editorial_run",
                entity_id=run_id,
                data=payload,
            )
            return {"entity_type": "editorial_run", "id": run_id, "status": "configured"}

        self.workflow.store.idempotent_write(
            "editorial.mvp.configure", f"{request.idempotency_key}:configure", payload, operation,
        )

    def _record_material_binding(
        self,
        request: EditorialMvpRunInput,
        run_id: str,
        material: dict[str, object],
    ) -> None:
        payload = {"run_id": run_id, **material}

        def operation(connection, _key_id):
            self.workflow.store.audit(
                connection,
                run_id=run_id,
                actor_type="service",
                actor_id="editorial-mvp",
                event_type="mvp.material.bound",
                entity_type="material_version",
                entity_id=str(material["version_id"]),
                data=material,
            )
            return {
                "entity_type": "material_version",
                "id": material["version_id"],
                "status": "bound",
            }

        self.workflow.store.idempotent_write(
            "editorial.mvp.material.bind",
            f"{request.idempotency_key}:material-bind:{material['material_type']}",
            payload,
            operation,
        )

    def _generate(
        self,
        request: EditorialMvpRunInput,
        run_id: str,
        task: str,
        input_text: str,
        instructions: str,
        *,
        generation_key: str | None = None,
    ) -> dict[str, object]:
        model = MODEL_ROUTING[task]
        key = f"{request.idempotency_key}:generation:{generation_key or task}"
        generation_payload = {
            "run_id": run_id,
            "task": task,
            "provider": request.provider,
            "model": model,
            "topic": request.topic,
            "primary_query": request.primary_query,
            "article_platform": request.article_platform,
            "account_id": request.account_id,
            "input_sha256": hashlib.sha256(input_text.encode("utf-8")).hexdigest(),
            "instructions_sha256": hashlib.sha256(instructions.encode("utf-8")).hexdigest(),
        }
        scope = f"editorial.mvp.generation.{task}"
        cached = self.workflow.store.reserve_idempotency(scope, key, generation_payload)
        if cached:
            return cached
        try:
            generated = self.provider.generate(TextGenerationRequest(
                task=task,
                model=model,
                topic=request.topic,
                primary_query=request.primary_query,
                article_platform=request.article_platform,
                account_id=request.account_id,
                input_text=input_text,
                instructions=instructions,
            ))
            if generated.provider != request.provider or generated.model != model:
                raise WorkflowError("Generation provider or model did not match the configured route")
            estimated_cost = self.rate_card.estimate(
                generated.provider, generated.model, generated.input_tokens, generated.output_tokens,
            )
            generation_id = str(uuid4())
            response = {
                "entity_type": "model_generation",
                "id": generation_id,
                "task": task,
                "provider": generated.provider,
                "model": generated.model,
                "text": generated.text,
                "text_sha256": hashlib.sha256(generated.text.encode("utf-8")).hexdigest(),
                "input_sha256": generation_payload["input_sha256"],
                "input_tokens": generated.input_tokens,
                "output_tokens": generated.output_tokens,
                "estimated_cost": estimated_cost,
                "currency": self.rate_card.currency,
            }

            def operation(connection):
                self.workflow.store.audit(
                    connection,
                    run_id=run_id,
                    actor_type="model",
                    actor_id=f"{generated.provider}:{generated.model}",
                    event_type="model.generation.completed",
                    entity_type="model_generation",
                    entity_id=generation_id,
                    data={key: value for key, value in response.items() if key != "text"},
                )

            return self.workflow.store.complete_reserved_idempotency(
                scope, key, generation_payload, response, operation,
            )
        except Exception:
            self.workflow.store.abandon_reserved_idempotency(scope, key, generation_payload)
            raise

    def _usage_summary(self, run_id: str) -> dict[str, object]:
        trail = self.workflow.audit_trail(run_id)
        generations = [
            event["data_json"]
            for event in trail["events"]
            if event["event_type"] == "model.generation.completed"
        ]
        return {
            "input_tokens": sum(int(item["input_tokens"]) for item in generations),
            "output_tokens": sum(int(item["output_tokens"]) for item in generations),
            "estimated_cost": round(sum(float(item["estimated_cost"]) for item in generations), 8),
            "currency": self.rate_card.currency,
        }

    def _artifact_path(self, business_date: str, run_id: str, platform: str, material_type: str) -> str:
        platform_slug = _safe_slug(platform)
        filename = f"{business_date}-{run_id}-{platform_slug}-{material_type}.md"
        if material_type == "article":
            return f"work/articles/drafts/{filename}"
        return f"work/social/{platform_slug}/drafts/{filename}"

    def _write_artifact(self, relative_path: str, text: str) -> str:
        destination = (self.artifact_root / relative_path).resolve()
        if not destination.is_relative_to(self.artifact_root):
            raise WorkflowError("Artifact path escaped its root")
        content = text if text.endswith("\n") else text + "\n"
        encoded = content.encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if destination.read_bytes() != encoded:
                raise WorkflowError(f"Refusing to overwrite an existing artifact: {relative_path}")
            return digest
        with destination.open("xb") as target:
            target.write(encoded)
        return digest

    def _verify_replay(self, replay: dict[str, object]) -> None:
        state = self.workflow.show_run(str(replay["id"]))
        if state["run"]["workflow_stage"] != "review" or state["counts"]["publication_jobs"] != 0:
            raise WorkflowError("Stored MVP result no longer has a safe owner-review state")
        for material in replay["materials"]:
            destination = (self.artifact_root / str(material["file_path"])).resolve()
            if not destination.is_relative_to(self.artifact_root) or not destination.is_file():
                raise WorkflowError("Stored MVP artifact is missing or outside its root")
            if sha256_file(destination) != material["sha256"]:
                raise WorkflowError("Stored MVP artifact hash no longer matches its immutable version")

    def _ensure_exact_review_bindings(
        self,
        request: EditorialMvpRunInput,
        replay: dict[str, object],
    ) -> None:
        run_id = str(replay["id"])
        for material in replay["materials"]:
            with self.workflow.store.read_connection() as connection:
                exact = connection.execute(
                    """
                    SELECT 1 FROM audit_events
                    WHERE run_id=? AND event_type='material.review.completed.v2'
                      AND entity_type='material_version' AND entity_id=?
                      AND json_extract(data_json, '$.subject_hash')=?
                      AND json_extract(data_json, '$.reviewed_input_sha256')=?
                    LIMIT 1
                    """,
                    (
                        run_id, material["version_id"], material["sha256"], material["sha256"],
                    ),
                ).fetchone()
            if exact:
                continue
            material_type = str(material["material_type"])
            text = (self.artifact_root / str(material["file_path"])).read_text(encoding="utf-8")
            review = self._generate(
                request,
                run_id,
                "review",
                text,
                f"Review the exact {material_type} version. Do not approve or publish it.",
                generation_key=f"review-v2:{material_type}",
            )
            review_sha256 = hashlib.sha256(str(review["text"]).encode("utf-8")).hexdigest()
            self.workflow.record_material_review(RecordMaterialReviewInput(
                idempotency_key=f"{request.idempotency_key}:review-record-v2:{material_type}",
                run_id=run_id,
                material_version_id=str(material["version_id"]),
                subject_hash=str(material["sha256"]),
                review_sha256=review_sha256,
                provider=str(review["provider"]),
                model=str(review["model"]),
                input_tokens=int(review["input_tokens"]),
                output_tokens=int(review["output_tokens"]),
                estimated_cost=float(review["estimated_cost"]),
            ))

    @staticmethod
    def _material_instructions(material_type: str, platform: str) -> str:
        if material_type == "article":
            return (
                f"Write one original Russian article for {platform}. Use one search intent and one CTA. "
                "Describe MetricHit directly as a service for PF manipulation and improvement in Yandex."
            )
        if material_type == "telegram":
            return "Write a concise standalone Russian Telegram post with its own practical angle and CTA."
        return "Write a standalone Russian VK post with a mini-audit angle and its own CTA."


def run_editorial_mvp(
    database_path: Path,
    request: EditorialMvpRunInput,
    *,
    provider: TextGenerationProvider | None = None,
    artifact_root: Path = REPOSITORY_ROOT,
) -> dict[str, object]:
    selected_provider = provider or create_provider(request.provider)
    orchestrator = EditorialMvpOrchestrator(
        database_path,
        provider=selected_provider,
        artifact_root=artifact_root,
    )
    return orchestrator.run(request)

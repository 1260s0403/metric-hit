from __future__ import annotations

import json
import sqlite3
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from .editorial_models import (
    AddMaterialVersionInput,
    AddResearchItemInput,
    AddResearchSourceInput,
    CompleteNoPublishInput,
    CreateDailyPlanInput,
    CreateMaterialInput,
    CreateRunInput,
    CreateTopicProposalInput,
    PreparePublicationJobInput,
    RecordApprovalDecisionInput,
    RecordMaterialReviewInput,
    RequestApprovalInput,
)
from .editorial_store import (
    EditorialStore,
    InvalidTransitionError,
    WorkflowError,
    canonical_json,
    payload_sha256,
    row_dict,
    utc_text,
)


class EditorialWorkflowService:
    def __init__(
        self,
        database_path: Path,
        *,
        clock=None,
        capability: object | None = None,
    ):
        arguments = {"capability": capability}
        if clock:
            arguments["clock"] = clock
        self.store = EditorialStore(database_path, **arguments)

    @staticmethod
    def _payload(model) -> dict[str, object]:
        return model.model_dump(mode="json", exclude={"idempotency_key"})

    @staticmethod
    def _run(connection: sqlite3.Connection, run_id: str) -> dict[str, object]:
        return row_dict(
            connection.execute("SELECT * FROM editorial_runs WHERE id=?", (run_id,)).fetchone(),
            "Editorial run does not exist",
        )

    @classmethod
    def _require_stage(cls, connection: sqlite3.Connection, run_id: str, *stages: str) -> dict[str, object]:
        run = cls._run(connection, run_id)
        if run["status"] != "running" or run["workflow_stage"] not in stages:
            expected = ", ".join(stages)
            raise InvalidTransitionError(
                f"Run stage {run['workflow_stage']} with status {run['status']} does not allow this operation; expected {expected}"
            )
        return run

    @staticmethod
    def _advance(
        connection: sqlite3.Connection,
        run_id: str,
        stage: str,
        *,
        status: str | None = None,
        finished_at: str | None = None,
    ) -> None:
        connection.execute(
            """
            UPDATE editorial_runs
            SET workflow_stage=?, status=coalesce(?, status), finished_at=coalesce(?, finished_at)
            WHERE id=?
            """,
            (stage, status, finished_at, run_id),
        )

    @staticmethod
    def _latest_version(connection: sqlite3.Connection, material_id: str) -> dict[str, object]:
        return row_dict(
            connection.execute(
                "SELECT * FROM material_versions WHERE material_id=? ORDER BY version DESC LIMIT 1",
                (material_id,),
            ).fetchone(),
            "Material has no versions",
        )

    @staticmethod
    def _material_for_version(connection: sqlite3.Connection, version_id: str) -> tuple[dict[str, object], dict[str, object]]:
        version = row_dict(
            connection.execute("SELECT * FROM material_versions WHERE id=?", (version_id,)).fetchone(),
            "Material version does not exist",
        )
        material = row_dict(
            connection.execute("SELECT * FROM materials WHERE id=?", (version["material_id"],)).fetchone(),
            "Material does not exist",
        )
        return material, version

    @staticmethod
    def _material_run_id(connection: sqlite3.Connection, material_id: str) -> str:
        row = connection.execute(
            """
            SELECT plan.run_id FROM materials AS material
            JOIN plan_items AS item ON item.id=material.plan_item_id
            JOIN daily_plans AS plan ON plan.id=item.plan_id
            WHERE material.id=?
            """,
            (material_id,),
        ).fetchone()
        if not row:
            raise WorkflowError("Material is not attached to an editorial run")
        return row["run_id"]

    @staticmethod
    def _approval_run_id(connection: sqlite3.Connection, approval_id: str) -> str:
        row = connection.execute(
            """
            SELECT coalesce(plan.run_id, material_plan.run_id) AS run_id
            FROM approvals AS approval
            LEFT JOIN daily_plans AS plan ON plan.id=approval.plan_id
            LEFT JOIN material_versions AS version ON version.id=approval.material_version_id
            LEFT JOIN materials AS material ON material.id=version.material_id
            LEFT JOIN plan_items AS item ON item.id=material.plan_item_id
            LEFT JOIN daily_plans AS material_plan ON material_plan.id=item.plan_id
            WHERE approval.id=?
            """,
            (approval_id,),
        ).fetchone()
        if not row or not row["run_id"]:
            raise WorkflowError("Approval is not attached to an editorial run")
        return row["run_id"]

    @staticmethod
    def _pending_content_approvals(connection: sqlite3.Connection, run_id: str) -> int:
        return int(connection.execute(
            """
            SELECT count(*)
            FROM approvals AS approval
            JOIN material_versions AS version ON version.id=approval.material_version_id
            JOIN materials AS material ON material.id=version.material_id
            JOIN plan_items AS item ON item.id=material.plan_item_id
            JOIN daily_plans AS plan ON plan.id=item.plan_id
            WHERE plan.run_id=? AND approval.scope='content' AND approval.status='pending'
            """,
            (run_id,),
        ).fetchone()[0])

    @staticmethod
    def _all_current_materials_content_approved(connection: sqlite3.Connection, run_id: str) -> bool:
        missing = connection.execute(
            """
            SELECT count(*)
            FROM materials AS material
            JOIN plan_items AS item ON item.id=material.plan_item_id
            JOIN daily_plans AS plan ON plan.id=item.plan_id
            WHERE plan.run_id=? AND NOT EXISTS (
                SELECT 1
                FROM material_versions AS version
                JOIN approvals AS approval ON approval.material_version_id=version.id
                WHERE version.material_id=material.id
                  AND version.id=(
                      SELECT latest.id FROM material_versions AS latest
                      WHERE latest.material_id=material.id
                      ORDER BY latest.version DESC LIMIT 1
                  )
                  AND approval.scope='content'
                  AND approval.status='approved'
                  AND approval.subject_hash=version.sha256
            )
            """,
            (run_id,),
        ).fetchone()[0]
        return int(missing) == 0

    @staticmethod
    def _plan_hash(connection: sqlite3.Connection, plan_id: str) -> str:
        plan = row_dict(
            connection.execute("SELECT * FROM daily_plans WHERE id=?", (plan_id,)).fetchone(),
            "Daily plan does not exist",
        )
        items = [dict(row) for row in connection.execute(
            """
            SELECT topic_proposal_id, topic, platform, format, score, rationale, decision
            FROM plan_items WHERE plan_id=? ORDER BY id
            """,
            (plan_id,),
        )]
        return payload_sha256({
            "run_id": plan["run_id"],
            "business_date": plan["business_date"],
            "version": plan["version"],
            "estimated_cost": plan["estimated_cost"],
            "items": items,
        })

    def create_run(self, request: CreateRunInput) -> dict[str, object]:
        payload = self._payload(request)

        def operation(connection, _key_id):
            run_id = str(uuid4())
            now = utc_text(self.store.clock())
            connection.execute(
                """
                INSERT INTO editorial_runs
                  (id, business_date, timezone, mode, status, config_sha256, started_at, workflow_stage)
                VALUES (?, ?, ?, ?, 'running', ?, ?, 'research')
                """,
                (run_id, request.business_date.isoformat(), request.timezone, request.mode, request.config_sha256, now),
            )
            self.store.audit(
                connection, run_id=run_id, actor_type="service", actor_id="editorial-workflow",
                event_type="run.created", entity_type="editorial_run", entity_id=run_id,
                data={"business_date": request.business_date.isoformat(), "mode": request.mode, "stage": "research"},
            )
            return {"entity_type": "editorial_run", "id": run_id, "status": "running", "workflow_stage": "research"}

        return self.store.idempotent_write("run.create", request.idempotency_key, payload, operation)

    def add_research_source(self, request: AddResearchSourceInput) -> dict[str, object]:
        payload = self._payload(request)

        def operation(connection, _key_id):
            self._require_stage(connection, request.run_id, "research")
            source_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO research_sources
                  (id, host, path_prefix, transport, source_class, reliability, relative_path, reviewed_by, reviewed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id, request.host, request.path_prefix, request.transport,
                    request.source_class, request.reliability, request.relative_path,
                    request.reviewed_by, utc_text(request.reviewed_at) if request.reviewed_at else None,
                ),
            )
            self.store.audit(
                connection, run_id=request.run_id, actor_type="service", actor_id="editorial-workflow",
                event_type="research_source.added", entity_type="research_source", entity_id=source_id,
                data={"host": request.host, "source_class": request.source_class, "reliability": request.reliability},
            )
            return {"entity_type": "research_source", "id": source_id, "status": "active"}

        return self.store.idempotent_write("research_source.add", request.idempotency_key, payload, operation)

    def add_research_item(self, request: AddResearchItemInput) -> dict[str, object]:
        payload = self._payload(request)

        def operation(connection, _key_id):
            self._require_stage(connection, request.run_id, "research")
            source = row_dict(
                connection.execute("SELECT * FROM research_sources WHERE id=?", (request.source_id,)).fetchone(),
                "Research source does not exist",
            )
            if source["source_class"] != request.source_class or source["reliability"] != request.reliability:
                raise WorkflowError("Research item classification must match its source")
            item_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO research_items
                  (id, source_id, canonical_url, content_sha256, title, author, published_at,
                   received_at, expires_at, language, source_class, reliability, status, relative_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id, request.source_id, request.canonical_url, request.content_sha256,
                    request.title, request.author,
                    utc_text(request.published_at) if request.published_at else None,
                    utc_text(request.received_at), utc_text(request.expires_at), request.language,
                    request.source_class, request.reliability, request.status, request.relative_path,
                ),
            )
            self.store.audit(
                connection, run_id=request.run_id, actor_type="service", actor_id="editorial-workflow",
                event_type="research_item.added", entity_type="research_item", entity_id=item_id,
                data={"source_id": request.source_id, "content_sha256": request.content_sha256, "status": request.status},
            )
            return {"entity_type": "research_item", "id": item_id, "status": request.status}

        return self.store.idempotent_write("research_item.add", request.idempotency_key, payload, operation)

    def create_topic_proposal(self, request: CreateTopicProposalInput) -> dict[str, object]:
        payload = self._payload(request)

        def operation(connection, _key_id):
            self._require_stage(connection, request.run_id, "research", "planning")
            if request.research_item_id:
                row_dict(
                    connection.execute("SELECT id FROM research_items WHERE id=?", (request.research_item_id,)).fetchone(),
                    "Research item does not exist",
                )
            proposal_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO topic_proposals
                  (id, run_id, research_item_id, topic, platform, format, score, rationale, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    proposal_id, request.run_id, request.research_item_id, request.topic,
                    request.platform, request.format, request.score, request.rationale, request.status,
                ),
            )
            run = self._run(connection, request.run_id)
            if run["workflow_stage"] == "research":
                self._advance(connection, request.run_id, "planning")
            self.store.audit(
                connection, run_id=request.run_id, actor_type="service", actor_id="editorial-workflow",
                event_type="topic_proposal.created", entity_type="topic_proposal", entity_id=proposal_id,
                data={"score": request.score, "status": request.status, "platform": request.platform},
            )
            return {"entity_type": "topic_proposal", "id": proposal_id, "status": request.status, "score": request.score}

        return self.store.idempotent_write("topic_proposal.create", request.idempotency_key, payload, operation)

    def create_daily_plan(self, request: CreateDailyPlanInput) -> dict[str, object]:
        payload = self._payload(request)

        def operation(connection, _key_id):
            run = self._require_stage(connection, request.run_id, "planning")
            if run["business_date"] != request.business_date.isoformat():
                raise WorkflowError("Plan business date must match its run")
            plan_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO daily_plans (id, run_id, business_date, version, status, estimated_cost)
                VALUES (?, ?, ?, ?, 'proposed', ?)
                """,
                (plan_id, request.run_id, request.business_date.isoformat(), request.version, request.estimated_cost),
            )
            plan_item_ids = []
            for item in request.items:
                proposal = row_dict(
                    connection.execute(
                        "SELECT * FROM topic_proposals WHERE id=? AND run_id=?",
                        (item.topic_proposal_id, request.run_id),
                    ).fetchone(),
                    "Topic proposal does not belong to this run",
                )
                item_id = str(uuid4())
                connection.execute(
                    """
                    INSERT INTO plan_items
                      (id, plan_id, topic_proposal_id, topic, platform, format, score, rationale, decision)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item_id, plan_id, proposal["id"], proposal["topic"], proposal["platform"],
                        proposal["format"], proposal["score"], proposal["rationale"], item.decision,
                    ),
                )
                connection.execute("UPDATE topic_proposals SET status=? WHERE id=?", (
                    "selected" if item.decision == "selected" else item.decision,
                    proposal["id"],
                ))
                plan_item_ids.append(item_id)
            self.store.audit(
                connection, run_id=request.run_id, actor_type="service", actor_id="editorial-workflow",
                event_type="daily_plan.created", entity_type="daily_plan", entity_id=plan_id,
                data={"version": request.version, "plan_item_ids": plan_item_ids},
            )
            return {
                "entity_type": "daily_plan", "id": plan_id, "status": "proposed",
                "subject_hash": self._plan_hash(connection, plan_id), "plan_item_ids": plan_item_ids,
            }

        return self.store.idempotent_write("daily_plan.create", request.idempotency_key, payload, operation)

    def create_material(self, request: CreateMaterialInput) -> dict[str, object]:
        payload = self._payload(request)

        def operation(connection, _key_id):
            self._require_stage(connection, request.run_id, "writing")
            item = row_dict(connection.execute(
                """
                SELECT item.* FROM plan_items AS item
                JOIN daily_plans AS plan ON plan.id=item.plan_id
                WHERE item.id=? AND plan.run_id=? AND plan.status='approved' AND item.decision='selected'
                """,
                (request.plan_item_id, request.run_id),
            ).fetchone(), "Selected item from an approved plan is required")
            material_id = str(uuid4())
            connection.execute(
                "INSERT INTO materials (id, plan_item_id, kind, canonical_title, status) VALUES (?, ?, ?, ?, 'draft')",
                (material_id, item["id"], request.kind, request.canonical_title),
            )
            self.store.audit(
                connection, run_id=request.run_id, actor_type="service", actor_id="editorial-workflow",
                event_type="material.created", entity_type="material", entity_id=material_id,
                data={"plan_item_id": item["id"], "kind": request.kind},
            )
            return {"entity_type": "material", "id": material_id, "status": "draft"}

        return self.store.idempotent_write("material.create", request.idempotency_key, payload, operation)

    def add_material_version(self, request: AddMaterialVersionInput) -> dict[str, object]:
        payload = self._payload(request)

        def operation(connection, _key_id):
            run = self._require_stage(connection, request.run_id, "writing", "review", "approval")
            material = row_dict(connection.execute(
                """
                SELECT material.* FROM materials AS material
                JOIN plan_items AS item ON item.id=material.plan_item_id
                JOIN daily_plans AS plan ON plan.id=item.plan_id
                WHERE material.id=? AND plan.run_id=?
                """,
                (request.material_id, request.run_id),
            ).fetchone(), "Material does not belong to this run")
            latest = connection.execute(
                "SELECT max(version) AS version FROM material_versions WHERE material_id=?",
                (request.material_id,),
            ).fetchone()["version"]
            version_number = (latest or 0) + 1
            version_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO material_versions
                  (id, material_id, version, file_path, sha256, evidence_set_sha256, created_by, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'candidate')
                """,
                (
                    version_id, request.material_id, version_number, request.file_path,
                    request.sha256, request.evidence_set_sha256, request.created_by,
                ),
            )
            now = utc_text(self.store.clock())
            invalidated = [row["id"] for row in connection.execute(
                """
                SELECT id FROM approvals
                WHERE status='pending' AND material_version_id IN (
                  SELECT id FROM material_versions WHERE material_id=? AND id<>?
                )
                ORDER BY id
                """,
                (request.material_id, version_id),
            )]
            connection.execute(
                """
                UPDATE approvals SET status='cancelled', actor_id='system', decided_at=?
                WHERE status='pending' AND material_version_id IN (
                  SELECT id FROM material_versions WHERE material_id=? AND id<>?
                )
                """,
                (now, request.material_id, version_id),
            )
            for approval_id in invalidated:
                self.store.audit(
                    connection, run_id=request.run_id, actor_type="system", actor_id="editorial-workflow",
                    event_type="approval.cancelled_stale_version", entity_type="approval", entity_id=approval_id,
                    data={"replacement_version_id": version_id},
                )
            connection.execute("UPDATE materials SET status='draft' WHERE id=?", (material["id"],))
            if run["workflow_stage"] in {"review", "approval"}:
                self._advance(connection, request.run_id, "writing")
            self.store.audit(
                connection, run_id=request.run_id, actor_type="service", actor_id=request.created_by,
                event_type="material_version.created", entity_type="material_version", entity_id=version_id,
                data={"material_id": request.material_id, "version": version_number, "sha256": request.sha256},
            )
            return {
                "entity_type": "material_version", "id": version_id,
                "status": "candidate", "version": version_number,
            }

        return self.store.idempotent_write("material_version.add", request.idempotency_key, payload, operation)

    def request_approval(self, request: RequestApprovalInput) -> dict[str, object]:
        payload = self._payload(request)

        def operation(connection, _key_id):
            now = self.store.clock()
            if request.scope == "plan":
                self._require_stage(connection, request.run_id, "planning")
                plan = row_dict(connection.execute(
                    "SELECT * FROM daily_plans WHERE id=? AND run_id=? AND status='proposed'",
                    (request.plan_id, request.run_id),
                ).fetchone(), "Proposed plan does not belong to this run")
                if request.subject_hash != self._plan_hash(connection, plan["id"]):
                    raise WorkflowError("Plan approval hash does not match the exact plan")
            else:
                expected_stages = ("writing", "review") if request.scope == "content" else ("approval",)
                self._require_stage(connection, request.run_id, *expected_stages)
                material, version = self._material_for_version(connection, request.material_version_id)
                if self._material_run_id(connection, material["id"]) != request.run_id:
                    raise WorkflowError("Material version does not belong to this run")
                latest = self._latest_version(connection, material["id"])
                if latest["id"] != version["id"]:
                    raise WorkflowError("Cannot approve a stale material version")
                if version["sha256"] != request.subject_hash:
                    raise WorkflowError("Approval hash does not match the material version")
                if request.scope == "publish":
                    content_approval = connection.execute(
                        """
                        SELECT id FROM approvals
                        WHERE scope='content' AND status='approved' AND material_version_id=? AND subject_hash=?
                        ORDER BY decided_at DESC LIMIT 1
                        """,
                        (version["id"], version["sha256"]),
                    ).fetchone()
                    if not content_approval:
                        raise WorkflowError("Publish approval requires exact content approval")
                    if request.scheduled_at < now:
                        raise WorkflowError("scheduled_at must not be in the past")
                    if request.scheduled_at - now > timedelta(hours=4):
                        raise WorkflowError("Publish approval cannot be requested more than four hours early")
                    latest_expiry = min(now + timedelta(hours=4), request.scheduled_at + timedelta(minutes=15))
                    if request.expires_at <= now or request.expires_at > latest_expiry:
                        raise WorkflowError("Publish approval expiry exceeds the allowed window")
            duplicate = connection.execute(
                """
                SELECT id, expires_at FROM approvals
                WHERE scope=? AND status='pending' AND subject_hash=?
                  AND plan_id IS ? AND material_version_id IS ? AND target IS ?
                """,
                (request.scope, request.subject_hash, request.plan_id, request.material_version_id, request.target),
            ).fetchone()
            if (
                duplicate
                and request.scope == "publish"
                and duplicate["expires_at"]
                and utc_text(now) >= duplicate["expires_at"]
            ):
                decided_at = utc_text(now)
                connection.execute(
                    "UPDATE approvals SET status='expired', actor_id='system', decided_at=? WHERE id=?",
                    (decided_at, duplicate["id"]),
                )
                self.store.audit(
                    connection, run_id=request.run_id, actor_type="system", actor_id="editorial-workflow",
                    event_type="approval.publish.expired", entity_type="approval", entity_id=duplicate["id"],
                    data={"subject_hash": request.subject_hash, "target": request.target},
                )
                duplicate = None
            if duplicate:
                raise WorkflowError("An equivalent approval request is already pending")
            approval_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO approvals
                  (id, plan_id, material_version_id, scope, subject_hash, platform, target,
                   scheduled_at, expires_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                """,
                (
                    approval_id, request.plan_id, request.material_version_id, request.scope,
                    request.subject_hash, request.platform, request.target,
                    utc_text(request.scheduled_at) if request.scheduled_at else None,
                    utc_text(request.expires_at) if request.expires_at else None,
                ),
            )
            if request.scope == "content":
                connection.execute("UPDATE materials SET status='in_review' WHERE id=?", (material["id"],))
                run = self._run(connection, request.run_id)
                if run["workflow_stage"] == "writing":
                    self._advance(connection, request.run_id, "review")
            self.store.audit(
                connection, run_id=request.run_id, actor_type="service", actor_id="editorial-workflow",
                event_type=f"approval.{request.scope}.requested", entity_type="approval", entity_id=approval_id,
                data={
                    "scope": request.scope, "subject_hash": request.subject_hash,
                    "target": request.target, "platform": request.platform,
                },
            )
            return {"entity_type": "approval", "id": approval_id, "scope": request.scope, "status": "pending"}

        return self.store.idempotent_write(f"approval.{request.scope}.request", request.idempotency_key, payload, operation)

    def record_approval_decision(self, request: RecordApprovalDecisionInput) -> dict[str, object]:
        payload = self._payload(request)

        def operation(connection, _key_id):
            approval = row_dict(connection.execute(
                "SELECT * FROM approvals WHERE id=?", (request.approval_id,)
            ).fetchone(), "Approval does not exist")
            if self._approval_run_id(connection, approval["id"]) != request.run_id:
                raise WorkflowError("Approval does not belong to this run")
            if approval["status"] != "pending":
                raise InvalidTransitionError("Approval already has a terminal decision")
            now = self.store.clock()
            if approval["expires_at"] and utc_text(now) >= approval["expires_at"]:
                raise InvalidTransitionError("Approval has expired")
            scope = approval["scope"]
            run = self._run(connection, request.run_id)
            if request.actor_type == "service" and scope != "plan":
                raise WorkflowError("Service decisions are limited to the automated plan gate")
            if scope == "content":
                self._require_stage(connection, request.run_id, "review", "writing")
            else:
                required_stage = {"plan": "planning", "publish": "approval"}[scope]
                self._require_stage(connection, request.run_id, required_stage)
            material = None
            if scope == "plan":
                if approval["subject_hash"] != self._plan_hash(connection, approval["plan_id"]):
                    raise WorkflowError("Approval no longer matches the exact plan")
            else:
                material, version = self._material_for_version(connection, approval["material_version_id"])
                latest = self._latest_version(connection, material["id"])
                if latest["id"] != version["id"]:
                    raise WorkflowError("Cannot decide approval for a stale material version")
                if approval["subject_hash"] != version["sha256"]:
                    raise WorkflowError("Approval no longer matches the exact material hash")
                if scope == "publish":
                    content_approval = connection.execute(
                        """
                        SELECT id FROM approvals
                        WHERE scope='content' AND status='approved'
                          AND material_version_id=? AND subject_hash=?
                        LIMIT 1
                        """,
                        (version["id"], version["sha256"]),
                    ).fetchone()
                    if not content_approval:
                        raise WorkflowError("Publish approval no longer has exact content approval")
            decided_at = utc_text(now)
            connection.execute(
                "UPDATE approvals SET status=?, actor_id=?, decided_at=? WHERE id=?",
                (request.decision, request.actor_id, decided_at, approval["id"]),
            )
            if scope == "plan":
                if request.decision == "approved":
                    connection.execute("UPDATE daily_plans SET status='approved' WHERE id=?", (approval["plan_id"],))
                    self._advance(connection, request.run_id, "writing")
                else:
                    connection.execute("UPDATE daily_plans SET status='rejected' WHERE id=?", (approval["plan_id"],))
                    self._advance(connection, request.run_id, "terminal", status="no_publish", finished_at=decided_at)
            elif scope == "content":
                if request.decision == "approved":
                    connection.execute("UPDATE materials SET status='approved' WHERE id=?", (material["id"],))
                else:
                    connection.execute("UPDATE materials SET status='draft' WHERE id=?", (material["id"],))
                if self._pending_content_approvals(connection, request.run_id) == 0:
                    run = self._run(connection, request.run_id)
                    if self._all_current_materials_content_approved(connection, request.run_id):
                        if run["workflow_stage"] == "writing":
                            self._advance(connection, request.run_id, "review")
                        self._advance(connection, request.run_id, "approval")
                    elif run["workflow_stage"] == "review":
                        self._advance(connection, request.run_id, "writing")
            elif request.decision == "rejected":
                self._advance(connection, request.run_id, "terminal", status="no_publish", finished_at=decided_at)
            self.store.audit(
                connection, run_id=request.run_id, actor_type=request.actor_type, actor_id=request.actor_id,
                event_type=f"approval.{scope}.{request.decision}", entity_type="approval", entity_id=approval["id"],
                data={"scope": scope, "decision": request.decision, "subject_hash": approval["subject_hash"]},
            )
            return {"entity_type": "approval", "id": approval["id"], "scope": scope, "status": request.decision}

        return self.store.idempotent_write("approval.decision", request.idempotency_key, payload, operation)

    def record_material_review(self, request: RecordMaterialReviewInput) -> dict[str, object]:
        payload = self._payload(request)

        def operation(connection, _key_id):
            self._require_stage(connection, request.run_id, "writing", "review")
            material, version = self._material_for_version(connection, request.material_version_id)
            if self._material_run_id(connection, material["id"]) != request.run_id:
                raise WorkflowError("Material version does not belong to this run")
            latest = self._latest_version(connection, material["id"])
            if latest["id"] != version["id"] or version["sha256"] != request.subject_hash:
                raise WorkflowError("Review requires the exact current material version and hash")
            generation = connection.execute(
                """
                SELECT id FROM audit_events
                WHERE run_id=? AND event_type='model.generation.completed'
                  AND actor_id=?
                  AND json_extract(data_json, '$.task')='review'
                  AND json_extract(data_json, '$.input_sha256')=?
                  AND json_extract(data_json, '$.text_sha256')=?
                  AND json_extract(data_json, '$.input_tokens')=?
                  AND json_extract(data_json, '$.output_tokens')=?
                  AND json_extract(data_json, '$.estimated_cost')=?
                LIMIT 1
                """,
                (
                    request.run_id, f"{request.provider}:{request.model}", request.subject_hash,
                    request.review_sha256,
                    request.input_tokens, request.output_tokens, request.estimated_cost,
                ),
            ).fetchone()
            if not generation:
                raise WorkflowError("Review record requires the exact audited generation result")
            self.store.audit(
                connection,
                run_id=request.run_id,
                actor_type="model",
                actor_id=f"{request.provider}:{request.model}",
                event_type="material.review.completed.v2",
                entity_type="material_version",
                entity_id=version["id"],
                data={
                    "subject_hash": request.subject_hash,
                    "reviewed_input_sha256": request.subject_hash,
                    "review_sha256": request.review_sha256,
                    "provider": request.provider,
                    "model": request.model,
                    "usage": {
                        "input_tokens": request.input_tokens,
                        "output_tokens": request.output_tokens,
                    },
                    "estimated_cost": request.estimated_cost,
                },
            )
            return {
                "entity_type": "material_review",
                "id": version["id"],
                "material_version_id": version["id"],
                "subject_hash": request.subject_hash,
                "review_sha256": request.review_sha256,
                "status": "completed",
            }

        return self.store.idempotent_write("material.review", request.idempotency_key, payload, operation)

    def prepare_publication_job(self, request: PreparePublicationJobInput) -> dict[str, object]:
        payload = self._payload(request)

        def operation(connection, key_id):
            self._require_stage(connection, request.run_id, "approval")
            approval = row_dict(connection.execute(
                "SELECT * FROM approvals WHERE id=?", (request.approval_id,)
            ).fetchone(), "Publish approval does not exist")
            material, version = self._material_for_version(connection, request.material_version_id)
            if self._approval_run_id(connection, approval["id"]) != request.run_id:
                raise WorkflowError("Approval does not belong to this run")
            if self._material_run_id(connection, material["id"]) != request.run_id:
                raise WorkflowError("Material version does not belong to this run")
            latest = self._latest_version(connection, material["id"])
            scheduled_at = utc_text(request.scheduled_at)
            now = utc_text(self.store.clock())
            if not (
                approval["scope"] == "publish"
                and approval["status"] == "approved"
                and approval["material_version_id"] == version["id"]
                and approval["subject_hash"] == request.content_sha256 == version["sha256"]
                and approval["platform"] == request.platform
                and approval["target"] == request.target
                and approval["scheduled_at"] == scheduled_at
                and approval["expires_at"] > now
                and latest["id"] == version["id"]
            ):
                raise WorkflowError("Publication job requires exact active approval for the current version")
            job_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO publication_jobs
                  (id, approval_id, material_version_id, idempotency_key_id, content_sha256,
                   platform, target, scheduled_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'scheduled')
                """,
                (
                    job_id, approval["id"], version["id"], key_id, request.content_sha256,
                    request.platform, request.target, scheduled_at,
                ),
            )
            self._advance(connection, request.run_id, "publishing")
            self.store.audit(
                connection, run_id=request.run_id, actor_type="service", actor_id="editorial-workflow",
                event_type="publication_job.prepared", entity_type="publication_job", entity_id=job_id,
                data={
                    "approval_id": approval["id"], "content_sha256": request.content_sha256,
                    "platform": request.platform, "target": request.target,
                    "scheduled_at": scheduled_at, "network_action": False,
                },
            )
            return {
                "entity_type": "publication_job", "id": job_id, "status": "scheduled",
                "network_action": False,
            }

        return self.store.idempotent_write("publication_job.prepare", request.idempotency_key, payload, operation)

    def complete_no_publish(self, request: CompleteNoPublishInput) -> dict[str, object]:
        payload = self._payload(request)

        def operation(connection, _key_id):
            self._require_stage(connection, request.run_id, "research", "planning")
            finished_at = utc_text(self.store.clock())
            self._advance(
                connection, request.run_id, "terminal",
                status="no_publish", finished_at=finished_at,
            )
            self.store.audit(
                connection, run_id=request.run_id, actor_type="service", actor_id="editorial-workflow",
                event_type="run.no_publish", entity_type="editorial_run", entity_id=request.run_id,
                data={"reason": request.reason},
            )
            return {
                "entity_type": "editorial_run", "id": request.run_id,
                "status": "no_publish", "workflow_stage": "terminal",
            }

        return self.store.idempotent_write("run.no_publish", request.idempotency_key, payload, operation)

    def show_run(self, run_id: str) -> dict[str, object]:
        with self.store.read_connection() as connection:
            run = self._run(connection, run_id)
            counts = {
                "research_items": connection.execute(
                    "SELECT count(*) FROM audit_events WHERE run_id=? AND event_type='research_item.added'",
                    (run_id,),
                ).fetchone()[0],
                "topic_proposals": connection.execute(
                    "SELECT count(*) FROM topic_proposals WHERE run_id=?", (run_id,)
                ).fetchone()[0],
                "daily_plans": connection.execute(
                    "SELECT count(*) FROM daily_plans WHERE run_id=?", (run_id,)
                ).fetchone()[0],
                "materials": connection.execute(
                    """
                    SELECT count(*) FROM materials AS material
                    JOIN plan_items AS item ON item.id=material.plan_item_id
                    JOIN daily_plans AS plan ON plan.id=item.plan_id
                    WHERE plan.run_id=?
                    """, (run_id,),
                ).fetchone()[0],
                "approvals": connection.execute(
                    """
                    SELECT count(*) FROM approvals AS approval
                    LEFT JOIN daily_plans AS plan ON plan.id=approval.plan_id
                    LEFT JOIN material_versions AS version ON version.id=approval.material_version_id
                    LEFT JOIN materials AS material ON material.id=version.material_id
                    LEFT JOIN plan_items AS item ON item.id=material.plan_item_id
                    LEFT JOIN daily_plans AS material_plan ON material_plan.id=item.plan_id
                    WHERE plan.run_id=? OR material_plan.run_id=?
                    """, (run_id, run_id),
                ).fetchone()[0],
                "publication_jobs": connection.execute(
                    """
                    SELECT count(*) FROM publication_jobs AS job
                    JOIN material_versions AS version ON version.id=job.material_version_id
                    JOIN materials AS material ON material.id=version.material_id
                    JOIN plan_items AS item ON item.id=material.plan_item_id
                    JOIN daily_plans AS plan ON plan.id=item.plan_id
                    WHERE plan.run_id=?
                    """, (run_id,),
                ).fetchone()[0],
            }
            return {"run": run, "counts": counts, "next_actions": self._actions_for(run)}

    def next_actions(self, run_id: str) -> dict[str, object]:
        with self.store.read_connection() as connection:
            run = self._run(connection, run_id)
            return {
                "run_id": run_id,
                "status": run["status"],
                "workflow_stage": run["workflow_stage"],
                "actions": self._actions_for(run),
            }

    @staticmethod
    def _actions_for(run: dict[str, object]) -> list[str]:
        if run["status"] != "running":
            return []
        return {
            "research": ["add_research", "create_topic", "complete_no_publish"],
            "planning": ["create_topic", "create_plan", "request_plan_approval", "complete_no_publish"],
            "writing": ["create_material", "add_material_version", "request_content_approval"],
            "review": ["record_content_decision", "add_material_version"],
            "approval": ["request_publish_approval", "record_publish_decision", "add_material_version", "prepare_publication_job"],
            "publishing": ["await_external_publication"],
            "measurement": ["record_measurement"],
            "terminal": [],
        }[run["workflow_stage"]]

    def audit_trail(self, run_id: str) -> dict[str, object]:
        with self.store.read_connection() as connection:
            self._run(connection, run_id)
            rows = connection.execute(
                """
                SELECT event.*,
                       (SELECT previous.event_hash FROM audit_events AS previous
                        WHERE previous.rowid < event.rowid ORDER BY previous.rowid DESC LIMIT 1) AS chain_predecessor
                FROM audit_events AS event
                WHERE event.run_id=? ORDER BY event.rowid
                """,
                (run_id,),
            ).fetchall()
        events = []
        chain_valid = True
        for row in rows:
            data = json.loads(row["data_json"]) if row["data_json"] else None
            expected = payload_sha256({
                "id": row["id"], "run_id": row["run_id"], "actor_type": row["actor_type"],
                "actor_id": row["actor_id"], "event_type": row["event_type"],
                "entity_type": row["entity_type"], "entity_id": row["entity_id"],
                "data": data, "created_at": row["created_at"], "prev_hash": row["prev_hash"],
            })
            if row["prev_hash"] != row["chain_predecessor"] or row["event_hash"] != expected:
                chain_valid = False
            event = dict(row)
            event.pop("chain_predecessor")
            events.append({**event, "data_json": data})
        return {"run_id": run_id, "chain_valid": chain_valid, "events": events}

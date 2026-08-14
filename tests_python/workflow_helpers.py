from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from metrichit_os.editorial_models import (
    AddMaterialVersionInput,
    AddResearchItemInput,
    AddResearchSourceInput,
    CreateDailyPlanInput,
    CreateMaterialInput,
    CreateRunInput,
    CreateTopicProposalInput,
    PlanItemInput,
    RecordApprovalDecisionInput,
    RequestApprovalInput,
)
from metrichit_os.editorial_store import initialize_workflow_database
from metrichit_os.editorial_workflow import EditorialWorkflowService


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass
class WorkflowFixture:
    service: EditorialWorkflowService
    now: datetime
    database_path: object

    def create_run(self, key: str = "run-1"):
        return self.service.create_run(CreateRunInput(
            idempotency_key=key,
            business_date=date(2026, 8, 14),
            timezone="Europe/Moscow",
            mode="simulation",
            config_sha256=digest("config"),
        ))

    def reach_writing(self):
        run = self.create_run()
        source = self.service.add_research_source(AddResearchSourceInput(
            idempotency_key="source-1", run_id=run["id"], host="example.com",
            path_prefix="/research", source_class="primary", reliability="high",
        ))
        item = self.service.add_research_item(AddResearchItemInput(
            idempotency_key="research-1", run_id=run["id"], source_id=source["id"],
            canonical_url="https://example.com/research/item", content_sha256=digest("research"),
            title="Research", received_at=self.now, expires_at=self.now + timedelta(days=1),
            source_class="primary", reliability="high",
        ))
        topic = self.service.create_topic_proposal(CreateTopicProposalInput(
            idempotency_key="topic-1", run_id=run["id"], research_item_id=item["id"],
            topic="Test topic", platform="workspace", format="article", score=82,
            rationale="Strong evidence",
        ))
        plan = self.service.create_daily_plan(CreateDailyPlanInput(
            idempotency_key="plan-1", run_id=run["id"], business_date=date(2026, 8, 14),
            version=1, items=[PlanItemInput(topic_proposal_id=topic["id"])],
        ))
        approval = self.service.request_approval(RequestApprovalInput(
            idempotency_key="plan-approval-1", run_id=run["id"], scope="plan",
            plan_id=plan["id"], subject_hash=plan["subject_hash"],
        ))
        self.service.record_approval_decision(RecordApprovalDecisionInput(
            idempotency_key="plan-decision-1", run_id=run["id"], approval_id=approval["id"],
            decision="approved", actor_id="owner",
        ))
        return {"run": run, "source": source, "research": item, "topic": topic, "plan": plan}

    def reach_content_approved(self):
        state = self.reach_writing()
        material = self.service.create_material(CreateMaterialInput(
            idempotency_key="material-1", run_id=state["run"]["id"],
            plan_item_id=state["plan"]["plan_item_ids"][0], kind="article",
            canonical_title="Test material",
        ))
        version = self.service.add_material_version(AddMaterialVersionInput(
            idempotency_key="version-1", run_id=state["run"]["id"], material_id=material["id"],
            file_path="work/articles/drafts/test/v01.md", sha256=digest("version-1"),
            evidence_set_sha256=digest("evidence"), created_by="service",
        ))
        approval = self.service.request_approval(RequestApprovalInput(
            idempotency_key="content-approval-1", run_id=state["run"]["id"], scope="content",
            material_version_id=version["id"], subject_hash=digest("version-1"),
        ))
        self.service.record_approval_decision(RecordApprovalDecisionInput(
            idempotency_key="content-decision-1", run_id=state["run"]["id"],
            approval_id=approval["id"], decision="approved", actor_id="owner",
        ))
        return {**state, "material": material, "version": version, "content_approval": approval}


def make_workflow(tmp_path) -> WorkflowFixture:
    database_path = tmp_path / "editorial.sqlite"
    initialize_workflow_database(database_path)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    service = EditorialWorkflowService(database_path, clock=lambda: now)
    return WorkflowFixture(service=service, now=now, database_path=database_path)

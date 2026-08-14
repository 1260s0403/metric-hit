from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator


Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
IdempotencyKey = Annotated[str, StringConstraints(min_length=1, max_length=200, strip_whitespace=True)]
NonEmpty = Annotated[str, StringConstraints(min_length=1, max_length=500, strip_whitespace=True)]


class WorkflowInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: IdempotencyKey


def utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include a timezone")
    normalized = value.astimezone(timezone.utc)
    if normalized.microsecond % 1000:
        raise ValueError("datetime precision must not be finer than one millisecond")
    return normalized


class CreateRunInput(WorkflowInput):
    business_date: date
    timezone: NonEmpty
    mode: Literal["simulation", "manual"] = "simulation"
    config_sha256: Sha256


class AddResearchSourceInput(WorkflowInput):
    run_id: NonEmpty
    host: NonEmpty
    path_prefix: NonEmpty = "/"
    transport: Literal["https", "file"] = "https"
    source_class: Literal["official", "primary", "industry", "editorial", "internal"]
    reliability: Literal["high", "medium", "low", "unknown"]
    relative_path: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None

    _normalize_reviewed_at = field_validator("reviewed_at")(utc_datetime)

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        if "/" in value or "\\" in value or "@" in value:
            raise ValueError("host must not contain a path or credentials")
        return value.lower()

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_repository_relative_path(value)


class AddResearchItemInput(WorkflowInput):
    run_id: NonEmpty
    source_id: NonEmpty
    canonical_url: Annotated[str, StringConstraints(min_length=1, max_length=2048)]
    content_sha256: Sha256
    title: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    received_at: datetime
    expires_at: datetime
    language: Annotated[str, StringConstraints(min_length=2, max_length=16)] = "ru"
    source_class: Literal["official", "primary", "industry", "editorial", "internal"]
    reliability: Literal["high", "medium", "low", "unknown"]
    status: Literal["fresh", "stale", "expired", "rejected"] = "fresh"
    relative_path: str | None = None

    _normalize_published_at = field_validator("published_at")(utc_datetime)
    _normalize_received_at = field_validator("received_at")(utc_datetime)
    _normalize_expires_at = field_validator("expires_at")(utc_datetime)

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_repository_relative_path(value)

    @model_validator(mode="after")
    def validate_expiry(self):
        if self.expires_at <= self.received_at:
            raise ValueError("expires_at must be after received_at")
        return self


class CreateTopicProposalInput(WorkflowInput):
    run_id: NonEmpty
    research_item_id: str | None = None
    topic: NonEmpty
    platform: NonEmpty
    format: NonEmpty
    score: float = Field(ge=0, le=100)
    rationale: str | None = None
    status: Literal["proposed", "deferred", "rejected"] = "proposed"


class PlanItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic_proposal_id: NonEmpty
    decision: Literal["selected", "deferred", "rejected"] = "selected"


class CreateDailyPlanInput(WorkflowInput):
    run_id: NonEmpty
    business_date: date
    version: int = Field(ge=1)
    estimated_cost: float | None = Field(default=None, ge=0)
    items: list[PlanItemInput] = Field(min_length=1, max_length=3)


class CreateMaterialInput(WorkflowInput):
    run_id: NonEmpty
    plan_item_id: NonEmpty
    kind: Literal["article", "post", "card", "brief", "other"]
    canonical_title: NonEmpty


class AddMaterialVersionInput(WorkflowInput):
    run_id: NonEmpty
    material_id: NonEmpty
    file_path: NonEmpty
    sha256: Sha256
    evidence_set_sha256: Sha256 | None = None
    created_by: NonEmpty

    @field_validator("file_path")
    @classmethod
    def validate_file_path(cls, value: str) -> str:
        return validate_repository_relative_path(value)


class RequestApprovalInput(WorkflowInput):
    run_id: NonEmpty
    scope: Literal["plan", "content", "publish"]
    plan_id: str | None = None
    material_version_id: str | None = None
    subject_hash: Sha256
    platform: str | None = None
    target: str | None = None
    scheduled_at: datetime | None = None
    expires_at: datetime | None = None

    _normalize_scheduled_at = field_validator("scheduled_at")(utc_datetime)
    _normalize_expires_at = field_validator("expires_at")(utc_datetime)

    @model_validator(mode="after")
    def validate_subject(self):
        if self.scope == "plan" and (not self.plan_id or self.material_version_id):
            raise ValueError("plan approval requires only plan_id")
        if self.scope in {"content", "publish"} and (not self.material_version_id or self.plan_id):
            raise ValueError(f"{self.scope} approval requires only material_version_id")
        if self.scope == "publish" and (
            not self.platform or not self.target or not self.scheduled_at or not self.expires_at
        ):
            raise ValueError("publish approval requires platform, target, scheduled_at and expires_at")
        if self.scope != "publish" and any((self.platform, self.target, self.scheduled_at, self.expires_at)):
            raise ValueError("only publish approval accepts publication fields")
        return self


class RecordApprovalDecisionInput(WorkflowInput):
    run_id: NonEmpty
    approval_id: NonEmpty
    decision: Literal["approved", "rejected"]
    actor_id: NonEmpty
    actor_type: Literal["owner", "service"] = "owner"


class RecordMaterialReviewInput(WorkflowInput):
    run_id: NonEmpty
    material_version_id: NonEmpty
    subject_hash: Sha256
    review_sha256: Sha256
    provider: NonEmpty
    model: NonEmpty
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    estimated_cost: float = Field(ge=0)


class EditorialMvpRunInput(WorkflowInput):
    topic: NonEmpty
    primary_query: NonEmpty
    article_platform: NonEmpty
    account_id: NonEmpty
    provider: Literal["fake", "openai"]
    simulation: bool = False

    @model_validator(mode="after")
    def validate_simulation_provider(self):
        if self.simulation and self.provider != "fake":
            raise ValueError("simulation mode requires the deterministic fake provider")
        return self


class PreparePublicationJobInput(WorkflowInput):
    run_id: NonEmpty
    approval_id: NonEmpty
    material_version_id: NonEmpty
    content_sha256: Sha256
    platform: NonEmpty
    target: NonEmpty
    scheduled_at: datetime

    _normalize_scheduled_at = field_validator("scheduled_at")(utc_datetime)


class CompleteNoPublishInput(WorkflowInput):
    run_id: NonEmpty
    reason: NonEmpty


def validate_repository_relative_path(value: str) -> str:
    if "\\" in value or ":" in value:
        raise ValueError("path must use a repository-relative POSIX form")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value.startswith("/"):
        raise ValueError("path must stay relative")
    return path.as_posix()

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from metrichit_os.editorial_models import (
    AddMaterialVersionInput,
    AddResearchItemInput,
    CreateMaterialInput,
    CreateRunInput,
    RequestApprovalInput,
)
from metrichit_os.editorial_store import InvalidTransitionError, WorkflowError

from workflow_helpers import digest, make_workflow


def test_models_require_utc_aware_datetimes():
    with pytest.raises(ValidationError, match="timezone"):
        AddResearchItemInput(
            idempotency_key="naive", run_id=str(uuid4()), source_id=str(uuid4()),
            canonical_url="https://example.com/item", content_sha256=digest("item"),
            received_at=datetime(2026, 8, 14, 10, 0),
            expires_at=datetime(2026, 8, 15, 10, 0),
            source_class="primary", reliability="high",
        )


def test_models_normalize_aware_datetimes_to_utc():
    value = AddResearchItemInput(
        idempotency_key="aware", run_id=str(uuid4()), source_id=str(uuid4()),
        canonical_url="https://example.com/item", content_sha256=digest("item"),
        received_at=datetime(2026, 8, 14, 15, 0, tzinfo=timezone(timedelta(hours=5))),
        expires_at=datetime(2026, 8, 15, 15, 0, tzinfo=timezone(timedelta(hours=5))),
        source_class="primary", reliability="high",
    )
    assert value.received_at.utcoffset() == timedelta(0)
    assert value.received_at.hour == 10


def test_models_reject_sub_millisecond_schedule_precision():
    with pytest.raises(ValidationError, match="millisecond"):
        RequestApprovalInput(
            idempotency_key="too-precise", run_id=str(uuid4()), scope="publish",
            material_version_id=str(uuid4()), subject_hash=digest("version"),
            platform="telegram", target="test-channel",
            scheduled_at=datetime(2026, 8, 14, 10, 0, 0, 1, tzinfo=timezone.utc),
            expires_at=datetime(2026, 8, 14, 11, 0, tzinfo=timezone.utc),
        )


def test_models_reject_absolute_or_traversing_paths():
    for path in ("C:/private/material.md", "../material.md", "/absolute/material.md", "work\\material.md"):
        with pytest.raises(ValidationError):
            AddMaterialVersionInput(
                idempotency_key=f"path-{path}", run_id=str(uuid4()), material_id=str(uuid4()),
                file_path=path, sha256=digest(path), created_by="service",
            )


def test_production_run_mode_is_not_enabled():
    with pytest.raises(ValidationError):
        CreateRunInput(
            idempotency_key="production", business_date="2026-08-14", timezone="Europe/Moscow",
            mode="production", config_sha256=digest("config"),
        )


def test_nonexistent_material_version_cannot_be_submitted(tmp_path):
    fixture = make_workflow(tmp_path)
    state = fixture.reach_writing()
    with pytest.raises(WorkflowError, match="does not exist"):
        fixture.service.request_approval(RequestApprovalInput(
            idempotency_key="missing-version", run_id=state["run"]["id"], scope="content",
            material_version_id=str(uuid4()), subject_hash=digest("missing"),
        ))


def test_publish_approval_cannot_replace_content_approval(tmp_path):
    fixture = make_workflow(tmp_path)
    state = fixture.reach_writing()
    material = fixture.service.create_material(CreateMaterialInput(
        idempotency_key="material", run_id=state["run"]["id"],
        plan_item_id=state["plan"]["plan_item_ids"][0], kind="article", canonical_title="Material",
    ))
    version = fixture.service.add_material_version(AddMaterialVersionInput(
        idempotency_key="version", run_id=state["run"]["id"], material_id=material["id"],
        file_path="work/articles/drafts/test/v01.md", sha256=digest("version"), created_by="service",
    ))
    with pytest.raises(InvalidTransitionError):
        fixture.service.request_approval(RequestApprovalInput(
            idempotency_key="publish-too-early", run_id=state["run"]["id"], scope="publish",
            material_version_id=version["id"], subject_hash=digest("version"),
            platform="telegram", target="test-channel",
            scheduled_at=fixture.now + timedelta(hours=1),
            expires_at=fixture.now + timedelta(hours=1, minutes=10),
        ))

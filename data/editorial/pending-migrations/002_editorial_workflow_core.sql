ALTER TABLE editorial_runs ADD COLUMN workflow_stage TEXT NOT NULL DEFAULT 'research'
    CHECK (workflow_stage IN ('research', 'planning', 'writing', 'review', 'approval', 'publishing', 'measurement', 'terminal'));

ALTER TABLE idempotency_keys ADD COLUMN request_sha256 TEXT
    CHECK (request_sha256 IS NULL OR (length(request_sha256) = 64 AND request_sha256 NOT GLOB '*[^0-9a-f]*'));
ALTER TABLE idempotency_keys ADD COLUMN result_entity_type TEXT;
ALTER TABLE idempotency_keys ADD COLUMN result_entity_id TEXT;
ALTER TABLE idempotency_keys ADD COLUMN response_json TEXT
    CHECK (response_json IS NULL OR json_valid(response_json));

ALTER TABLE approvals ADD COLUMN platform TEXT;
ALTER TABLE approvals ADD COLUMN scheduled_at TEXT;

CREATE UNIQUE INDEX publication_jobs_one_job_per_approval_idx
ON publication_jobs (approval_id);

CREATE TRIGGER editorial_runs_validate_insert
BEFORE INSERT ON editorial_runs
WHEN NEW.workflow_stage <> 'research'
  OR NEW.status <> 'running'
  OR NEW.started_at IS NULL
  OR NEW.finished_at IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'new editorial run must start as active research');
END;

CREATE TRIGGER editorial_runs_validate_workflow_transition
BEFORE UPDATE OF workflow_stage ON editorial_runs
WHEN NEW.workflow_stage <> OLD.workflow_stage
 AND NOT (
    (OLD.workflow_stage = 'research' AND NEW.workflow_stage IN ('planning', 'terminal')) OR
    (OLD.workflow_stage = 'planning' AND NEW.workflow_stage IN ('writing', 'terminal')) OR
    (OLD.workflow_stage = 'writing' AND NEW.workflow_stage IN ('review', 'terminal')) OR
    (OLD.workflow_stage = 'review' AND NEW.workflow_stage IN ('writing', 'approval', 'terminal')) OR
    (OLD.workflow_stage = 'approval' AND NEW.workflow_stage IN ('writing', 'publishing', 'terminal')) OR
    (OLD.workflow_stage = 'publishing' AND NEW.workflow_stage IN ('measurement', 'terminal')) OR
    (OLD.workflow_stage = 'measurement' AND NEW.workflow_stage = 'terminal')
 )
BEGIN
    SELECT RAISE(ABORT, 'invalid editorial workflow transition');
END;

CREATE TRIGGER editorial_runs_validate_state_binding
BEFORE UPDATE OF status, workflow_stage, started_at, finished_at ON editorial_runs
WHEN NEW.started_at IS NULL
  OR (NEW.workflow_stage <> 'terminal' AND (
      NEW.status NOT IN ('running', 'needs_owner') OR NEW.finished_at IS NOT NULL
  ))
  OR (NEW.workflow_stage = 'terminal' AND (
      NEW.status NOT IN ('completed', 'failed', 'no_publish', 'cancelled')
      OR NEW.finished_at IS NULL
  ))
BEGIN
    SELECT RAISE(ABORT, 'workflow stage, run status, and timestamps disagree');
END;

CREATE TRIGGER material_versions_prevent_update
BEFORE UPDATE ON material_versions
BEGIN
    SELECT RAISE(ABORT, 'material_versions are immutable');
END;

CREATE TRIGGER material_versions_prevent_delete
BEFORE DELETE ON material_versions
BEGIN
    SELECT RAISE(ABORT, 'material_versions are immutable');
END;

CREATE TRIGGER material_versions_require_candidate_insert
BEFORE INSERT ON material_versions
WHEN NEW.status <> 'candidate'
BEGIN
    SELECT RAISE(ABORT, 'new material version must be an immutable candidate');
END;

CREATE TRIGGER approvals_require_pending_insert
BEFORE INSERT ON approvals
WHEN NEW.status <> 'pending' OR NEW.actor_id IS NOT NULL OR NEW.decided_at IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'new approval must be pending without a decision');
END;

CREATE TRIGGER approvals_validate_scope_insert
BEFORE INSERT ON approvals
WHEN (NEW.scope = 'plan' AND (NEW.plan_id IS NULL OR NEW.material_version_id IS NOT NULL))
  OR (NEW.scope IN ('content', 'publish') AND (NEW.material_version_id IS NULL OR NEW.plan_id IS NOT NULL))
  OR (NEW.scope <> 'publish' AND (NEW.platform IS NOT NULL OR NEW.scheduled_at IS NOT NULL))
  OR (NEW.scope = 'publish' AND (NEW.platform IS NULL OR NEW.target IS NULL OR NEW.scheduled_at IS NULL OR NEW.expires_at IS NULL))
BEGIN
    SELECT RAISE(ABORT, 'approval subject does not match scope');
END;

CREATE TRIGGER approvals_require_current_material_version
BEFORE INSERT ON approvals
WHEN NEW.scope IN ('content', 'publish')
 AND NEW.material_version_id <> (
    SELECT latest.id
    FROM material_versions AS latest
    WHERE latest.material_id = (
        SELECT selected.material_id FROM material_versions AS selected WHERE selected.id = NEW.material_version_id
    )
    ORDER BY latest.version DESC
    LIMIT 1
 )
BEGIN
    SELECT RAISE(ABORT, 'approval requires the current material version');
END;

CREATE TRIGGER approvals_require_exact_material_hash
BEFORE INSERT ON approvals
WHEN NEW.scope IN ('content', 'publish')
 AND NEW.subject_hash <> (SELECT sha256 FROM material_versions WHERE id = NEW.material_version_id)
BEGIN
    SELECT RAISE(ABORT, 'approval hash does not match material version');
END;

CREATE TRIGGER approvals_require_content_approval_before_publish
BEFORE INSERT ON approvals
WHEN NEW.scope = 'publish'
 AND NOT EXISTS (
    SELECT 1 FROM approvals AS content_approval
    WHERE content_approval.scope = 'content'
      AND content_approval.status = 'approved'
      AND content_approval.material_version_id = NEW.material_version_id
      AND content_approval.subject_hash = NEW.subject_hash
 )
BEGIN
    SELECT RAISE(ABORT, 'publish approval requires exact content approval');
END;

CREATE TRIGGER approvals_validate_publish_timestamps
BEFORE INSERT ON approvals
WHEN NEW.scope = 'publish'
 AND (
    strftime('%Y-%m-%dT%H:%M:%fZ', NEW.scheduled_at) IS NOT NEW.scheduled_at
    OR strftime('%Y-%m-%dT%H:%M:%fZ', NEW.expires_at) IS NOT NEW.expires_at
    OR julianday(NEW.scheduled_at) < julianday('now')
    OR julianday(NEW.scheduled_at) > julianday('now', '+4 hours')
    OR julianday(NEW.expires_at) <= julianday('now')
    OR julianday(NEW.expires_at) > julianday('now', '+4 hours')
    OR julianday(NEW.expires_at) > julianday(NEW.scheduled_at, '+15 minutes')
 )
BEGIN
    SELECT RAISE(ABORT, 'publish approval timestamps must be canonical UTC and inside the approval window');
END;

CREATE TRIGGER approvals_validate_decision
BEFORE UPDATE OF status, actor_id, decided_at ON approvals
WHEN (OLD.status <> 'pending' AND NEW.status <> OLD.status)
  OR (OLD.status = 'pending' AND NEW.status NOT IN ('pending', 'approved', 'rejected', 'expired', 'cancelled'))
  OR (OLD.status = 'pending' AND NEW.status = 'pending' AND (NEW.actor_id IS NOT NULL OR NEW.decided_at IS NOT NULL))
  OR (OLD.status = 'pending' AND NEW.status <> 'pending' AND (
      NEW.actor_id IS NULL OR trim(NEW.actor_id) = '' OR NEW.decided_at IS NULL
      OR strftime('%Y-%m-%dT%H:%M:%fZ', NEW.decided_at) IS NOT NEW.decided_at
  ))
BEGIN
    SELECT RAISE(ABORT, 'invalid approval decision');
END;

CREATE TRIGGER approvals_protect_binding
BEFORE UPDATE ON approvals
WHEN NEW.id IS NOT OLD.id
  OR NEW.plan_id IS NOT OLD.plan_id
  OR NEW.material_version_id IS NOT OLD.material_version_id
  OR NEW.scope IS NOT OLD.scope
  OR NEW.subject_hash IS NOT OLD.subject_hash
  OR NEW.platform IS NOT OLD.platform
  OR NEW.target IS NOT OLD.target
  OR NEW.scheduled_at IS NOT OLD.scheduled_at
  OR NEW.expires_at IS NOT OLD.expires_at
  OR NEW.created_at IS NOT OLD.created_at
BEGIN
    SELECT RAISE(ABORT, 'approval binding is immutable');
END;

CREATE TRIGGER approvals_protect_terminal_decision
BEFORE UPDATE ON approvals
WHEN OLD.status <> 'pending'
 AND (
    NEW.status IS NOT OLD.status OR
    NEW.actor_id IS NOT OLD.actor_id OR
    NEW.decided_at IS NOT OLD.decided_at
 )
BEGIN
    SELECT RAISE(ABORT, 'approval decision is immutable');
END;

CREATE TRIGGER approvals_prevent_delete
BEFORE DELETE ON approvals
BEGIN
    SELECT RAISE(ABORT, 'approvals cannot be deleted');
END;

CREATE TRIGGER publication_jobs_require_exact_approval
BEFORE INSERT ON publication_jobs
WHEN NOT EXISTS (
    SELECT 1
    FROM approvals AS approval
    JOIN material_versions AS version ON version.id = NEW.material_version_id
    WHERE approval.id = NEW.approval_id
      AND approval.scope = 'publish'
      AND approval.status = 'approved'
      AND approval.material_version_id = NEW.material_version_id
      AND approval.subject_hash = NEW.content_sha256
      AND approval.subject_hash = version.sha256
      AND approval.platform = NEW.platform
      AND approval.target = NEW.target
      AND approval.scheduled_at IS NEW.scheduled_at
      AND (approval.expires_at IS NULL OR approval.expires_at > strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
      AND version.id = (
          SELECT latest.id FROM material_versions AS latest
          WHERE latest.material_id = version.material_id
          ORDER BY latest.version DESC LIMIT 1
      )
)
BEGIN
    SELECT RAISE(ABORT, 'publication job requires exact current publish approval');
END;

CREATE TRIGGER publication_jobs_require_prepared_state
BEFORE INSERT ON publication_jobs
WHEN NEW.status NOT IN ('pending', 'scheduled')
BEGIN
    SELECT RAISE(ABORT, 'publication job can only be prepared in this stage');
END;

CREATE TRIGGER publication_jobs_protect_binding
BEFORE UPDATE ON publication_jobs
WHEN NEW.id IS NOT OLD.id
  OR NEW.approval_id IS NOT OLD.approval_id
  OR NEW.material_version_id IS NOT OLD.material_version_id
  OR NEW.idempotency_key_id IS NOT OLD.idempotency_key_id
  OR NEW.content_sha256 IS NOT OLD.content_sha256
  OR NEW.platform IS NOT OLD.platform
  OR NEW.target IS NOT OLD.target
  OR NEW.scheduled_at IS NOT OLD.scheduled_at
  OR NEW.created_at IS NOT OLD.created_at
BEGIN
    SELECT RAISE(ABORT, 'publication job binding is immutable');
END;

CREATE TRIGGER publication_jobs_prevent_execution_state
BEFORE UPDATE OF status ON publication_jobs
WHEN NEW.status NOT IN ('pending', 'scheduled', 'cancelled')
BEGIN
    SELECT RAISE(ABORT, 'publication execution is disabled in this stage');
END;

CREATE TRIGGER publication_jobs_prevent_delete
BEFORE DELETE ON publication_jobs
BEGIN
    SELECT RAISE(ABORT, 'publication jobs cannot be deleted');
END;

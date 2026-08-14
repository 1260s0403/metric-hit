PRAGMA foreign_keys = ON;

CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    checksum TEXT NOT NULL CHECK (length(checksum) = 64 AND checksum NOT GLOB '*[^0-9a-f]*'),
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE TABLE editorial_runs (
    id TEXT PRIMARY KEY CHECK (length(id) = 36),
    business_date TEXT NOT NULL CHECK (business_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    timezone TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('simulation', 'manual', 'production')),
    status TEXT NOT NULL DEFAULT 'planned' CHECK (status IN ('planned', 'running', 'completed', 'failed', 'needs_owner', 'no_publish', 'cancelled')),
    config_sha256 TEXT NOT NULL CHECK (length(config_sha256) = 64 AND config_sha256 NOT GLOB '*[^0-9a-f]*'),
    started_at TEXT,
    finished_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (business_date, timezone, mode)
) STRICT;

CREATE TABLE research_sources (
    id TEXT PRIMARY KEY CHECK (length(id) = 36),
    host TEXT NOT NULL,
    path_prefix TEXT NOT NULL DEFAULT '/',
    transport TEXT NOT NULL DEFAULT 'https' CHECK (transport IN ('https', 'file')),
    source_class TEXT NOT NULL CHECK (source_class IN ('official', 'primary', 'industry', 'editorial', 'internal')),
    reliability TEXT NOT NULL CHECK (reliability IN ('high', 'medium', 'low', 'unknown')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled', 'archived')),
    relative_path TEXT CHECK (relative_path IS NULL OR (relative_path NOT LIKE '/%' AND relative_path NOT LIKE '\\%' AND relative_path NOT GLOB '[A-Za-z]:*' AND instr(relative_path, '..') = 0)),
    reviewed_by TEXT,
    reviewed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (host, path_prefix, transport)
) STRICT;

CREATE TABLE research_items (
    id TEXT PRIMARY KEY CHECK (length(id) = 36),
    source_id TEXT NOT NULL REFERENCES research_sources(id) ON DELETE RESTRICT,
    canonical_url TEXT NOT NULL,
    content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64 AND content_sha256 NOT GLOB '*[^0-9a-f]*'),
    title TEXT,
    author TEXT,
    published_at TEXT,
    received_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'ru',
    source_class TEXT NOT NULL CHECK (source_class IN ('official', 'primary', 'industry', 'editorial', 'internal')),
    reliability TEXT NOT NULL CHECK (reliability IN ('high', 'medium', 'low', 'unknown')),
    status TEXT NOT NULL DEFAULT 'fresh' CHECK (status IN ('fresh', 'stale', 'expired', 'rejected')),
    relative_path TEXT CHECK (relative_path IS NULL OR (relative_path NOT LIKE '/%' AND relative_path NOT LIKE '\\%' AND relative_path NOT GLOB '[A-Za-z]:*' AND instr(relative_path, '..') = 0)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (canonical_url, content_sha256)
) STRICT;

CREATE TABLE topic_proposals (
    id TEXT PRIMARY KEY CHECK (length(id) = 36),
    run_id TEXT REFERENCES editorial_runs(id) ON DELETE RESTRICT,
    research_item_id TEXT REFERENCES research_items(id) ON DELETE RESTRICT,
    topic TEXT NOT NULL,
    platform TEXT NOT NULL,
    format TEXT NOT NULL,
    score REAL,
    rationale TEXT,
    status TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'selected', 'rejected', 'deferred', 'archived')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE TABLE daily_plans (
    id TEXT PRIMARY KEY CHECK (length(id) = 36),
    run_id TEXT NOT NULL REFERENCES editorial_runs(id) ON DELETE RESTRICT,
    business_date TEXT NOT NULL CHECK (business_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    version INTEGER NOT NULL CHECK (version > 0),
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'proposed', 'approved', 'rejected', 'superseded', 'archived')),
    estimated_cost REAL CHECK (estimated_cost IS NULL OR estimated_cost >= 0),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (run_id, version)
) STRICT;

CREATE TABLE plan_items (
    id TEXT PRIMARY KEY CHECK (length(id) = 36),
    plan_id TEXT NOT NULL REFERENCES daily_plans(id) ON DELETE RESTRICT,
    topic_proposal_id TEXT REFERENCES topic_proposals(id) ON DELETE RESTRICT,
    topic TEXT NOT NULL,
    platform TEXT NOT NULL,
    format TEXT NOT NULL,
    score REAL,
    rationale TEXT,
    decision TEXT NOT NULL DEFAULT 'proposed' CHECK (decision IN ('proposed', 'selected', 'rejected', 'deferred', 'cancelled')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE TABLE materials (
    id TEXT PRIMARY KEY CHECK (length(id) = 36),
    plan_item_id TEXT NOT NULL REFERENCES plan_items(id) ON DELETE RESTRICT,
    kind TEXT NOT NULL CHECK (kind IN ('article', 'post', 'card', 'brief', 'other')),
    canonical_title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'in_review', 'approved', 'rejected', 'archived')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE TABLE material_versions (
    id TEXT PRIMARY KEY CHECK (length(id) = 36),
    material_id TEXT NOT NULL REFERENCES materials(id) ON DELETE RESTRICT,
    version INTEGER NOT NULL CHECK (version > 0),
    file_path TEXT NOT NULL CHECK (file_path NOT LIKE '/%' AND file_path NOT LIKE '\\%' AND file_path NOT GLOB '[A-Za-z]:*' AND instr(file_path, '..') = 0),
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
    evidence_set_sha256 TEXT CHECK (evidence_set_sha256 IS NULL OR (length(evidence_set_sha256) = 64 AND evidence_set_sha256 NOT GLOB '*[^0-9a-f]*')),
    created_by TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'candidate', 'approved', 'rejected', 'archived')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (material_id, version),
    UNIQUE (file_path, sha256)
) STRICT;

CREATE TABLE approvals (
    id TEXT PRIMARY KEY CHECK (length(id) = 36),
    plan_id TEXT REFERENCES daily_plans(id) ON DELETE RESTRICT,
    material_version_id TEXT REFERENCES material_versions(id) ON DELETE RESTRICT,
    scope TEXT NOT NULL CHECK (scope IN ('plan', 'content', 'publish', 'budget', 'strategy', 'memory', 'access')),
    subject_hash TEXT NOT NULL CHECK (length(subject_hash) = 64 AND subject_hash NOT GLOB '*[^0-9a-f]*'),
    target TEXT,
    expires_at TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected', 'expired', 'cancelled')),
    actor_id TEXT,
    decided_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK ((plan_id IS NOT NULL) != (material_version_id IS NOT NULL))
) STRICT;

CREATE TABLE idempotency_keys (
    id TEXT PRIMARY KEY CHECK (length(id) = 36),
    scope TEXT NOT NULL,
    key_value TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'consumed', 'expired', 'cancelled')),
    expires_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (scope, key_value)
) STRICT;

CREATE TABLE publication_jobs (
    id TEXT PRIMARY KEY CHECK (length(id) = 36),
    approval_id TEXT NOT NULL REFERENCES approvals(id) ON DELETE RESTRICT,
    material_version_id TEXT NOT NULL REFERENCES material_versions(id) ON DELETE RESTRICT,
    idempotency_key_id TEXT NOT NULL REFERENCES idempotency_keys(id) ON DELETE RESTRICT,
    content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64 AND content_sha256 NOT GLOB '*[^0-9a-f]*'),
    platform TEXT NOT NULL,
    target TEXT NOT NULL,
    scheduled_at TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'scheduled', 'processing', 'would_publish', 'published', 'failed', 'cancelled', 'uncertain')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (idempotency_key_id)
) STRICT;

CREATE TABLE audit_events (
    id TEXT PRIMARY KEY CHECK (length(id) = 36),
    run_id TEXT REFERENCES editorial_runs(id) ON DELETE RESTRICT,
    actor_type TEXT NOT NULL CHECK (actor_type IN ('system', 'owner', 'model', 'service')),
    actor_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    data_json TEXT CHECK (data_json IS NULL OR json_valid(data_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    prev_hash TEXT CHECK (prev_hash IS NULL OR (length(prev_hash) = 64 AND prev_hash NOT GLOB '*[^0-9a-f]*')),
    event_hash TEXT NOT NULL UNIQUE CHECK (length(event_hash) = 64 AND event_hash NOT GLOB '*[^0-9a-f]*')
) STRICT;

CREATE INDEX research_items_source_status_idx ON research_items (source_id, status, expires_at);
CREATE INDEX topic_proposals_run_status_idx ON topic_proposals (run_id, status);
CREATE INDEX daily_plans_business_date_idx ON daily_plans (business_date, status);
CREATE INDEX plan_items_plan_decision_idx ON plan_items (plan_id, decision);
CREATE INDEX materials_plan_item_status_idx ON materials (plan_item_id, status);
CREATE INDEX material_versions_material_idx ON material_versions (material_id, version);
CREATE INDEX approvals_status_expiry_idx ON approvals (status, expires_at);
CREATE INDEX publication_jobs_status_schedule_idx ON publication_jobs (status, scheduled_at);
CREATE INDEX audit_events_run_created_idx ON audit_events (run_id, created_at);

CREATE TRIGGER audit_events_prevent_update
BEFORE UPDATE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events is append-only; create a new event instead');
END;

CREATE TRIGGER audit_events_prevent_delete
BEFORE DELETE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events is append-only; events cannot be deleted');
END;

CREATE TRIGGER editorial_runs_touch_updated_at AFTER UPDATE ON editorial_runs
WHEN NEW.updated_at = OLD.updated_at BEGIN UPDATE editorial_runs SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;
CREATE TRIGGER research_sources_touch_updated_at AFTER UPDATE ON research_sources
WHEN NEW.updated_at = OLD.updated_at BEGIN UPDATE research_sources SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;
CREATE TRIGGER research_items_touch_updated_at AFTER UPDATE ON research_items
WHEN NEW.updated_at = OLD.updated_at BEGIN UPDATE research_items SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;
CREATE TRIGGER topic_proposals_touch_updated_at AFTER UPDATE ON topic_proposals
WHEN NEW.updated_at = OLD.updated_at BEGIN UPDATE topic_proposals SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;
CREATE TRIGGER daily_plans_touch_updated_at AFTER UPDATE ON daily_plans
WHEN NEW.updated_at = OLD.updated_at BEGIN UPDATE daily_plans SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;
CREATE TRIGGER plan_items_touch_updated_at AFTER UPDATE ON plan_items
WHEN NEW.updated_at = OLD.updated_at BEGIN UPDATE plan_items SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;
CREATE TRIGGER materials_touch_updated_at AFTER UPDATE ON materials
WHEN NEW.updated_at = OLD.updated_at BEGIN UPDATE materials SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;
CREATE TRIGGER approvals_touch_updated_at AFTER UPDATE ON approvals
WHEN NEW.updated_at = OLD.updated_at BEGIN UPDATE approvals SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;
CREATE TRIGGER idempotency_keys_touch_updated_at AFTER UPDATE ON idempotency_keys
WHEN NEW.updated_at = OLD.updated_at BEGIN UPDATE idempotency_keys SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;
CREATE TRIGGER publication_jobs_touch_updated_at AFTER UPDATE ON publication_jobs
WHEN NEW.updated_at = OLD.updated_at BEGIN UPDATE publication_jobs SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;

PRAGMA foreign_keys = ON;

CREATE TABLE editorial_schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    checksum TEXT NOT NULL CHECK (length(checksum) = 64 AND checksum NOT GLOB '*[^0-9a-f]*'),
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE TABLE editorial_memory (
    id TEXT PRIMARY KEY CHECK (length(id) = 36),
    semantic_key TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL CHECK (category IN ('rule', 'fact', 'insight', 'platform')),
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('approved_memory', 'owner', 'editorial_result')),
    source_ref TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE TABLE editorial_topics (
    id TEXT PRIMARY KEY CHECK (length(id) = 36),
    idempotency_key TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    primary_intent TEXT NOT NULL,
    primary_query TEXT,
    cluster_name TEXT,
    priority INTEGER NOT NULL DEFAULT 50 CHECK (priority BETWEEN 0 AND 100),
    status TEXT NOT NULL DEFAULT 'idea' CHECK (status IN ('idea', 'planned', 'in_progress', 'completed', 'archived')),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE TABLE editorial_materials (
    id TEXT PRIMARY KEY CHECK (length(id) = 36),
    idempotency_key TEXT NOT NULL UNIQUE,
    topic_id TEXT NOT NULL REFERENCES editorial_topics(id) ON DELETE RESTRICT,
    parent_material_id TEXT REFERENCES editorial_materials(id) ON DELETE RESTRICT,
    material_type TEXT NOT NULL CHECK (material_type IN ('article', 'telegram_post', 'vk_post', 'brief', 'other')),
    title TEXT NOT NULL,
    content_ref TEXT,
    status TEXT NOT NULL DEFAULT 'planned' CHECK (status IN ('planned', 'draft', 'review', 'approved', 'published', 'archived')),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (parent_material_id IS NULL OR parent_material_id <> id),
    CHECK (parent_material_id IS NULL OR material_type <> 'article')
) STRICT;

CREATE TABLE editorial_publications (
    id TEXT PRIMARY KEY CHECK (length(id) = 36),
    idempotency_key TEXT NOT NULL UNIQUE,
    material_id TEXT NOT NULL REFERENCES editorial_materials(id) ON DELETE RESTRICT,
    platform TEXT NOT NULL,
    account_ref TEXT,
    status TEXT NOT NULL DEFAULT 'planned' CHECK (status IN ('planned', 'published', 'failed', 'retracted')),
    url TEXT,
    external_id TEXT,
    published_at TEXT,
    confirmation_kind TEXT CHECK (confirmation_kind IN ('owner', 'verified_url')),
    confirmation_ref TEXT,
    confirmed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (
      status <> 'published' OR (
        published_at IS NOT NULL AND confirmed_at IS NOT NULL AND confirmation_kind IS NOT NULL
        AND ((confirmation_kind = 'owner' AND confirmation_ref IS NOT NULL)
          OR (confirmation_kind = 'verified_url' AND url IS NOT NULL))
      )
    )
) STRICT;

CREATE TABLE editorial_results (
    id TEXT PRIMARY KEY CHECK (length(id) = 36),
    idempotency_key TEXT NOT NULL UNIQUE,
    publication_id TEXT NOT NULL REFERENCES editorial_publications(id) ON DELETE RESTRICT,
    metric_name TEXT NOT NULL,
    metric_value REAL NOT NULL,
    unit TEXT NOT NULL,
    period_start TEXT,
    period_end TEXT,
    observed_at TEXT NOT NULL,
    source TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE INDEX editorial_memory_active_idx ON editorial_memory (status, category, semantic_key);
CREATE INDEX editorial_topics_status_priority_idx ON editorial_topics (status, priority DESC, updated_at DESC);
CREATE INDEX editorial_materials_topic_idx ON editorial_materials (topic_id, status, updated_at DESC);
CREATE INDEX editorial_materials_parent_idx ON editorial_materials (parent_material_id, material_type);
CREATE INDEX editorial_publications_material_idx ON editorial_publications (material_id, status, published_at DESC);
CREATE INDEX editorial_results_publication_idx ON editorial_results (publication_id, observed_at DESC);

CREATE TRIGGER editorial_material_parent_validate_insert
BEFORE INSERT ON editorial_materials
WHEN NEW.parent_material_id IS NOT NULL
BEGIN
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM editorial_materials parent
    WHERE parent.id = NEW.parent_material_id
      AND parent.topic_id = NEW.topic_id
      AND parent.material_type = 'article'
  ) THEN RAISE(ABORT, 'derived editorial material requires an article parent in the same topic') END;
END;

CREATE TRIGGER editorial_material_parent_validate_update
BEFORE UPDATE OF parent_material_id, topic_id, material_type ON editorial_materials
WHEN NEW.parent_material_id IS NOT NULL
BEGIN
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM editorial_materials parent
    WHERE parent.id = NEW.parent_material_id
      AND parent.topic_id = NEW.topic_id
      AND parent.material_type = 'article'
  ) THEN RAISE(ABORT, 'derived editorial material requires an article parent in the same topic') END;
END;

CREATE TRIGGER editorial_memory_touch_updated_at AFTER UPDATE ON editorial_memory
WHEN NEW.updated_at = OLD.updated_at
BEGIN UPDATE editorial_memory SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;
CREATE TRIGGER editorial_topics_touch_updated_at AFTER UPDATE ON editorial_topics
WHEN NEW.updated_at = OLD.updated_at
BEGIN UPDATE editorial_topics SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;
CREATE TRIGGER editorial_materials_touch_updated_at AFTER UPDATE ON editorial_materials
WHEN NEW.updated_at = OLD.updated_at
BEGIN UPDATE editorial_materials SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;
CREATE TRIGGER editorial_publications_touch_updated_at AFTER UPDATE ON editorial_publications
WHEN NEW.updated_at = OLD.updated_at
BEGIN UPDATE editorial_publications SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;

INSERT INTO editorial_memory
  (id, semantic_key, category, title, content, source_type, source_ref, status, created_at, updated_at)
SELECT id, semantic_key,
       CASE WHEN type = 'editorial_rule' THEN 'rule'
            WHEN semantic_key LIKE 'publication.%' THEN 'platform'
            ELSE 'fact' END,
       title, content, 'approved_memory', id, 'active', created_at, updated_at
FROM (
  SELECT *, row_number() OVER (
    PARTITION BY semantic_key ORDER BY updated_at DESC, created_at DESC, id DESC
  ) AS editorial_rank
  FROM memory_candidates
  WHERE status = 'approved'
    AND (
      semantic_key LIKE 'editorial.%'
      OR semantic_key LIKE 'content.%'
      OR semantic_key LIKE 'publication.%'
    )
)
WHERE editorial_rank = 1;

PRAGMA foreign_keys = ON;

CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE TABLE sources (
    id TEXT PRIMARY KEY CHECK (length(id) = 36),
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT,
    data_json TEXT CHECK (data_json IS NULL OR json_valid(data_json)),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    author TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    valid_at TEXT,
    access_level TEXT NOT NULL DEFAULT 'internal' CHECK (access_level IN ('public', 'internal', 'restricted')),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    CHECK (content IS NOT NULL OR data_json IS NOT NULL)
) STRICT;

CREATE TABLE memory_items (
    id TEXT PRIMARY KEY CHECK (length(id) = 36),
    type TEXT NOT NULL,
    semantic_key TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT,
    data_json TEXT CHECK (data_json IS NULL OR json_valid(data_json)),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'superseded', 'archived')),
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
    author TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    valid_at TEXT,
    access_level TEXT NOT NULL DEFAULT 'internal' CHECK (access_level IN ('public', 'internal', 'restricted')),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    CHECK (content IS NOT NULL OR data_json IS NOT NULL)
) STRICT;

CREATE UNIQUE INDEX memory_items_one_active_key
    ON memory_items(semantic_key) WHERE status = 'active';

CREATE TABLE memory_candidates (
    id TEXT PRIMARY KEY CHECK (length(id) = 36),
    type TEXT NOT NULL,
    semantic_key TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT,
    data_json TEXT CHECK (data_json IS NULL OR json_valid(data_json)),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
    target_memory_item_id TEXT REFERENCES memory_items(id) ON DELETE RESTRICT,
    author TEXT NOT NULL,
    reviewed_by TEXT,
    review_note TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    valid_at TEXT,
    access_level TEXT NOT NULL DEFAULT 'internal' CHECK (access_level IN ('public', 'internal', 'restricted')),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    CHECK (content IS NOT NULL OR data_json IS NOT NULL),
    CHECK (status = 'pending' OR reviewed_by IS NOT NULL)
) STRICT;

CREATE TABLE memory_conflicts (
    id TEXT PRIMARY KEY CHECK (length(id) = 36),
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT,
    data_json TEXT CHECK (data_json IS NULL OR json_valid(data_json)),
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved', 'dismissed')),
    candidate_id TEXT NOT NULL REFERENCES memory_candidates(id) ON DELETE RESTRICT,
    existing_memory_item_id TEXT NOT NULL REFERENCES memory_items(id) ON DELETE RESTRICT,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
    author TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    valid_at TEXT,
    access_level TEXT NOT NULL DEFAULT 'internal' CHECK (access_level IN ('public', 'internal', 'restricted')),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    resolution TEXT,
    UNIQUE (candidate_id, existing_memory_item_id),
    CHECK (content IS NOT NULL OR data_json IS NOT NULL)
) STRICT;

CREATE TABLE decisions (
    id TEXT PRIMARY KEY CHECK (length(id) = 36),
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT,
    data_json TEXT CHECK (data_json IS NULL OR json_valid(data_json)),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'superseded', 'archived')),
    source_id TEXT REFERENCES sources(id) ON DELETE RESTRICT,
    author TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    valid_at TEXT,
    access_level TEXT NOT NULL DEFAULT 'internal' CHECK (access_level IN ('public', 'internal', 'restricted')),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    CHECK (content IS NOT NULL OR data_json IS NOT NULL)
) STRICT;

CREATE TABLE tasks (
    id TEXT PRIMARY KEY CHECK (length(id) = 36),
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT,
    data_json TEXT CHECK (data_json IS NULL OR json_valid(data_json)),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'in_progress', 'completed', 'cancelled')),
    source_id TEXT REFERENCES sources(id) ON DELETE RESTRICT,
    author TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    valid_at TEXT,
    access_level TEXT NOT NULL DEFAULT 'internal' CHECK (access_level IN ('public', 'internal', 'restricted')),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    CHECK (content IS NOT NULL OR data_json IS NOT NULL)
) STRICT;

CREATE TABLE documents (
    id TEXT PRIMARY KEY CHECK (length(id) = 36),
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT,
    data_json TEXT CHECK (data_json IS NULL OR json_valid(data_json)),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    source_id TEXT REFERENCES sources(id) ON DELETE RESTRICT,
    author TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    valid_at TEXT,
    access_level TEXT NOT NULL DEFAULT 'internal' CHECK (access_level IN ('public', 'internal', 'restricted')),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    CHECK (content IS NOT NULL OR data_json IS NOT NULL)
) STRICT;

CREATE TABLE document_versions (
    id TEXT PRIMARY KEY CHECK (length(id) = 36),
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE RESTRICT,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT,
    data_json TEXT CHECK (data_json IS NULL OR json_valid(data_json)),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'superseded', 'archived')),
    source_id TEXT REFERENCES sources(id) ON DELETE RESTRICT,
    author TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    valid_at TEXT,
    access_level TEXT NOT NULL DEFAULT 'internal' CHECK (access_level IN ('public', 'internal', 'restricted')),
    version INTEGER NOT NULL CHECK (version > 0),
    UNIQUE (document_id, version),
    CHECK (content IS NOT NULL OR data_json IS NOT NULL)
) STRICT;

CREATE TABLE audit_log (
    id TEXT PRIMARY KEY CHECK (length(id) = 36),
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT,
    data_json TEXT CHECK (data_json IS NULL OR json_valid(data_json)),
    status TEXT NOT NULL DEFAULT 'recorded' CHECK (status = 'recorded'),
    source_id TEXT REFERENCES sources(id) ON DELETE RESTRICT,
    author TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    valid_at TEXT,
    access_level TEXT NOT NULL DEFAULT 'restricted' CHECK (access_level IN ('internal', 'restricted')),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version = 1),
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL CHECK (length(entity_id) = 36),
    action TEXT NOT NULL CHECK (action IN ('create', 'update')),
    CHECK (content IS NOT NULL OR data_json IS NOT NULL)
) STRICT;

CREATE TRIGGER memory_items_audit_insert
AFTER INSERT ON memory_items
BEGIN
    INSERT INTO audit_log (
        id, type, title, data_json, source_id, author,
        entity_type, entity_id, action
    ) VALUES (
        lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' ||
        substr(lower(hex(randomblob(2))), 2) || '-' ||
        substr('89ab', abs(random()) % 4 + 1, 1) || substr(lower(hex(randomblob(2))), 2) || '-' ||
        lower(hex(randomblob(6))),
        'memory_item_change', 'Memory item created',
        json_object('new', json(NEW.data_json), 'content', NEW.content, 'status', NEW.status, 'version', NEW.version),
        NEW.source_id, NEW.author, 'memory_item', NEW.id, 'create'
    );
END;

CREATE TRIGGER memory_items_validate_update
BEFORE UPDATE ON memory_items
WHEN NEW.version <> OLD.version + 1
BEGIN
    SELECT RAISE(ABORT, 'memory_items version must increase by exactly one');
END;

CREATE TRIGGER memory_items_audit_update
AFTER UPDATE ON memory_items
BEGIN
    INSERT INTO audit_log (
        id, type, title, data_json, source_id, author,
        entity_type, entity_id, action
    ) VALUES (
        lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' ||
        substr(lower(hex(randomblob(2))), 2) || '-' ||
        substr('89ab', abs(random()) % 4 + 1, 1) || substr(lower(hex(randomblob(2))), 2) || '-' ||
        lower(hex(randomblob(6))),
        'memory_item_change', 'Memory item updated',
        json_object(
            'old', json_object('content', OLD.content, 'data', json(OLD.data_json), 'status', OLD.status, 'version', OLD.version),
            'new', json_object('content', NEW.content, 'data', json(NEW.data_json), 'status', NEW.status, 'version', NEW.version)
        ),
        NEW.source_id, NEW.author, 'memory_item', NEW.id, 'update'
    );
END;

CREATE TRIGGER memory_items_prevent_delete
BEFORE DELETE ON memory_items
BEGIN
    SELECT RAISE(ABORT, 'memory_items cannot be deleted; archive or supersede instead');
END;

CREATE TRIGGER audit_log_prevent_update
BEFORE UPDATE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only');
END;

CREATE TRIGGER audit_log_prevent_delete
BEFORE DELETE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only');
END;

CREATE TRIGGER memory_candidates_conflict_on_approval
AFTER UPDATE OF status ON memory_candidates
WHEN NEW.status = 'approved'
 AND OLD.status <> 'approved'
 AND NEW.target_memory_item_id IS NOT NULL
 AND EXISTS (
    SELECT 1 FROM memory_items m
    WHERE m.id = NEW.target_memory_item_id
      AND m.status = 'active'
      AND (m.content IS NOT NEW.content OR m.data_json IS NOT NEW.data_json)
 )
BEGIN
    INSERT OR IGNORE INTO memory_conflicts (
        id, type, title, content, data_json, candidate_id,
        existing_memory_item_id, source_id, author, valid_at, access_level
    ) VALUES (
        lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' ||
        substr(lower(hex(randomblob(2))), 2) || '-' ||
        substr('89ab', abs(random()) % 4 + 1, 1) || substr(lower(hex(randomblob(2))), 2) || '-' ||
        lower(hex(randomblob(6))),
        'memory_candidate_conflict', 'Conflict: ' || NEW.title,
        NEW.content, NEW.data_json, NEW.id, NEW.target_memory_item_id,
        NEW.source_id, NEW.reviewed_by, NEW.valid_at, NEW.access_level
    );
END;


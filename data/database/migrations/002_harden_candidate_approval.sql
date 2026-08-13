ALTER TABLE memory_candidates ADD COLUMN reviewed_at TEXT;

DROP TRIGGER memory_candidates_conflict_on_approval;

CREATE TRIGGER memory_candidates_require_pending_insert
BEFORE INSERT ON memory_candidates
WHEN NEW.status <> 'pending'
BEGIN
    SELECT RAISE(ABORT, 'new memory_candidates must have pending status');
END;

CREATE TRIGGER memory_candidates_validate_approval
BEFORE UPDATE OF status ON memory_candidates
WHEN NEW.status = 'approved'
 AND OLD.status <> 'approved'
 AND (
    NEW.reviewed_by IS NULL OR trim(NEW.reviewed_by) = '' OR
    NEW.reviewed_at IS NULL OR trim(NEW.reviewed_at) = ''
 )
BEGIN
    SELECT RAISE(ABORT, 'approval requires reviewed_by and reviewed_at');
END;

CREATE TRIGGER memory_candidates_conflict_on_approval
AFTER UPDATE OF status ON memory_candidates
WHEN NEW.status = 'approved' AND OLD.status <> 'approved'
BEGIN
    INSERT INTO memory_conflicts (
        id, type, title, content, data_json, candidate_id,
        existing_memory_item_id, source_id, author, valid_at, access_level
    )
    SELECT
        lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' ||
        substr(lower(hex(randomblob(2))), 2) || '-' ||
        substr('89ab', abs(random()) % 4 + 1, 1) || substr(lower(hex(randomblob(2))), 2) || '-' ||
        lower(hex(randomblob(6))),
        'memory_candidate_conflict', 'Conflict: ' || NEW.title,
        NEW.content, NEW.data_json, NEW.id, m.id,
        NEW.source_id, NEW.reviewed_by, NEW.valid_at, NEW.access_level
    FROM memory_items AS m
    WHERE m.status = 'active'
      AND (
        (NEW.target_memory_item_id IS NOT NULL AND m.id = NEW.target_memory_item_id) OR
        (NEW.target_memory_item_id IS NULL AND m.semantic_key = NEW.semantic_key)
      )
      AND (m.content IS NOT NEW.content OR m.data_json IS NOT NEW.data_json)
    ON CONFLICT (candidate_id, existing_memory_item_id) DO UPDATE SET
        type = excluded.type,
        title = excluded.title,
        content = excluded.content,
        data_json = excluded.data_json,
        status = 'open',
        source_id = excluded.source_id,
        author = excluded.author,
        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
        valid_at = excluded.valid_at,
        access_level = excluded.access_level,
        version = memory_conflicts.version + 1,
        resolution = NULL;
END;


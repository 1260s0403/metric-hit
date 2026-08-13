DROP TRIGGER memory_candidates_conflict_on_approval;

CREATE TRIGGER memory_candidates_conflict_on_approval
AFTER UPDATE OF status ON memory_candidates
WHEN NEW.status = 'approved' AND OLD.status = 'pending'
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
      AND (m.semantic_key = NEW.semantic_key OR m.id = NEW.target_memory_item_id)
      AND (m.content IS NOT NEW.content OR m.data_json IS NOT NEW.data_json)
    ON CONFLICT (candidate_id, existing_memory_item_id) DO UPDATE SET
        type = excluded.type, title = excluded.title,
        content = excluded.content, data_json = excluded.data_json,
        status = 'open', source_id = excluded.source_id, author = excluded.author,
        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
        valid_at = excluded.valid_at, access_level = excluded.access_level,
        version = memory_conflicts.version + 1, resolution = NULL;
END;

DROP TRIGGER memory_items_audit_insert;
DROP TRIGGER memory_items_audit_update;

CREATE TRIGGER memory_items_audit_insert
AFTER INSERT ON memory_items
BEGIN
    INSERT INTO audit_log (id, type, title, data_json, source_id, author, entity_type, entity_id, action)
    VALUES (
        lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' ||
        substr(lower(hex(randomblob(2))), 2) || '-' ||
        substr('89ab', abs(random()) % 4 + 1, 1) || substr(lower(hex(randomblob(2))), 2) || '-' ||
        lower(hex(randomblob(6))),
        'memory_item_change', 'Memory item created',
        json_object('new', json_object(
            'id', NEW.id, 'type', NEW.type, 'semantic_key', NEW.semantic_key,
            'title', NEW.title, 'content', NEW.content, 'data_json', json(NEW.data_json),
            'status', NEW.status, 'source_id', NEW.source_id, 'author', NEW.author,
            'created_at', NEW.created_at, 'updated_at', NEW.updated_at,
            'valid_at', NEW.valid_at, 'access_level', NEW.access_level, 'version', NEW.version
        )),
        NEW.source_id, NEW.author, 'memory_item', NEW.id, 'create'
    );
END;

CREATE TRIGGER memory_items_audit_update
AFTER UPDATE ON memory_items
BEGIN
    INSERT INTO audit_log (id, type, title, data_json, source_id, author, entity_type, entity_id, action)
    VALUES (
        lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' ||
        substr(lower(hex(randomblob(2))), 2) || '-' ||
        substr('89ab', abs(random()) % 4 + 1, 1) || substr(lower(hex(randomblob(2))), 2) || '-' ||
        lower(hex(randomblob(6))),
        'memory_item_change', 'Memory item updated',
        json_object(
            'old', json_object(
                'id', OLD.id, 'type', OLD.type, 'semantic_key', OLD.semantic_key,
                'title', OLD.title, 'content', OLD.content, 'data_json', json(OLD.data_json),
                'status', OLD.status, 'source_id', OLD.source_id, 'author', OLD.author,
                'created_at', OLD.created_at, 'updated_at', OLD.updated_at,
                'valid_at', OLD.valid_at, 'access_level', OLD.access_level, 'version', OLD.version
            ),
            'new', json_object(
                'id', NEW.id, 'type', NEW.type, 'semantic_key', NEW.semantic_key,
                'title', NEW.title, 'content', NEW.content, 'data_json', json(NEW.data_json),
                'status', NEW.status, 'source_id', NEW.source_id, 'author', NEW.author,
                'created_at', NEW.created_at, 'updated_at', NEW.updated_at,
                'valid_at', NEW.valid_at, 'access_level', NEW.access_level, 'version', NEW.version
            )
        ),
        NEW.source_id, NEW.author, 'memory_item', NEW.id, 'update'
    );
END;

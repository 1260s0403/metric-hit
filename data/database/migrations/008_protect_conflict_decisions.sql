DROP TRIGGER memory_conflicts_validate_resolution;

CREATE TRIGGER memory_conflicts_validate_insert
BEFORE INSERT ON memory_conflicts
WHEN (
    NEW.status IN ('resolved', 'dismissed')
    AND (NEW.resolution IS NULL OR trim(NEW.resolution) = '')
 ) OR (
    NEW.status = 'open' AND NEW.resolution IS NOT NULL
 )
BEGIN
    SELECT RAISE(ABORT, 'closed conflicts require a resolution; open conflicts must not have one');
END;

CREATE TRIGGER memory_conflicts_protect_history
BEFORE UPDATE ON memory_conflicts
WHEN NEW.id IS NOT OLD.id
 OR NEW.type IS NOT OLD.type
 OR NEW.title IS NOT OLD.title
 OR NEW.content IS NOT OLD.content
 OR NEW.data_json IS NOT OLD.data_json
 OR NEW.candidate_id IS NOT OLD.candidate_id
 OR NEW.existing_memory_item_id IS NOT OLD.existing_memory_item_id
 OR NEW.source_id IS NOT OLD.source_id
 OR NEW.author IS NOT OLD.author
 OR NEW.created_at IS NOT OLD.created_at
 OR NEW.valid_at IS NOT OLD.valid_at
 OR NEW.access_level IS NOT OLD.access_level
BEGIN
    SELECT RAISE(ABORT, 'memory_conflicts history and attribution are immutable');
END;

CREATE TRIGGER memory_conflicts_protect_closed_decision
BEFORE UPDATE ON memory_conflicts
WHEN OLD.status IN ('resolved', 'dismissed')
 AND (
    NEW.status IS NOT OLD.status OR
    NEW.resolution IS NOT OLD.resolution
 )
BEGIN
    SELECT RAISE(ABORT, 'closed memory_conflicts decisions are immutable');
END;

CREATE TRIGGER memory_conflicts_validate_update
BEFORE UPDATE ON memory_conflicts
WHEN (
    NEW.status IN ('resolved', 'dismissed')
    AND (NEW.resolution IS NULL OR trim(NEW.resolution) = '')
 ) OR (
    NEW.status = 'open' AND NEW.resolution IS NOT NULL
 ) OR (
    OLD.status = 'open' AND NEW.status NOT IN ('open', 'resolved', 'dismissed')
 )
BEGIN
    SELECT RAISE(ABORT, 'invalid conflict state; closing requires a non-empty resolution');
END;


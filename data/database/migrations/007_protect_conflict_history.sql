CREATE TRIGGER memory_conflicts_prevent_delete
BEFORE DELETE ON memory_conflicts
BEGIN
    SELECT RAISE(ABORT, 'memory_conflicts cannot be deleted; resolve or dismiss instead');
END;

CREATE TRIGGER memory_conflicts_validate_resolution
BEFORE UPDATE ON memory_conflicts
WHEN (
    NEW.status IN ('resolved', 'dismissed')
    AND (NEW.resolution IS NULL OR trim(NEW.resolution) = '')
 ) OR (
    NEW.status = 'open' AND NEW.resolution IS NOT NULL
 )
BEGIN
    SELECT RAISE(ABORT, 'closed conflicts require a resolution; open conflicts must not have one');
END;


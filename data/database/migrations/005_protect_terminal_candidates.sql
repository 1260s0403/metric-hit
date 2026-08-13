CREATE TRIGGER memory_candidates_protect_terminal_update
BEFORE UPDATE ON memory_candidates
WHEN OLD.status IN ('approved', 'rejected')
 AND (
    NEW.id IS NOT OLD.id OR
    NEW.type IS NOT OLD.type OR
    NEW.semantic_key IS NOT OLD.semantic_key OR
    NEW.title IS NOT OLD.title OR
    NEW.content IS NOT OLD.content OR
    NEW.data_json IS NOT OLD.data_json OR
    NEW.status IS NOT OLD.status OR
    NEW.source_id IS NOT OLD.source_id OR
    NEW.target_memory_item_id IS NOT OLD.target_memory_item_id OR
    NEW.author IS NOT OLD.author OR
    NEW.reviewed_by IS NOT OLD.reviewed_by OR
    NEW.review_note IS NOT OLD.review_note OR
    NEW.created_at IS NOT OLD.created_at OR
    NEW.valid_at IS NOT OLD.valid_at OR
    NEW.access_level IS NOT OLD.access_level OR
    NEW.reviewed_at IS NOT OLD.reviewed_at
 )
BEGIN
    SELECT RAISE(ABORT, 'terminal memory_candidates are immutable; create a new candidate instead');
END;

CREATE TRIGGER memory_candidates_protect_terminal_delete
BEFORE DELETE ON memory_candidates
WHEN OLD.status IN ('approved', 'rejected')
BEGIN
    SELECT RAISE(ABORT, 'terminal memory_candidates cannot be deleted; create a new candidate instead');
END;


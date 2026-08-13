DROP TRIGGER memory_candidates_validate_approval;

CREATE TRIGGER memory_candidates_validate_review_outcome
BEFORE UPDATE OF status ON memory_candidates
WHEN OLD.status = 'pending'
 AND NEW.status IN ('approved', 'rejected')
 AND (
    NEW.reviewed_by IS NULL OR trim(NEW.reviewed_by) = '' OR
    NEW.reviewed_at IS NULL OR trim(NEW.reviewed_at) = ''
 )
BEGIN
    SELECT RAISE(ABORT, 'approval or rejection requires reviewed_by and reviewed_at');
END;

CREATE TRIGGER document_versions_prevent_update
BEFORE UPDATE ON document_versions
BEGIN
    SELECT RAISE(ABORT, 'document_versions is append-only; add a new version instead');
END;

CREATE TRIGGER document_versions_prevent_delete
BEFORE DELETE ON document_versions
BEGIN
    SELECT RAISE(ABORT, 'document_versions is append-only; versions cannot be deleted');
END;


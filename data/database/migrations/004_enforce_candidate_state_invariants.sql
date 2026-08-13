DROP TRIGGER memory_candidates_validate_review_outcome;

CREATE TRIGGER memory_candidates_validate_review_metadata_insert
BEFORE INSERT ON memory_candidates
WHEN NEW.status IN ('approved', 'rejected')
 AND (
    NEW.reviewed_by IS NULL OR trim(NEW.reviewed_by) = '' OR
    NEW.reviewed_at IS NULL OR trim(NEW.reviewed_at) = ''
 )
BEGIN
    SELECT RAISE(ABORT, 'approved or rejected candidates require reviewed_by and reviewed_at');
END;

CREATE TRIGGER memory_candidates_validate_review_metadata_update
BEFORE UPDATE ON memory_candidates
WHEN NEW.status IN ('approved', 'rejected')
 AND (
    NEW.reviewed_by IS NULL OR trim(NEW.reviewed_by) = '' OR
    NEW.reviewed_at IS NULL OR trim(NEW.reviewed_at) = ''
 )
BEGIN
    SELECT RAISE(ABORT, 'approved or rejected candidates require reviewed_by and reviewed_at');
END;

CREATE TRIGGER memory_candidates_validate_status_transition
BEFORE UPDATE OF status ON memory_candidates
WHEN NEW.status <> OLD.status
 AND NOT (
    OLD.status = 'pending' AND NEW.status IN ('approved', 'rejected')
 )
BEGIN
    SELECT RAISE(ABORT, 'invalid memory_candidates status transition; create a new candidate for reconsideration');
END;


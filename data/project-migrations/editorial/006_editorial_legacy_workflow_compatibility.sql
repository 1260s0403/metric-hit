PRAGMA foreign_keys = ON;

DROP TRIGGER editorial_material_workflow_validate_update;

UPDATE editorial_materials
SET workflow_stage = 'idea',
    workflow_actor = 'migration',
    workflow_note = 'Legacy pre-workflow material starts at idea stage',
    workflow_updated_at = updated_at
WHERE workflow_stage IN ('draft', 'review');

CREATE TRIGGER editorial_material_workflow_validate_update
BEFORE UPDATE OF workflow_stage ON editorial_materials
WHEN NEW.workflow_stage <> OLD.workflow_stage
BEGIN
  SELECT CASE WHEN NOT (
    (OLD.workflow_stage = 'idea' AND NEW.workflow_stage = 'plan')
    OR (OLD.workflow_stage = 'plan' AND NEW.workflow_stage = 'draft')
    OR (OLD.workflow_stage = 'draft' AND NEW.workflow_stage = 'review')
    OR (OLD.workflow_stage = 'review' AND NEW.workflow_stage = 'draft')
    OR (OLD.workflow_stage = 'review' AND NEW.workflow_stage = 'published')
    OR (OLD.workflow_stage = 'published' AND NEW.workflow_stage = 'result')
  ) THEN RAISE(ABORT, 'invalid editorial workflow transition') END;
  SELECT CASE WHEN trim(NEW.workflow_actor) = ''
    THEN RAISE(ABORT, 'editorial workflow actor is required') END;
  SELECT CASE WHEN NEW.workflow_stage IN ('plan','draft','review','published')
      AND (NEW.plan_ref IS NULL OR trim(NEW.plan_ref) = '')
    THEN RAISE(ABORT, 'plan_ref is required from plan stage') END;
  SELECT CASE WHEN NEW.workflow_stage IN ('draft','review','published')
      AND (NEW.content_ref IS NULL OR trim(NEW.content_ref) = '')
    THEN RAISE(ABORT, 'content_ref is required from draft stage') END;
  SELECT CASE WHEN NEW.workflow_stage IN ('review','published')
      AND (NEW.review_requested_by IS NULL OR trim(NEW.review_requested_by) = '')
    THEN RAISE(ABORT, 'review_requested_by is required from review stage') END;
  SELECT CASE WHEN NEW.workflow_stage = 'published' AND NOT EXISTS (
    SELECT 1 FROM editorial_publications publication
    WHERE publication.material_id = NEW.id
      AND publication.status = 'published'
      AND publication.confirmed_at IS NOT NULL
      AND publication.confirmation_kind IN ('owner','verified_url')
  ) THEN RAISE(ABORT, 'published stage requires a confirmed publication') END;
  SELECT CASE WHEN NEW.workflow_stage = 'result' AND NOT EXISTS (
    SELECT 1 FROM editorial_results result
    JOIN editorial_publications publication ON publication.id = result.publication_id
    WHERE publication.material_id = NEW.id AND publication.status = 'published'
  ) THEN RAISE(ABORT, 'result stage requires a recorded publication result') END;
END;

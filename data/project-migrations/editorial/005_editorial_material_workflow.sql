PRAGMA foreign_keys = ON;

ALTER TABLE editorial_materials
ADD COLUMN workflow_stage TEXT NOT NULL DEFAULT 'idea'
CHECK (workflow_stage IN ('idea', 'plan', 'draft', 'review', 'published', 'result'));

ALTER TABLE editorial_materials ADD COLUMN plan_ref TEXT;
ALTER TABLE editorial_materials ADD COLUMN review_requested_by TEXT;
ALTER TABLE editorial_materials ADD COLUMN workflow_actor TEXT NOT NULL DEFAULT 'system';
ALTER TABLE editorial_materials ADD COLUMN workflow_note TEXT;
ALTER TABLE editorial_materials
ADD COLUMN workflow_updated_at TEXT NOT NULL DEFAULT '1970-01-01T00:00:00Z';

UPDATE editorial_materials
SET workflow_stage = CASE status
  WHEN 'draft' THEN 'draft'
  WHEN 'review' THEN 'review'
  WHEN 'approved' THEN 'review'
  WHEN 'published' THEN 'published'
  ELSE 'idea'
END,
workflow_actor = 'migration',
workflow_updated_at = updated_at;

CREATE TABLE editorial_status_audit (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id TEXT NOT NULL REFERENCES editorial_materials(id) ON DELETE RESTRICT,
    from_stage TEXT CHECK (from_stage IS NULL OR from_stage IN ('idea', 'plan', 'draft', 'review', 'published', 'result')),
    to_stage TEXT NOT NULL CHECK (to_stage IN ('idea', 'plan', 'draft', 'review', 'published', 'result')),
    actor TEXT NOT NULL,
    note TEXT,
    changed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

INSERT INTO editorial_status_audit(material_id,from_stage,to_stage,actor,note,changed_at)
SELECT id,NULL,workflow_stage,'migration','Initial stage recorded during workflow migration',created_at
FROM editorial_materials;

CREATE INDEX editorial_status_audit_material_idx
ON editorial_status_audit(material_id, sequence);

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
  SELECT CASE WHEN NEW.workflow_stage IN ('plan','draft','review','published','result')
      AND (NEW.plan_ref IS NULL OR trim(NEW.plan_ref) = '')
    THEN RAISE(ABORT, 'plan_ref is required from plan stage') END;
  SELECT CASE WHEN NEW.workflow_stage IN ('draft','review','published','result')
      AND (NEW.content_ref IS NULL OR trim(NEW.content_ref) = '')
    THEN RAISE(ABORT, 'content_ref is required from draft stage') END;
  SELECT CASE WHEN NEW.workflow_stage IN ('review','published','result')
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

CREATE TRIGGER editorial_material_workflow_audit_insert
AFTER INSERT ON editorial_materials
BEGIN
  INSERT INTO editorial_status_audit(material_id,from_stage,to_stage,actor,note)
  VALUES(NEW.id,NULL,NEW.workflow_stage,NEW.workflow_actor,NEW.workflow_note);
END;

CREATE TRIGGER editorial_material_workflow_audit_update
AFTER UPDATE OF workflow_stage ON editorial_materials
WHEN NEW.workflow_stage <> OLD.workflow_stage
BEGIN
  INSERT INTO editorial_status_audit(material_id,from_stage,to_stage,actor,note)
  VALUES(NEW.id,OLD.workflow_stage,NEW.workflow_stage,NEW.workflow_actor,NEW.workflow_note);
END;

CREATE TRIGGER editorial_status_audit_prevent_update
BEFORE UPDATE ON editorial_status_audit
BEGIN
  SELECT RAISE(ABORT, 'editorial status audit is append-only');
END;

CREATE TRIGGER editorial_status_audit_prevent_delete
BEFORE DELETE ON editorial_status_audit
BEGIN
  SELECT RAISE(ABORT, 'editorial status audit is append-only');
END;

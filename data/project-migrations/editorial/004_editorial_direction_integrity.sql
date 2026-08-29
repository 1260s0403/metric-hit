PRAGMA foreign_keys = ON;

DROP TRIGGER editorial_material_direction_validate_insert;
DROP TRIGGER editorial_material_direction_validate_update;

CREATE TRIGGER editorial_material_direction_validate_insert
BEFORE INSERT ON editorial_materials
BEGIN
  SELECT CASE
    WHEN NEW.material_type = 'article' AND NEW.direction <> 'articles'
      THEN RAISE(ABORT, 'article material requires articles direction')
    WHEN NEW.material_type IN ('telegram_post', 'vk_post') AND NEW.direction <> 'social'
      THEN RAISE(ABORT, 'social post material requires social direction')
  END;
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM editorial_topics topic
    WHERE topic.id = NEW.topic_id
      AND (
        (NEW.parent_material_id IS NULL AND topic.direction = NEW.direction)
        OR (NEW.parent_material_id IS NOT NULL AND NEW.direction = 'social'
            AND topic.direction = 'articles')
      )
  ) THEN RAISE(ABORT, 'material direction does not match its topic workflow') END;
END;

CREATE TRIGGER editorial_material_direction_validate_update
BEFORE UPDATE OF topic_id, parent_material_id, material_type, direction ON editorial_materials
BEGIN
  SELECT CASE
    WHEN NEW.material_type = 'article' AND NEW.direction <> 'articles'
      THEN RAISE(ABORT, 'article material requires articles direction')
    WHEN NEW.material_type IN ('telegram_post', 'vk_post') AND NEW.direction <> 'social'
      THEN RAISE(ABORT, 'social post material requires social direction')
  END;
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM editorial_topics topic
    WHERE topic.id = NEW.topic_id
      AND (
        (NEW.parent_material_id IS NULL AND topic.direction = NEW.direction)
        OR (NEW.parent_material_id IS NOT NULL AND NEW.direction = 'social'
            AND topic.direction = 'articles')
      )
  ) THEN RAISE(ABORT, 'material direction does not match its topic workflow') END;
END;

CREATE TRIGGER editorial_material_parent_protect_update
BEFORE UPDATE OF topic_id, material_type, direction ON editorial_materials
WHEN EXISTS (SELECT 1 FROM editorial_materials child WHERE child.parent_material_id = OLD.id)
BEGIN
  SELECT CASE WHEN NEW.topic_id <> OLD.topic_id
    OR NEW.material_type <> 'article'
    OR NEW.direction <> 'articles'
  THEN RAISE(ABORT, 'source article cannot invalidate derived social materials') END;
END;

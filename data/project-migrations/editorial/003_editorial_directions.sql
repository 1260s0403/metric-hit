PRAGMA foreign_keys = ON;

ALTER TABLE editorial_memory
ADD COLUMN direction TEXT NOT NULL DEFAULT 'common'
CHECK (direction IN ('common', 'articles', 'social'));

ALTER TABLE editorial_topics
ADD COLUMN direction TEXT NOT NULL DEFAULT 'articles'
CHECK (direction IN ('articles', 'social'));

ALTER TABLE editorial_materials
ADD COLUMN direction TEXT NOT NULL DEFAULT 'articles'
CHECK (direction IN ('articles', 'social'));

UPDATE editorial_materials
SET direction = 'social'
WHERE material_type IN ('telegram_post', 'vk_post');

DROP TRIGGER editorial_material_parent_validate_insert;
DROP TRIGGER editorial_material_parent_validate_update;

CREATE TRIGGER editorial_material_direction_validate_insert
BEFORE INSERT ON editorial_materials
BEGIN
  SELECT CASE
    WHEN NEW.material_type = 'article' AND NEW.direction <> 'articles'
      THEN RAISE(ABORT, 'article material requires articles direction')
    WHEN NEW.material_type IN ('telegram_post', 'vk_post') AND NEW.direction <> 'social'
      THEN RAISE(ABORT, 'social post material requires social direction')
  END;
END;

CREATE TRIGGER editorial_material_direction_validate_update
BEFORE UPDATE OF material_type, direction ON editorial_materials
BEGIN
  SELECT CASE
    WHEN NEW.material_type = 'article' AND NEW.direction <> 'articles'
      THEN RAISE(ABORT, 'article material requires articles direction')
    WHEN NEW.material_type IN ('telegram_post', 'vk_post') AND NEW.direction <> 'social'
      THEN RAISE(ABORT, 'social post material requires social direction')
  END;
END;

CREATE TRIGGER editorial_material_parent_validate_insert
BEFORE INSERT ON editorial_materials
WHEN NEW.parent_material_id IS NOT NULL
BEGIN
  SELECT CASE WHEN NEW.direction <> 'social' OR NOT EXISTS (
    SELECT 1 FROM editorial_materials parent
    WHERE parent.id = NEW.parent_material_id
      AND parent.topic_id = NEW.topic_id
      AND parent.material_type = 'article'
      AND parent.direction = 'articles'
  ) THEN RAISE(ABORT, 'derived social material requires an articles parent in the same topic') END;
END;

CREATE TRIGGER editorial_material_parent_validate_update
BEFORE UPDATE OF parent_material_id, topic_id, material_type, direction ON editorial_materials
WHEN NEW.parent_material_id IS NOT NULL
BEGIN
  SELECT CASE WHEN NEW.direction <> 'social' OR NOT EXISTS (
    SELECT 1 FROM editorial_materials parent
    WHERE parent.id = NEW.parent_material_id
      AND parent.topic_id = NEW.topic_id
      AND parent.material_type = 'article'
      AND parent.direction = 'articles'
  ) THEN RAISE(ABORT, 'derived social material requires an articles parent in the same topic') END;
END;

CREATE INDEX editorial_memory_direction_idx
ON editorial_memory (direction, status, category, updated_at DESC);

CREATE INDEX editorial_topics_direction_idx
ON editorial_topics (direction, status, priority DESC, updated_at DESC);

CREATE INDEX editorial_materials_direction_idx
ON editorial_materials (direction, status, updated_at DESC);

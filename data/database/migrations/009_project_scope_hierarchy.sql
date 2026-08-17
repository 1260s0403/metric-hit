PRAGMA foreign_keys = ON;

-- Stable bootstrap scopes. Existing tasks and knowledge entries are deliberately
-- left untouched: their missing scope remains a visible legacy state.
INSERT OR IGNORE INTO documents
  (id, type, title, content, data_json, status, author, access_level, version)
VALUES
  ('00000000-0000-4000-a000-000000000101', 'project', 'Развитие Ядра',
   'Внутренний проект для развития инфраструктуры и control plane «Ядро».',
   '{"kind":"project","scope_type":"independent"}', 'active', 'owner', 'internal', 1),
  ('00000000-0000-4000-a000-000000000102', 'project', 'MetricHit',
   'Первый самостоятельный проект под управлением «Ядра».',
   '{"default_for_new":true,"kind":"project","scope_type":"independent"}', 'active', 'owner', 'internal', 1);

CREATE TRIGGER project_scope_validate_insert
BEFORE INSERT ON documents
WHEN NEW.type = 'project'
BEGIN
  SELECT CASE
    WHEN json_extract(NEW.data_json, '$.scope_type') NOT IN ('independent', 'subproject')
      THEN RAISE(ABORT, 'project scope_type must be independent or subproject')
    WHEN json_extract(NEW.data_json, '$.scope_type') = 'independent'
      AND json_type(NEW.data_json, '$.parent_project_id') IS NOT NULL
      THEN RAISE(ABORT, 'independent project cannot have a parent')
    WHEN json_extract(NEW.data_json, '$.scope_type') = 'subproject'
      AND NOT EXISTS (
        SELECT 1 FROM documents parent
        WHERE parent.id = json_extract(NEW.data_json, '$.parent_project_id')
          AND parent.type = 'project' AND parent.status = 'active'
          AND json_extract(parent.data_json, '$.scope_type') = 'independent'
      )
      THEN RAISE(ABORT, 'subproject parent must be an active independent project')
  END;
END;

CREATE TRIGGER project_scope_validate_update
BEFORE UPDATE OF data_json, status ON documents
WHEN NEW.type = 'project'
BEGIN
  SELECT CASE
    WHEN json_extract(NEW.data_json, '$.scope_type') NOT IN ('independent', 'subproject')
      THEN RAISE(ABORT, 'project scope_type must be independent or subproject')
    WHEN json_extract(NEW.data_json, '$.scope_type') = 'independent'
      AND json_type(NEW.data_json, '$.parent_project_id') IS NOT NULL
      THEN RAISE(ABORT, 'independent project cannot have a parent')
    WHEN json_extract(NEW.data_json, '$.scope_type') = 'subproject'
      AND NOT EXISTS (
        SELECT 1 FROM documents parent
        WHERE parent.id = json_extract(NEW.data_json, '$.parent_project_id')
          AND parent.type = 'project' AND parent.status = 'active'
          AND json_extract(parent.data_json, '$.scope_type') = 'independent'
      )
      THEN RAISE(ABORT, 'subproject parent must be an active independent project')
  END;
END;

CREATE TRIGGER scoped_task_validate_insert
BEFORE INSERT ON tasks
WHEN NEW.type IN ('knowledge_task', 'standalone_task')
 AND coalesce(json_extract(NEW.data_json, '$.handoff.kind'), '') <> 'codex_engineering'
BEGIN
  SELECT CASE
    WHEN json_type(NEW.data_json, '$.project_id') IS NOT 'text'
      THEN RAISE(ABORT, 'new task requires project scope')
    WHEN NOT EXISTS (
      SELECT 1 FROM documents project
      WHERE project.id = json_extract(NEW.data_json, '$.project_id')
        AND project.type = 'project' AND project.status = 'active'
        AND coalesce(json_extract(project.data_json, '$.scope_type'), 'independent') = 'independent'
    ) THEN RAISE(ABORT, 'task project must be an active independent project')
    WHEN json_type(NEW.data_json, '$.subproject_id') IS NOT NULL AND NOT EXISTS (
      SELECT 1 FROM documents child
      WHERE child.id = json_extract(NEW.data_json, '$.subproject_id')
        AND child.type = 'project' AND child.status = 'active'
        AND json_extract(child.data_json, '$.scope_type') = 'subproject'
        AND json_extract(child.data_json, '$.parent_project_id') = json_extract(NEW.data_json, '$.project_id')
    ) THEN RAISE(ABORT, 'task subproject must belong to its project')
  END;
END;

CREATE TRIGGER scoped_entry_validate_insert
BEFORE INSERT ON documents
WHEN NEW.type = 'knowledge_entry'
BEGIN
  SELECT CASE
    WHEN json_type(NEW.data_json, '$.project_id') IS NOT 'text'
      THEN RAISE(ABORT, 'new knowledge entry requires project scope')
    WHEN NOT EXISTS (
      SELECT 1 FROM documents project
      WHERE project.id = json_extract(NEW.data_json, '$.project_id')
        AND project.type = 'project' AND project.status = 'active'
        AND coalesce(json_extract(project.data_json, '$.scope_type'), 'independent') = 'independent'
    ) THEN RAISE(ABORT, 'knowledge entry project must be an active independent project')
    WHEN json_type(NEW.data_json, '$.subproject_id') IS NOT NULL AND NOT EXISTS (
      SELECT 1 FROM documents child
      WHERE child.id = json_extract(NEW.data_json, '$.subproject_id')
        AND child.type = 'project' AND child.status = 'active'
        AND json_extract(child.data_json, '$.scope_type') = 'subproject'
        AND json_extract(child.data_json, '$.parent_project_id') = json_extract(NEW.data_json, '$.project_id')
    ) THEN RAISE(ABORT, 'knowledge entry subproject must belong to its project')
  END;
END;

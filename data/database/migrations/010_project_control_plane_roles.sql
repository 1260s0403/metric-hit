PRAGMA foreign_keys = ON;

-- The control plane and the projects it manages are different roles, not
-- parent/child project records. Stable IDs and every existing object scope are
-- preserved; only the two bootstrap project records and one superseded phrase
-- in the mixed legacy task are corrected.
DROP TRIGGER project_scope_validate_insert;
DROP TRIGGER project_scope_validate_update;
DROP TRIGGER scoped_task_validate_insert;
DROP TRIGGER scoped_entry_validate_insert;

UPDATE documents
SET title = 'Ядро',
    content = 'Основной проект и control plane системы.',
    data_json = json_set(data_json, '$.scope_type', 'control_plane'),
    updated_at = '2026-08-17T18:00:00.000Z',
    version = version + 1
WHERE id = '00000000-0000-4000-a000-000000000101'
  AND type = 'project';

UPDATE documents
SET content = 'Первый проект внутри системы под управлением «Ядра».',
    data_json = json_set(data_json, '$.scope_type', 'managed_project', '$.managed_by', 'yadro'),
    updated_at = '2026-08-17T18:00:00.000Z',
    version = version + 1
WHERE id = '00000000-0000-4000-a000-000000000102'
  AND type = 'project';

UPDATE tasks
SET content = replace(
      content,
      'Разделение: ядро - самостоятельный проект. а метрикхит это подпроект в нем',
      'Разделение: «Ядро» — основной control plane; MetricHit — первый проект внутри системы под его управлением, а не подпроект'
    ),
    updated_at = '2026-08-17T18:00:00.000Z',
    version = version + 1
WHERE id = 'a1023db2-32d7-4286-b635-03c27fef6a35'
  AND content LIKE '%метрикхит это подпроект в нем%';

INSERT OR IGNORE INTO audit_log
  (id, type, title, data_json, author, created_at, updated_at, access_level,
   version, entity_type, entity_id, action)
VALUES
  ('00000000-0000-4000-a010-000000000101', 'project_change',
   'Роль «Ядра» уточнена',
   '{"new":{"name":"Ядро","scope_type":"control_plane"},"old":{"name":"Развитие Ядра","scope_type":"independent"}}',
   'owner', '2026-08-17T18:00:00.000Z', '2026-08-17T18:00:00.000Z',
   'restricted', 1, 'project', '00000000-0000-4000-a000-000000000101', 'update'),
  ('00000000-0000-4000-a010-000000000102', 'project_change',
   'Роль MetricHit уточнена',
   '{"new":{"scope_type":"managed_project"},"old":{"scope_type":"independent"}}',
   'owner', '2026-08-17T18:00:00.000Z', '2026-08-17T18:00:00.000Z',
   'restricted', 1, 'project', '00000000-0000-4000-a000-000000000102', 'update'),
  ('00000000-0000-4000-a010-000000000103', 'task_change',
   'Граница «Ядра» и MetricHit уточнена',
   '{"new":{"wording":"MetricHit is a managed project, not a subproject"},"old":{"wording":"MetricHit is a subproject"}}',
   'owner', '2026-08-17T18:00:00.000Z', '2026-08-17T18:00:00.000Z',
   'restricted', 1, 'task', 'a1023db2-32d7-4286-b635-03c27fef6a35', 'update');

CREATE TRIGGER project_scope_validate_insert
BEFORE INSERT ON documents
WHEN NEW.type = 'project'
BEGIN
  SELECT CASE
    WHEN json_extract(NEW.data_json, '$.scope_type') NOT IN ('control_plane', 'managed_project', 'subproject')
      THEN RAISE(ABORT, 'project scope_type must be control_plane, managed_project, or subproject')
    WHEN json_extract(NEW.data_json, '$.scope_type') IN ('control_plane', 'managed_project')
      AND json_type(NEW.data_json, '$.parent_project_id') IS NOT NULL
      THEN RAISE(ABORT, 'top-level project cannot have a parent')
    WHEN json_extract(NEW.data_json, '$.scope_type') = 'subproject'
      AND NOT EXISTS (
        SELECT 1 FROM documents parent
        WHERE parent.id = json_extract(NEW.data_json, '$.parent_project_id')
          AND parent.type = 'project' AND parent.status = 'active'
          AND json_extract(parent.data_json, '$.scope_type') IN ('control_plane', 'managed_project')
      )
      THEN RAISE(ABORT, 'subproject parent must be an active top-level project')
  END;
END;

CREATE TRIGGER project_scope_validate_update
BEFORE UPDATE OF data_json, status ON documents
WHEN NEW.type = 'project'
BEGIN
  SELECT CASE
    WHEN json_extract(NEW.data_json, '$.scope_type') NOT IN ('control_plane', 'managed_project', 'subproject')
      THEN RAISE(ABORT, 'project scope_type must be control_plane, managed_project, or subproject')
    WHEN json_extract(NEW.data_json, '$.scope_type') IN ('control_plane', 'managed_project')
      AND json_type(NEW.data_json, '$.parent_project_id') IS NOT NULL
      THEN RAISE(ABORT, 'top-level project cannot have a parent')
    WHEN json_extract(NEW.data_json, '$.scope_type') = 'subproject'
      AND NOT EXISTS (
        SELECT 1 FROM documents parent
        WHERE parent.id = json_extract(NEW.data_json, '$.parent_project_id')
          AND parent.type = 'project' AND parent.status = 'active'
          AND json_extract(parent.data_json, '$.scope_type') IN ('control_plane', 'managed_project')
      )
      THEN RAISE(ABORT, 'subproject parent must be an active top-level project')
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
        AND json_extract(project.data_json, '$.scope_type') IN ('control_plane', 'managed_project')
    ) THEN RAISE(ABORT, 'task project must be an active top-level project')
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
        AND json_extract(project.data_json, '$.scope_type') IN ('control_plane', 'managed_project')
    ) THEN RAISE(ABORT, 'knowledge entry project must be an active top-level project')
    WHEN json_type(NEW.data_json, '$.subproject_id') IS NOT NULL AND NOT EXISTS (
      SELECT 1 FROM documents child
      WHERE child.id = json_extract(NEW.data_json, '$.subproject_id')
        AND child.type = 'project' AND child.status = 'active'
        AND json_extract(child.data_json, '$.scope_type') = 'subproject'
        AND json_extract(child.data_json, '$.parent_project_id') = json_extract(NEW.data_json, '$.project_id')
    ) THEN RAISE(ABORT, 'knowledge entry subproject must belong to its project')
  END;
END;

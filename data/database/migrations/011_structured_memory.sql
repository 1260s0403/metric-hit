PRAGMA foreign_keys = ON;

CREATE TABLE scope_passports (
    id TEXT PRIMARY KEY,
    scope_kind TEXT NOT NULL CHECK (scope_kind IN ('core', 'project', 'subproject', 'task')),
    parent_scope_id TEXT REFERENCES scope_passports(id) ON DELETE RESTRICT,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    summary TEXT NOT NULL CHECK (length(trim(summary)) > 0),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json) AND json_type(metadata_json) = 'object'),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK ((scope_kind = 'core' AND parent_scope_id IS NULL) OR (scope_kind <> 'core' AND parent_scope_id IS NOT NULL))
);

CREATE UNIQUE INDEX scope_passports_one_active_core
    ON scope_passports(scope_kind) WHERE scope_kind = 'core' AND status = 'active';

CREATE TRIGGER scope_passports_validate_hierarchy_insert
BEFORE INSERT ON scope_passports
WHEN NEW.scope_kind <> 'core'
BEGIN
  SELECT CASE
    WHEN NOT EXISTS (SELECT 1 FROM scope_passports p WHERE p.id=NEW.parent_scope_id AND p.status='active')
      THEN RAISE(ABORT, 'scope parent must be active')
    WHEN NEW.scope_kind='project' AND NOT EXISTS (SELECT 1 FROM scope_passports p WHERE p.id=NEW.parent_scope_id AND p.scope_kind='core')
      THEN RAISE(ABORT, 'project parent must be core')
    WHEN NEW.scope_kind='subproject' AND NOT EXISTS (SELECT 1 FROM scope_passports p WHERE p.id=NEW.parent_scope_id AND p.scope_kind='project')
      THEN RAISE(ABORT, 'subproject parent must be project')
    WHEN NEW.scope_kind='task' AND NOT EXISTS (SELECT 1 FROM scope_passports p WHERE p.id=NEW.parent_scope_id AND p.scope_kind IN ('project','subproject'))
      THEN RAISE(ABORT, 'task parent must be project or subproject')
  END;
END;

CREATE TABLE scoped_memory_records (
    id TEXT PRIMARY KEY,
    semantic_key TEXT NOT NULL CHECK (length(trim(semantic_key)) > 0),
    scope_id TEXT NOT NULL REFERENCES scope_passports(id) ON DELETE RESTRICT,
    layer TEXT NOT NULL CHECK (layer IN ('permanent', 'working', 'historical')),
    record_type TEXT NOT NULL CHECK (record_type IN ('rule', 'decision', 'fact', 'commitment')),
    lifecycle_status TEXT NOT NULL CHECK (lifecycle_status IN ('active', 'superseded', 'outdated', 'needs_review', 'historical')),
    title TEXT NOT NULL CHECK (length(trim(title)) > 0),
    content TEXT NOT NULL CHECK (length(trim(content)) > 0),
    source_ref TEXT NOT NULL CHECK (length(trim(source_ref)) > 0),
    valid_from TEXT NOT NULL,
    supersedes_id TEXT REFERENCES scoped_memory_records(id) ON DELETE RESTRICT,
    rule_effect TEXT CHECK (rule_effect IS NULL OR rule_effect IN ('prohibit', 'require', 'allow', 'guidance')),
    task_types_json TEXT NOT NULL DEFAULT '["all"]' CHECK (json_valid(task_types_json) AND json_type(task_types_json) = 'array'),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json) AND json_type(metadata_json) = 'object'),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK ((record_type='rule' AND rule_effect IS NOT NULL) OR (record_type<>'rule' AND rule_effect IS NULL)),
    CHECK ((layer='historical' AND lifecycle_status='historical') OR layer<>'historical')
);

CREATE UNIQUE INDEX scoped_memory_one_active_key_per_scope
    ON scoped_memory_records(scope_id, semantic_key) WHERE lifecycle_status='active';

CREATE TRIGGER scoped_memory_validate_supersedes_insert
BEFORE INSERT ON scoped_memory_records
WHEN NEW.supersedes_id IS NOT NULL
BEGIN
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM scoped_memory_records old
    WHERE old.id=NEW.supersedes_id AND old.scope_id=NEW.scope_id AND old.semantic_key=NEW.semantic_key
  ) THEN RAISE(ABORT, 'supersedes must reference the same scope and semantic key') END;
END;

CREATE TRIGGER scoped_memory_protect_core_prohibition_insert
BEFORE INSERT ON scoped_memory_records
WHEN NEW.lifecycle_status='active' AND coalesce(NEW.rule_effect, '')<>'prohibit'
BEGIN
  SELECT CASE WHEN EXISTS (
    SELECT 1 FROM scoped_memory_records core_record
    JOIN scope_passports core_scope ON core_scope.id=core_record.scope_id
    WHERE core_scope.scope_kind='core' AND core_record.lifecycle_status='active'
      AND core_record.rule_effect='prohibit' AND core_record.semantic_key=NEW.semantic_key
      AND core_record.scope_id<>NEW.scope_id
  ) THEN RAISE(ABORT, 'core prohibition cannot be overridden') END;
END;

CREATE TRIGGER scoped_memory_prevent_delete
BEFORE DELETE ON scoped_memory_records
BEGIN SELECT RAISE(ABORT, 'structured memory cannot be deleted; change lifecycle status'); END;

CREATE TABLE unresolved_memory_queue (
    id TEXT PRIMARY KEY,
    semantic_key TEXT,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    reason TEXT NOT NULL,
    candidate_scope_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'resolved')),
    resolution_scope_id TEXT REFERENCES scope_passports(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    CHECK ((status='pending' AND resolution_scope_id IS NULL AND resolved_at IS NULL) OR
           (status='resolved' AND resolution_scope_id IS NOT NULL AND resolved_at IS NOT NULL))
);

CREATE TRIGGER unresolved_memory_prevent_delete
BEFORE DELETE ON unresolved_memory_queue
BEGIN SELECT RAISE(ABORT, 'unresolved memory queue is append-only'); END;

CREATE TABLE context_packs (
    id TEXT PRIMARY KEY,
    scope_id TEXT NOT NULL REFERENCES scope_passports(id) ON DELETE RESTRICT,
    task_type TEXT NOT NULL,
    compiler_version INTEGER NOT NULL CHECK (compiler_version > 0),
    input_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json) AND json_type(payload_json)='object'),
    compiled_bytes INTEGER NOT NULL CHECK (compiled_bytes > 0),
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    created_at TEXT NOT NULL,
    closed_at TEXT,
    CHECK ((status='open' AND closed_at IS NULL) OR (status='closed' AND closed_at IS NOT NULL))
);

CREATE TRIGGER context_packs_prevent_delete
BEFORE DELETE ON context_packs
BEGIN SELECT RAISE(ABORT, 'context packs cannot be deleted'); END;

CREATE TABLE scope_routing_audit (
    id TEXT PRIMARY KEY,
    task_fingerprint TEXT NOT NULL,
    requested_scope_id TEXT,
    resolved_scope_id TEXT REFERENCES scope_passports(id) ON DELETE RESTRICT,
    task_type TEXT,
    outcome TEXT NOT NULL CHECK (outcome IN ('routed', 'needs_clarification', 'rejected')),
    signals_json TEXT NOT NULL CHECK (json_valid(signals_json) AND json_type(signals_json)='array'),
    context_pack_id TEXT REFERENCES context_packs(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL
);

CREATE TRIGGER scope_routing_audit_prevent_update
BEFORE UPDATE ON scope_routing_audit
BEGIN SELECT RAISE(ABORT, 'scope routing audit is immutable'); END;

CREATE TRIGGER scope_routing_audit_prevent_delete
BEFORE DELETE ON scope_routing_audit
BEGIN SELECT RAISE(ABORT, 'scope routing audit is immutable'); END;

INSERT INTO scope_passports(id,scope_kind,parent_scope_id,name,summary,status,metadata_json,created_at,updated_at) VALUES
 ('scope:core','core',NULL,'Ядро','Управляющий контур, общие ограничения и правила Strategy.','active','{"aliases":["ядро","core"]}','2026-08-31T08:00:00.000Z','2026-08-31T08:00:00.000Z'),
 ('scope:project:metrichit','project','scope:core','MetricHit','Управляемый проект MetricHit и его общая бизнес-истина.','active','{"aliases":["metrichit","метрикхит"]}','2026-08-31T08:00:00.000Z','2026-08-31T08:00:00.000Z'),
 ('scope:subproject:editorial','subproject','scope:project:metrichit','Редакция','Статьи и social-материалы MetricHit.','active','{"aliases":["редакция","статья","контент","social"]}','2026-08-31T08:00:00.000Z','2026-08-31T08:00:00.000Z'),
 ('scope:subproject:panel','subproject','scope:project:metrichit','Панель','Operator panel MetricHit, её backend и интерфейс.','active','{"aliases":["панель","operator panel","ui"]}','2026-08-31T08:00:00.000Z','2026-08-31T08:00:00.000Z');

INSERT INTO scoped_memory_records(id,semantic_key,scope_id,layer,record_type,lifecycle_status,title,content,source_ref,valid_from,supersedes_id,rule_effect,task_types_json,metadata_json,created_at,updated_at) VALUES
 ('memory:core:owner-gates','governance.owner_gates','scope:core','permanent','rule','active','Owner-gates','Удаление, force-операции, публикация, расходы, доступы, стратегия, политика памяти, системные настройки и расширение scope требуют отдельного решения владельца.','AGENTS.md','2026-08-31T08:00:00.000Z',NULL,'prohibit','["all"]','{}','2026-08-31T08:00:00.000Z','2026-08-31T08:00:00.000Z'),
 ('memory:core:strategy','governance.strategy_role','scope:core','permanent','rule','active','Роль Strategy','Strategy является read-only human-facing router; repository меняет один named executor.','AGENTS.md','2026-08-31T08:00:00.000Z',NULL,'require','["all"]','{}','2026-08-31T08:00:00.000Z','2026-08-31T08:00:00.000Z'),
 ('memory:metrichit:boundary','architecture.metrichit_boundary','scope:project:metrichit','permanent','decision','active','Граница MetricHit','MetricHit — managed project под управлением «Ядра», а не sibling control plane.','knowledge/approved/current-context.md','2026-08-31T08:00:00.000Z',NULL,NULL,'["all"]','{}','2026-08-31T08:00:00.000Z','2026-08-31T08:00:00.000Z'),
 ('memory:editorial:separation','editorial.channel_separation','scope:subproject:editorial','permanent','rule','active','Разделение каналов','Landing, articles и SMM хранятся в своих контурах; опубликованным считается только подтверждённый материал.','AGENTS.md','2026-08-31T08:00:00.000Z',NULL,'require','["editorial"]','{}','2026-08-31T08:00:00.000Z','2026-08-31T08:00:00.000Z'),
 ('memory:editorial:research','editorial.next_research_mvp','scope:subproject:editorial','working','commitment','active','Следующий этап редакции','On-demand research-MVP остаётся следующим незавершённым редакционным этапом; monitoring и автопубликация не входят в него.','documents/roadmap.md','2026-08-31T08:00:00.000Z',NULL,NULL,'["editorial"]','{}','2026-08-31T08:00:00.000Z','2026-08-31T08:00:00.000Z'),
 ('memory:panel:contract','panel.ux_contract_required','scope:subproject:panel','permanent','rule','active','UX-контракт панели','Перед изменением operator panel обязателен documents/operator-panel-ux-contract.md и относящийся E2E.','AGENTS.md','2026-08-31T08:00:00.000Z',NULL,'require','["ui"]','{}','2026-08-31T08:00:00.000Z','2026-08-31T08:00:00.000Z');

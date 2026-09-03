import { createHash } from 'node:crypto';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabase = join(root, 'data', 'database', 'metrichit.db');
const owner = 'owner';
const approvedAt = '2026-09-02T00:00:00.000Z';
const sourceRef = 'direct owner approval 2026-09-02';
const metrichitProjectId = '00000000-0000-4000-a000-000000000102';
const departmentScopeId = 'scope:subproject:automation';
const departmentProjectId = 'a9f37b82-0ab9-4e7d-83c5-17c6b9136bf0';
const semanticKey = 'automation.department_registration';
const avitoStartupSemanticKey = 'automation.avito.startup_context';
const avitoScopeId = 'scope:task:automation:avito';
const avitoApprovedAt = '2026-09-03T00:00:00.000Z';
const avitoSourceRef = 'direct owner approval 2026-09-03: create isolated Avito scope';
const avitoStartupRevision = 2;
const avitoStartupSourceId = stableUuid(`avito-startup-context-source-revision-${avitoStartupRevision}`);
const avitoStartupDocumentId = stableUuid(`avito-startup-context-document-revision-${avitoStartupRevision}`);
const avitoStartupVersionId = stableUuid(`avito-startup-context-version-revision-${avitoStartupRevision}`);
const avitoStartupCandidateId = stableUuid(`avito-startup-context-candidate-revision-${avitoStartupRevision}`);
const legacyAvitoStartupCandidateId = stableUuid('avito-startup-context-candidate');

function stableUuid(key) {
  const hex = createHash('sha256').update(`metrichit-automation-department:${key}`).digest('hex');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
}

function assertFields(row, expected, label) {
  if (!row) throw new Error(`Missing ${label}`);
  for (const [field, value] of Object.entries(expected)) {
    if (row[field] !== value) throw new Error(`${label}.${field} differs`);
  }
}

function ensureScopedRecord(database, record) {
  const existing = database.prepare('SELECT * FROM scoped_memory_records WHERE id=?').get(record.id);
  if (!existing) {
    database.prepare(`INSERT INTO scoped_memory_records
      (id,semantic_key,scope_id,layer,record_type,lifecycle_status,title,content,source_ref,valid_from,supersedes_id,rule_effect,task_types_json,metadata_json,created_at,updated_at)
      VALUES (?,?,?,?,?,'active',?,?,?,?,NULL,?,?,?,?,?)`).run(
      record.id, record.semanticKey, departmentScopeId, record.layer, record.recordType,
      record.title, record.content, sourceRef, approvedAt, record.ruleEffect,
      JSON.stringify(['all']), JSON.stringify({ authority: 'direct_owner_confirmation' }), approvedAt, approvedAt,
    );
  }
  assertFields(database.prepare('SELECT * FROM scoped_memory_records WHERE id=?').get(record.id), {
    semantic_key: record.semanticKey, scope_id: departmentScopeId, layer: record.layer,
    record_type: record.recordType, lifecycle_status: 'active', title: record.title,
    content: record.content, source_ref: sourceRef, rule_effect: record.ruleEffect,
  }, `scoped record ${record.semanticKey}`);
}

function ensureAvitoScopedRecord(database, record) {
  const existing = database.prepare('SELECT * FROM scoped_memory_records WHERE id=?').get(record.id);
  if (!existing) {
    database.prepare(`INSERT INTO scoped_memory_records
      (id,semantic_key,scope_id,layer,record_type,lifecycle_status,title,content,source_ref,valid_from,supersedes_id,rule_effect,task_types_json,metadata_json,created_at,updated_at)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`).run(
      record.id, record.semanticKey, avitoScopeId, record.layer, record.recordType, 'active',
      record.title, record.content, avitoSourceRef, avitoApprovedAt, null, record.ruleEffect,
      JSON.stringify(['all']), JSON.stringify({ authority: 'direct_owner_confirmation', platform: 'avito', working_root: 'work/automation/avito' }), avitoApprovedAt, avitoApprovedAt,
    );
  }
  assertFields(database.prepare('SELECT * FROM scoped_memory_records WHERE id=?').get(record.id), {
    semantic_key: record.semanticKey, scope_id: avitoScopeId, layer: record.layer,
    record_type: record.recordType, lifecycle_status: 'active', title: record.title,
    content: record.content, source_ref: avitoSourceRef, rule_effect: record.ruleEffect,
  }, `Avito scoped record ${record.semanticKey}`);
}

export function applyAvitoScope(databasePath = defaultDatabase) {
  const database = new DatabaseSync(databasePath);
  const created = { scope: 0, scopedRecords: 0, supersededRecords: 0, sources: 0, documents: 0, versions: 0, candidates: 0 };
  const passportMetadata = JSON.stringify({
    aliases: ['авито', 'avito'],
    working_root: 'work/automation/avito',
    platform_access_authorized: false,
    separate_database: false,
  });
  const registrationContent = '«Авито» — активный изолированный дочерний scope MetricHit → Автоматизация. Его единственный разрешённый рабочий корень — work/automation/avito. Память и материалы Авито не смешиваются с Freelance.ru и другими площадками.';
  const boundaryContent = 'Авито использует только work/automation/avito и собственную scoped memory. Материалы, правила, сессии и доступы Freelance.ru и других площадок не применяются к Авито и не читаются без отдельной прямой зависимости. В этом scope не разрешены доступ к площадке, login, запуск сценариев, scheduler, отправка форм, публикация, секреты, cookies, local session, отдельная база данных, schema или migration.';
  const startupTitle = 'Контур «Авито» в Автоматизации';
  const startupContent = 'MetricHit → Автоматизация → Авито — активный изолированный scope с единственным рабочим корнем work/automation/avito. На паузе только внешние действия на площадке: до отдельной прямой задачи владельца запрещены доступ к Авито, login, scheduler, отправка форм и публикация. Секреты, cookies, local sessions, отдельная база данных, schema и migrations также не разрешены.';
  const startupData = JSON.stringify({
    revision: avitoStartupRevision,
    supersedes_semantic_revisions: [0],
    scope_id: avitoScopeId,
    working_root: 'work/automation/avito',
    platform_access_authorized: false,
    login_authorized: false,
    scheduler_authorized: false,
    forms_authorized: false,
    publication_authorized: false,
    secrets_or_sessions_authorized: false,
    separate_database_or_schema_authorized: false,
  });
  database.exec('PRAGMA foreign_keys=ON; BEGIN IMMEDIATE;');
  try {
    if (!database.prepare("SELECT id FROM scope_passports WHERE id=? AND status='active'").get(departmentScopeId)) {
      throw new Error('Automation scope is not active');
    }
    created.scope += Number(database.prepare(`INSERT OR IGNORE INTO scope_passports
      (id,scope_kind,parent_scope_id,name,summary,status,metadata_json,created_at,updated_at)
      VALUES (?,'task',?,'Авито',?,'active',?,?,?)`).run(
      avitoScopeId, departmentScopeId, 'Изолированный контур Авито без доступа к площадке.', passportMetadata, avitoApprovedAt, avitoApprovedAt,
    ).changes);
    assertFields(database.prepare('SELECT * FROM scope_passports WHERE id=?').get(avitoScopeId), {
      scope_kind: 'task', parent_scope_id: departmentScopeId, name: 'Авито',
      summary: 'Изолированный контур Авито без доступа к площадке.', status: 'active', metadata_json: passportMetadata,
    }, 'Avito scope passport');

    const existingRecords = database.prepare('SELECT count(*) AS count FROM scoped_memory_records WHERE id IN (?,?)').get(
      'memory:automation:avito:registration', 'memory:automation:avito:boundaries',
    ).count;
    ensureAvitoScopedRecord(database, {
      id: 'memory:automation:avito:registration', semanticKey: 'automation.avito.registration',
      layer: 'permanent', recordType: 'decision', ruleEffect: null,
      title: 'Изолированный scope «Авито»', content: registrationContent,
    });
    ensureAvitoScopedRecord(database, {
      id: 'memory:automation:avito:boundaries', semanticKey: 'automation.avito.isolation',
      layer: 'permanent', recordType: 'rule', ruleEffect: 'require',
      title: 'Границы scope «Авито»', content: boundaryContent,
    });
    created.scopedRecords = 2 - Number(existingRecords);

    const superseded = database.prepare('SELECT * FROM scoped_memory_records WHERE id=?').get('memory:automation:platform-design');
    const current = database.prepare('SELECT * FROM scoped_memory_records WHERE id=?').get('memory:automation:platform-design-avito-created');
    if (!current) {
      if (!superseded || superseded.lifecycle_status !== 'active') throw new Error('Automation platform design record is not active');
      database.prepare("UPDATE scoped_memory_records SET lifecycle_status='superseded',updated_at=? WHERE id=? AND lifecycle_status='active'")
        .run(avitoApprovedAt, superseded.id);
      database.prepare(`INSERT INTO scoped_memory_records
        (id,semantic_key,scope_id,layer,record_type,lifecycle_status,title,content,source_ref,valid_from,supersedes_id,rule_effect,task_types_json,metadata_json,created_at,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`).run(
        'memory:automation:platform-design-avito-created', 'automation.platform_scope_design',
        departmentScopeId, 'working', 'decision', 'active', 'Площадочные направления автоматизации',
        'Freelance.ru, FL.ru и Kwork остаются будущими самостоятельными направлениями. Авито создан как отдельный активный изолированный scope с рабочим корнем work/automation/avito; доступ к площадке, сценарии и публикация не разрешены.',
        avitoSourceRef, avitoApprovedAt, superseded.id, null,
        JSON.stringify(['all']), JSON.stringify({ authority: 'direct_owner_confirmation', avito_scope_id: avitoScopeId }), avitoApprovedAt, avitoApprovedAt,
      );
      created.supersededRecords = 1;
    }
    assertFields(database.prepare('SELECT * FROM scoped_memory_records WHERE id=?').get('memory:automation:platform-design-avito-created'), {
      semantic_key: 'automation.platform_scope_design', scope_id: departmentScopeId, layer: 'working', record_type: 'decision', lifecycle_status: 'active',
      supersedes_id: 'memory:automation:platform-design', source_ref: avitoSourceRef,
    }, 'Avito platform design evolution');

    const existingRevisions = database.prepare(`SELECT id,coalesce(json_extract(data_json, '$.revision'), 0) AS revision
      FROM memory_candidates WHERE semantic_key=? AND status IN ('pending','approved') AND id<>?`)
      .all(avitoStartupSemanticKey, avitoStartupCandidateId);
    const revisions = existingRevisions.map((row) => Number(row.revision)).sort((left, right) => left - right);
    if (revisions.some((revision) => ![0, 1].includes(revision))) {
      throw new Error(`Unexpected semantic revision blocks ${semanticKey}: ${revisions.join(',')}`);
    }
    const sourceData = JSON.stringify({ authority: 'direct_owner_confirmation', approved_at: avitoApprovedAt, scope_id: avitoScopeId });
    created.sources += Number(database.prepare(`INSERT OR IGNORE INTO sources
      (id,type,title,content,data_json,status,author,valid_at,access_level)
      VALUES (?,'owner_decision',?,?,?,'active',?,'2026-09-03','internal')`).run(
      avitoStartupSourceId, startupTitle, avitoSourceRef, sourceData, owner,
    ).changes);
    created.documents += Number(database.prepare(`INSERT OR IGNORE INTO documents
      (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version)
      VALUES (?,'owner_decision',?,?,?,'active',?,?,'2026-09-03','internal',1)`).run(
      avitoStartupDocumentId, startupTitle, startupContent, startupData, avitoStartupSourceId, owner,
    ).changes);
    created.versions += Number(database.prepare(`INSERT OR IGNORE INTO document_versions
      (id,document_id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version)
      VALUES (?,?,'owner_decision',?,?,?,'active',?,?,'2026-09-03','internal',1)`).run(
      avitoStartupVersionId, avitoStartupDocumentId, startupTitle, startupContent, startupData, avitoStartupSourceId, owner,
    ).changes);
    created.candidates += Number(database.prepare(`INSERT OR IGNORE INTO memory_candidates
      (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version)
      VALUES (?,'decision',?,?,?,?, 'pending',?,'owner','2026-09-03','internal',1)`).run(
      avitoStartupCandidateId, avitoStartupSemanticKey, startupTitle, startupContent, startupData, avitoStartupSourceId,
    ).changes);
    if (database.prepare('SELECT status FROM memory_candidates WHERE id=?').get(avitoStartupCandidateId)?.status === 'pending') {
      database.prepare(`UPDATE memory_candidates SET status='approved',reviewed_by=?,reviewed_at=?,review_note=?,updated_at=?,version=version+1 WHERE id=?`).run(
        owner, avitoApprovedAt, 'Одобрено прямой командой владельца синхронизировать startup context с созданным scope «Авито».', avitoApprovedAt, avitoStartupCandidateId,
      );
    }
    assertFields(database.prepare('SELECT * FROM memory_candidates WHERE id=?').get(avitoStartupCandidateId), {
      type: 'decision', semantic_key: avitoStartupSemanticKey, title: startupTitle, content: startupContent, data_json: startupData,
      status: 'approved', source_id: avitoStartupSourceId, reviewed_by: owner, reviewed_at: avitoApprovedAt,
    }, 'Avito startup-context decision');

    database.exec('COMMIT');
    return { databasePath, avitoScopeId, created };
  } catch (error) {
    database.exec('ROLLBACK');
    throw error;
  } finally {
    database.close();
  }
}

export function applyAutomationDepartment(databasePath = defaultDatabase) {
  const title = 'Отдел «Автоматизация» MetricHit';
  const content = 'В MetricHit создан отдельный отдел «Автоматизация» для будущих рабочих направлений Freelance.ru, FL.ru, Kwork, Avito и других площадок. Отдел имеет изолированную scoped memory в цепочке «Ядро → MetricHit → Автоматизация». Рабочие материалы площадки размещаются только по пути work/automation/<platform>. Секреты, локальные сессии, токены, cookies и клиентские данные не хранятся в repository. Создание площадочного контура, login, запуск сценария или внешняя публикация не входят в регистрацию отдела и требуют отдельного утверждённого scope.';
  const data = JSON.stringify({
    department: 'automation',
    parent_project_id: metrichitProjectId,
    scope_id: departmentScopeId,
    project_id: departmentProjectId,
    working_root: 'work/automation',
    planned_platforms: ['freelance-ru', 'fl-ru', 'kwork', 'avito'],
    platform_scopes_created: false,
    secrets_in_repository: false,
    login_or_publication_authorized: false,
  });
  const sourceId = stableUuid('source');
  const documentId = stableUuid('document');
  const versionId = stableUuid('version');
  const candidateId = stableUuid('candidate');
  const database = new DatabaseSync(databasePath);
  const created = { projects: 0, scopes: 0, sources: 0, documents: 0, versions: 0, candidates: 0, scopedRecords: 0 };

  database.exec('PRAGMA foreign_keys=ON; BEGIN IMMEDIATE;');
  try {
    const existing = database.prepare("SELECT id,status FROM memory_candidates WHERE semantic_key=? AND status IN ('pending','approved') AND id NOT IN (?,?,?)").all(semanticKey, candidateId, legacyAvitoStartupCandidateId, avitoStartupCandidateId);
    if (existing.length) throw new Error(`Semantic duplicate or evolution requires review for ${semanticKey}`);

    created.projects += Number(database.prepare(`INSERT OR IGNORE INTO documents
      (id,type,title,content,data_json,status,author,valid_at,access_level,version)
      VALUES (?,'project',?,?,?,'active',?,'2026-09-02','internal',1)`).run(
      departmentProjectId, title, 'Подпроект MetricHit для безопасной подготовки и сопровождения автоматизаций площадок.',
      JSON.stringify({ kind: 'project', parent_project_id: metrichitProjectId, scope_type: 'subproject' }), owner,
    ).changes);
    assertFields(database.prepare('SELECT * FROM documents WHERE id=?').get(departmentProjectId), {
      type: 'project', title, status: 'active',
      data_json: JSON.stringify({ kind: 'project', parent_project_id: metrichitProjectId, scope_type: 'subproject' }),
    }, 'automation department project');

    created.scopes += Number(database.prepare(`INSERT OR IGNORE INTO scope_passports
      (id,scope_kind,parent_scope_id,name,summary,status,metadata_json,created_at,updated_at)
      VALUES (?,'subproject','scope:project:metrichit','Автоматизация',?,'active',?,?,?)`).run(
      departmentScopeId, 'Автоматизация публикационных и иных площадочных сценариев MetricHit.',
      JSON.stringify({ aliases: ['автоматизация', 'automation', 'freelance.ru', 'fl.ru', 'kwork', 'авито', 'avito'], working_root: 'work/automation' }), approvedAt, approvedAt,
    ).changes);
    assertFields(database.prepare('SELECT * FROM scope_passports WHERE id=?').get(departmentScopeId), {
      scope_kind: 'subproject', parent_scope_id: 'scope:project:metrichit', name: 'Автоматизация', status: 'active',
    }, 'automation scope passport');

    created.sources += Number(database.prepare(`INSERT OR IGNORE INTO sources
      (id,type,title,content,data_json,status,author,valid_at,access_level)
      VALUES (?,'owner_decision',?,?,?,'active',?,'2026-09-02','internal')`).run(
      sourceId, title, sourceRef, JSON.stringify({ authority: 'direct_owner_confirmation', approved_at: approvedAt }), owner,
    ).changes);
    created.documents += Number(database.prepare(`INSERT OR IGNORE INTO documents
      (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version)
      VALUES (?,'owner_decision',?,?,?,'active',?,?,'2026-09-02','internal',1)`).run(
      documentId, title, content, data, sourceId, owner,
    ).changes);
    created.versions += Number(database.prepare(`INSERT OR IGNORE INTO document_versions
      (id,document_id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version)
      VALUES (?,?,'owner_decision',?,?,?,'active',?,?,'2026-09-02','internal',1)`).run(
      versionId, documentId, title, content, data, sourceId, owner,
    ).changes);
    created.candidates += Number(database.prepare(`INSERT OR IGNORE INTO memory_candidates
      (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version)
      VALUES (?,'decision',?,?,?,?,'pending',?,?,'2026-09-02','internal',1)`).run(
      candidateId, semanticKey, title, content, data, sourceId, owner,
    ).changes);
    if (database.prepare('SELECT status FROM memory_candidates WHERE id=?').get(candidateId)?.status === 'pending') {
      database.prepare(`UPDATE memory_candidates SET status='approved',reviewed_by=?,reviewed_at=?,review_note=?,updated_at=?,version=version+1 WHERE id=?`).run(
        owner, approvedAt, 'Одобрено прямой командой владельца создать отдел «Автоматизация».', approvedAt, candidateId,
      );
    }
    assertFields(database.prepare('SELECT * FROM memory_candidates WHERE id=?').get(candidateId), {
      type: 'decision', semantic_key: semanticKey, title, content, data_json: data, status: 'approved',
      source_id: sourceId, reviewed_by: owner, reviewed_at: approvedAt,
    }, 'automation department decision');

    const recordCountBefore = database.prepare('SELECT count(*) AS count FROM scoped_memory_records WHERE id IN (?,?,?)').get(
      'memory:automation:registration', 'memory:automation:boundaries', 'memory:automation:platform-design',
    ).count;
    ensureScopedRecord(database, {
      id: 'memory:automation:registration', semanticKey, layer: 'permanent', recordType: 'decision', ruleEffect: null,
      title, content,
    });
    ensureScopedRecord(database, {
      id: 'memory:automation:boundaries', semanticKey: 'automation.operating_boundaries', layer: 'permanent', recordType: 'rule', ruleEffect: 'require',
      title: 'Границы автоматизации',
      content: 'Рабочие материалы площадки размещаются только в work/automation/<platform>. Секреты, локальные сессии, токены, cookies и клиентские данные исключены из repository. Login, запуск сценариев, отправка форм и внешняя публикация требуют отдельного утверждённого scope владельца.',
    });
    if (!database.prepare('SELECT id FROM scoped_memory_records WHERE id=?').get('memory:automation:platform-design-avito-created')) {
      ensureScopedRecord(database, {
        id: 'memory:automation:platform-design', semanticKey: 'automation.platform_scope_design', layer: 'working', recordType: 'decision', ruleEffect: null,
        title: 'Будущие площадочные направления',
        content: 'Freelance.ru, FL.ru, Kwork и Avito — будущие самостоятельные рабочие направления отдела. Сейчас они не созданы как scope и не имеют файлов, сценариев или доступов. Для каждой площадки будущая отдельная задача определяет точный scope, изолированную память, разрешённые пути и проверки без изменения других площадок.',
      });
    }
    created.scopedRecords = 3 - Number(recordCountBefore);

    database.exec('COMMIT');
    return { databasePath, departmentScopeId, departmentProjectId, candidateId, created };
  } catch (error) {
    database.exec('ROLLBACK');
    throw error;
  } finally {
    database.close();
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const databasePath = process.argv[2] ? resolve(process.argv[2]) : defaultDatabase;
  console.log(`Applied automation department: ${JSON.stringify(applyAutomationDepartment(databasePath))}`);
  console.log(`Applied Avito scope: ${JSON.stringify(applyAvitoScope(databasePath))}`);
}

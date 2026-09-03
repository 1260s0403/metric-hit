import { createHash } from 'node:crypto';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabase = join(root, 'data', 'database', 'metrichit.db');
const scopeId = 'scope:subproject:automation';
const avitoScopeId = 'scope:task:automation:avito';
const sourceRef = 'direct owner approval 2026-09-02: Freelance.ru commands-only automation';
const approvedAt = '2026-09-02T00:00:00.000Z';
const avitoSourceRef = 'direct owner approval 2026-09-03: Avito access and API policy';
const avitoApprovedAt = '2026-09-03T00:00:00.000Z';
const avitoStartupRevision = 3;

function stableUuid(key) {
  const hex = createHash('sha256').update(`metrichit-freelance-policy:${key}`).digest('hex');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
}

function ensureRecord(database, record) {
  const existing = database.prepare('SELECT * FROM scoped_memory_records WHERE id=?').get(record.id);
  if (!existing) {
    database.prepare(`INSERT INTO scoped_memory_records
      (id,semantic_key,scope_id,layer,record_type,lifecycle_status,title,content,source_ref,valid_from,supersedes_id,rule_effect,task_types_json,metadata_json,created_at,updated_at)
      VALUES (?,?,?,?,?,'active',?,?,?,?,NULL,?,?,?,?,?)`).run(
      record.id, record.semanticKey, record.scopeId, record.layer, record.recordType, record.title, record.content,
      record.sourceRef, record.approvedAt, record.ruleEffect, JSON.stringify(record.taskTypes ?? ['general']), JSON.stringify(record.metadata), record.approvedAt, record.approvedAt,
    );
  }
  const stored = database.prepare('SELECT * FROM scoped_memory_records WHERE id=?').get(record.id);
  for (const [field, value] of Object.entries({ semantic_key: record.semanticKey, scope_id: record.scopeId, layer: record.layer, record_type: record.recordType, lifecycle_status: 'active', title: record.title, content: record.content, source_ref: record.sourceRef, rule_effect: record.ruleEffect })) {
    if (stored?.[field] !== value) throw new Error(`Automation policy record ${record.id}.${field} differs`);
  }
}

function supersedeRecord(database, priorId, record) {
  const current = database.prepare('SELECT * FROM scoped_memory_records WHERE id=?').get(record.id);
  if (!current) {
    const prior = database.prepare("SELECT * FROM scoped_memory_records WHERE id=? AND lifecycle_status='active'").get(priorId);
    if (!prior || prior.semantic_key !== record.semanticKey || prior.scope_id !== record.scopeId) throw new Error(`Active policy record ${priorId} is required`);
    database.prepare("UPDATE scoped_memory_records SET lifecycle_status='superseded',updated_at=? WHERE id=? AND lifecycle_status='active'")
      .run(record.approvedAt, priorId);
    database.prepare(`INSERT INTO scoped_memory_records
      (id,semantic_key,scope_id,layer,record_type,lifecycle_status,title,content,source_ref,valid_from,supersedes_id,rule_effect,task_types_json,metadata_json,created_at,updated_at)
      VALUES (?,?,?,?,?,'active',?,?,?,?,?,?,?,?,?,?)`).run(
      record.id, record.semanticKey, record.scopeId, record.layer, record.recordType, record.title, record.content,
      record.sourceRef, record.approvedAt, priorId, record.ruleEffect, JSON.stringify(record.taskTypes ?? ['all']), JSON.stringify(record.metadata), record.approvedAt, record.approvedAt,
    );
  }
  ensureRecord(database, record);
  if (database.prepare('SELECT supersedes_id FROM scoped_memory_records WHERE id=?').get(record.id)?.supersedes_id !== priorId) {
    throw new Error(`Automation policy record ${record.id} has an invalid supersedes link`);
  }
}

function upsertApprovedAvitoStartupContext(database) {
  const sourceId = stableUuid(`avito-startup-context-source-revision-${avitoStartupRevision}`);
  const documentId = stableUuid(`avito-startup-context-document-revision-${avitoStartupRevision}`);
  const versionId = stableUuid(`avito-startup-context-version-revision-${avitoStartupRevision}`);
  const candidateId = stableUuid(`avito-startup-context-candidate-revision-${avitoStartupRevision}`);
  const title = 'Контур «Авито»: доступ и изменяющие действия';
  const content = 'MetricHit → Автоматизация → Авито — активный изолированный scope с единственным рабочим корнем work/automation/avito. Разрешены local-browser login/access и API integration/use, но доступность API не предполагается. Создание, снятие, редактирование, публикация и любые изменяющие состояние form/API operations допускаются только по последующей точной команде владельца на операцию или пакет. Scheduler, платные услуги и расходы запрещены. Секреты, пароли, tokens, cookies и sessions остаются вне repository.';
  const data = JSON.stringify({ revision: avitoStartupRevision, supersedes_semantic_revisions: [2], scope_id: avitoScopeId, working_root: 'work/automation/avito', platform_access_authorized: true, login_authorized: true, api_integration_authorized: true, api_availability_assumed: false, scheduler_authorized: false, paid_services_or_spending_authorized: false, state_changing_operations_require_direct_command: true, secrets_or_sessions_in_repository_authorized: false });
  const revisions = database.prepare("SELECT coalesce(json_extract(data_json, '$.revision'), 0) AS revision FROM memory_candidates WHERE semantic_key=? AND status IN ('pending','approved') AND id<>?")
    .all('automation.avito.startup_context', candidateId).map((row) => Number(row.revision)).sort((left, right) => left - right);
  if (JSON.stringify(revisions) !== JSON.stringify([2])) throw new Error(`Unexpected Avito startup-context revisions: ${revisions.join(',')}`);
  const sourceData = JSON.stringify({ authority: 'direct_owner_confirmation', approved_at: avitoApprovedAt, scope_id: avitoScopeId });
  database.prepare(`INSERT OR IGNORE INTO sources (id,type,title,content,data_json,status,author,valid_at,access_level)
    VALUES (?,'owner_decision',?,?,?,'active','owner','2026-09-03','internal')`).run(sourceId, title, avitoSourceRef, sourceData);
  database.prepare(`INSERT OR IGNORE INTO documents (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version)
    VALUES (?,'owner_decision',?,?,?,'active',?,'owner','2026-09-03','internal',1)`).run(documentId, title, content, data, sourceId);
  database.prepare(`INSERT OR IGNORE INTO document_versions (id,document_id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version)
    VALUES (?,?,'owner_decision',?,?,?,'active',?,'owner','2026-09-03','internal',1)`).run(versionId, documentId, title, content, data, sourceId);
  database.prepare(`INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version)
    VALUES (?,'decision','automation.avito.startup_context',?,?,?,'pending',?,'owner','2026-09-03','internal',1)`).run(candidateId, title, content, data, sourceId);
  if (database.prepare('SELECT status FROM memory_candidates WHERE id=?').get(candidateId)?.status === 'pending') {
    database.prepare('UPDATE memory_candidates SET status=?,reviewed_by=?,reviewed_at=?,review_note=?,updated_at=?,version=version+1 WHERE id=?')
      .run('approved', 'owner', avitoApprovedAt, 'Одобрено прямой командой владельца: доступ Авито и API разрешены; изменяющие действия только по следующей точной команде.', avitoApprovedAt, candidateId);
  }
  const stored = database.prepare('SELECT * FROM memory_candidates WHERE id=?').get(candidateId);
  for (const [field, value] of Object.entries({ type: 'decision', semantic_key: 'automation.avito.startup_context', title, content, data_json: data, status: 'approved', source_id: sourceId, reviewed_by: 'owner', reviewed_at: avitoApprovedAt })) {
    if (stored?.[field] !== value) throw new Error(`Avito startup-context ${field} differs`);
  }
  return candidateId;
}

function supersedeLegacyAutomationRegistrationContext(database) {
  const semanticKey = 'automation.department_registration';
  const revision = 2;
  const sourceId = stableUuid('automation-registration-avito-policy-source-revision-2');
  const documentId = stableUuid('automation-registration-avito-policy-document-revision-2');
  const versionId = stableUuid('automation-registration-avito-policy-version-revision-2');
  const candidateId = stableUuid('automation-registration-avito-policy-candidate-revision-2');
  const title = 'Отдел «Автоматизация»: контур Авито';
  const content = 'В MetricHit действует отдельный отдел «Автоматизация» с изолированной scoped memory и рабочими корнями work/automation/<platform>. Авито — активный изолированный scope; его действующие доступы и запреты определяются решением «Контур «Авито»: доступ и изменяющие действия». Freelance.ru, FL.ru, Kwork и другие площадки сохраняют собственные прежние ограничения. Секреты, локальные сессии, tokens, cookies и клиентские данные не хранятся в repository.';
  const data = JSON.stringify({ revision, supersedes_semantic_revisions: [1], scope_id: scopeId, avito_scope_id: avitoScopeId, avito_policy_semantic_key: 'automation.avito.startup_context' });
  const revisions = database.prepare("SELECT coalesce(json_extract(data_json, '$.revision'), 0) AS revision FROM memory_candidates WHERE semantic_key=? AND status IN ('pending','approved') AND id<>?")
    .all(semanticKey, candidateId).map((row) => Number(row.revision)).sort((left, right) => left - right);
  if (JSON.stringify(revisions) !== JSON.stringify([0, 1])) throw new Error(`Unexpected automation-registration revisions: ${revisions.join(',')}`);
  const sourceData = JSON.stringify({ authority: 'direct_owner_confirmation', approved_at: avitoApprovedAt, scope_id: scopeId, avito_scope_id: avitoScopeId });
  database.prepare(`INSERT OR IGNORE INTO sources (id,type,title,content,data_json,status,author,valid_at,access_level)
    VALUES (?,'owner_decision',?,?,?,'active','owner','2026-09-03','internal')`).run(sourceId, title, avitoSourceRef, sourceData);
  database.prepare(`INSERT OR IGNORE INTO documents (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version)
    VALUES (?,'owner_decision',?,?,?,'active',?,'owner','2026-09-03','internal',1)`).run(documentId, title, content, data, sourceId);
  database.prepare(`INSERT OR IGNORE INTO document_versions (id,document_id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version)
    VALUES (?,?,'owner_decision',?,?,?,'active',?,'owner','2026-09-03','internal',1)`).run(versionId, documentId, title, content, data, sourceId);
  database.prepare(`INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version)
    VALUES (?,'decision',?,?,?,?, 'pending',?,'owner','2026-09-03','internal',1)`).run(candidateId, semanticKey, title, content, data, sourceId);
  if (database.prepare('SELECT status FROM memory_candidates WHERE id=?').get(candidateId)?.status === 'pending') {
    database.prepare('UPDATE memory_candidates SET status=?,reviewed_by=?,reviewed_at=?,review_note=?,updated_at=?,version=version+1 WHERE id=?')
      .run('approved', 'owner', avitoApprovedAt, 'Одобрено прямой командой владельца: legacy startup-формулировка Авито заменена актуальной политикой.', avitoApprovedAt, candidateId);
  }
  const stored = database.prepare('SELECT * FROM memory_candidates WHERE id=?').get(candidateId);
  for (const [field, value] of Object.entries({ type: 'decision', semantic_key: semanticKey, title, content, data_json: data, status: 'approved', source_id: sourceId, reviewed_by: 'owner', reviewed_at: avitoApprovedAt })) {
    if (stored?.[field] !== value) throw new Error(`Automation registration context ${field} differs`);
  }
  return candidateId;
}

export function applyFreelanceAutomationPolicy(databasePath = defaultDatabase) {
  const database = new DatabaseSync(databasePath);
  database.exec('PRAGMA foreign_keys=ON; BEGIN IMMEDIATE;');
  try {
    if (!database.prepare("SELECT id FROM scope_passports WHERE id=? AND status='active'").get(scopeId)) throw new Error('Automation scope is not active');
    if (!database.prepare("SELECT id FROM scope_passports WHERE id=? AND status='active'").get(avitoScopeId)) throw new Error('Avito scope is not active');
    supersedeRecord(database, 'memory:automation:freelance-ru-commands-only', {
      id: 'memory:automation:freelance-ru-commands-only-avito-exception', semanticKey: 'automation.freelance_ru.commands_only', scopeId,
      layer: 'permanent', recordType: 'rule', ruleEffect: 'require', title: 'Freelance.ru: commands-only automation',
      content: 'Freelance.ru разрешён в MetricHit → Автоматизация после прямой команды владельца: local-browser login, формы, создание, редактирование, снятие и публикация объявлений допустимы без подтверждения каждой позиции. Расписания нет; пароль не хранится; сессия только DPAPI вне repository. Avito регулируется отдельным ограниченным исключением; FL.ru, Kwork и другие внешние аккаунты запрещены.',
      sourceRef: avitoSourceRef, approvedAt: avitoApprovedAt, metadata: { authority: 'direct_owner_confirmation', platform: 'freelance.ru' },
    });
    ensureRecord(database, {
      id: 'memory:automation:freelance-ru-session-storage', semanticKey: 'automation.freelance_ru.session_storage', scopeId,
      layer: 'permanent', recordType: 'rule', ruleEffect: 'require', title: 'Freelance.ru: DPAPI session storage',
      content: 'Состояние сессии Freelance.ru хранится только в C:\\ProgramData\\MetricHit\\automation-secrets\\freelance-ru\\freelance-session.dpapi, зашифрованное Windows DPAPI для текущей учётной записи и с restrictive ACL. Секреты, cookies, tokens и сессии не попадают в workspace или Git.',
      sourceRef, approvedAt, metadata: { authority: 'direct_owner_confirmation', platform: 'freelance.ru' },
    });
    supersedeRecord(database, 'memory:automation:avito:boundaries', {
      id: 'memory:automation:avito:boundaries-access-policy', semanticKey: 'automation.avito.isolation', scopeId: avitoScopeId,
      layer: 'permanent', recordType: 'rule', ruleEffect: 'require', title: 'Границы и доступ scope «Авито»',
      content: 'Авито использует только work/automation/avito и собственную scoped memory. Разрешены local-browser login/access и API integration/use; доступность API не предполагается. Создание, снятие, редактирование, публикация и любые изменяющие состояние form/API operations допускаются только по последующей точной команде владельца на операцию или пакет. Scheduler, платные услуги и расходы запрещены. Секреты, пароли, tokens, cookies и sessions не хранятся в repository. Новая отдельная база данных, schema или migration требуют отдельного scope.',
      sourceRef: avitoSourceRef, approvedAt: avitoApprovedAt, metadata: { authority: 'direct_owner_confirmation', platform: 'avito', working_root: 'work/automation/avito' },
    });
    supersedeRecord(database, 'memory:automation:platform-design-avito-created', {
      id: 'memory:automation:platform-design-avito-access-authorized', semanticKey: 'automation.platform_scope_design', scopeId,
      layer: 'working', recordType: 'decision', ruleEffect: null, title: 'Площадочные направления автоматизации',
      content: 'Freelance.ru, FL.ru и Kwork остаются самостоятельными направлениями с прежними ограничениями. Авито — активный изолированный scope с рабочим корнем work/automation/avito: local-browser login/access и API integration/use разрешены, но доступность API не предполагается. Любая изменяющая состояние операция Авито требует следующей точной команды владельца; scheduler, платные услуги и расходы запрещены.',
      sourceRef: avitoSourceRef, approvedAt: avitoApprovedAt, metadata: { authority: 'direct_owner_confirmation', avito_scope_id: avitoScopeId },
    });
    const avitoStartupCandidateId = upsertApprovedAvitoStartupContext(database);
    const automationRegistrationCandidateId = supersedeLegacyAutomationRegistrationContext(database);
    database.exec('COMMIT');
    return { databasePath, records: ['memory:automation:freelance-ru-commands-only-avito-exception', 'memory:automation:freelance-ru-session-storage', 'memory:automation:avito:boundaries-access-policy', 'memory:automation:platform-design-avito-access-authorized'], avitoStartupCandidateId, automationRegistrationCandidateId };
  } catch (error) {
    database.exec('ROLLBACK');
    throw error;
  } finally { database.close(); }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  console.log(JSON.stringify(applyFreelanceAutomationPolicy(process.argv[2] ? resolve(process.argv[2]) : defaultDatabase)));
}

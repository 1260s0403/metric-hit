import { createHash } from 'node:crypto';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabase = join(root, 'data', 'database', 'metrichit.db');
const scopeId = 'scope:subproject:automation';
const sourceRef = 'direct owner approval 2026-09-02: Freelance.ru commands-only automation';
const approvedAt = '2026-09-02T00:00:00.000Z';

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
      record.id, record.semanticKey, scopeId, record.layer, record.recordType, record.title, record.content,
      sourceRef, approvedAt, record.ruleEffect, JSON.stringify(['general']), JSON.stringify({ authority: 'direct_owner_confirmation', platform: 'freelance.ru' }), approvedAt, approvedAt,
    );
  }
  const stored = database.prepare('SELECT * FROM scoped_memory_records WHERE id=?').get(record.id);
  for (const [field, value] of Object.entries({ semantic_key: record.semanticKey, scope_id: scopeId, layer: record.layer, record_type: record.recordType, lifecycle_status: 'active', title: record.title, content: record.content, source_ref: sourceRef, rule_effect: record.ruleEffect })) {
    if (stored?.[field] !== value) throw new Error(`Freelance policy record ${record.id}.${field} differs`);
  }
}

export function applyFreelanceAutomationPolicy(databasePath = defaultDatabase) {
  const database = new DatabaseSync(databasePath);
  database.exec('PRAGMA foreign_keys=ON; BEGIN IMMEDIATE;');
  try {
    if (!database.prepare("SELECT id FROM scope_passports WHERE id=? AND status='active'").get(scopeId)) throw new Error('Automation scope is not active');
    ensureRecord(database, {
      id: 'memory:automation:freelance-ru-commands-only', semanticKey: 'automation.freelance_ru.commands_only',
      layer: 'permanent', recordType: 'rule', ruleEffect: 'require', title: 'Freelance.ru: commands-only automation',
      content: 'Только Freelance.ru разрешён в MetricHit → Автоматизация после прямой команды владельца: local-browser login, формы, создание, редактирование, снятие и публикация объявлений допустимы без подтверждения каждой позиции. Расписания нет; пароль не хранится; сессия только DPAPI вне repository. FL.ru, Kwork, Avito и другие внешние аккаунты запрещены.',
    });
    ensureRecord(database, {
      id: 'memory:automation:freelance-ru-session-storage', semanticKey: 'automation.freelance_ru.session_storage',
      layer: 'permanent', recordType: 'rule', ruleEffect: 'require', title: 'Freelance.ru: DPAPI session storage',
      content: 'Состояние сессии Freelance.ru хранится только в C:\\ProgramData\\MetricHit\\automation-secrets\\freelance-ru\\freelance-session.dpapi, зашифрованное Windows DPAPI для текущей учётной записи и с restrictive ACL. Секреты, cookies, tokens и сессии не попадают в workspace или Git.',
    });
    database.exec('COMMIT');
    return { databasePath, records: ['memory:automation:freelance-ru-commands-only', 'memory:automation:freelance-ru-session-storage'] };
  } catch (error) {
    database.exec('ROLLBACK');
    throw error;
  } finally { database.close(); }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  console.log(JSON.stringify(applyFreelanceAutomationPolicy(process.argv[2] ? resolve(process.argv[2]) : defaultDatabase)));
}

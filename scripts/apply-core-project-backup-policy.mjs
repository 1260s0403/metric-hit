import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabase = join(root, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/core-and-project-backup-policy-2026-08-21.md';
const semanticKey = 'operations.core_and_project_backup_policy';
const reviewedAt = '2026-08-21T21:00:00.000Z';

function uuid(key) {
  const hash = createHash('sha256').update(`metrichit-core-project-backup:${key}`).digest('hex');
  return `${hash.slice(0, 8)}-${hash.slice(8, 12)}-4${hash.slice(13, 16)}-a${hash.slice(17, 20)}-${hash.slice(20, 32)}`;
}

export function applyCoreProjectBackupPolicy(databasePath = defaultDatabase) {
  const bytes = readFileSync(join(root, decisionPath));
  const decision = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  const title = 'Единое резервирование «Ядра» и управляемых проектов';
  const content = 'Штатный backup «Ядра» охватывает центральный контур и все фактически созданные физические хранилища управляемых проектов. Центральная и каждая проектная SQLite снимаются безопасным online backup; для всех включённых данных единообразно проверяются запрещённые пути, секреты, inventory, SHA-256, служебная принадлежность и целостность. Полный охват достижимой Git-истории не сокращается: объекты читаются одним пакетным процессом, обычные, пустые, бинарные, ZIP и вложенные ZIP blobs проверяются, а ошибка протокола блокирует backup. Решение не создаёт проекты, не мигрирует данные и не переключает runtime.';
  const data = JSON.stringify({
    revision: 1,
    scope: ['core', 'all_existing_managed_project_storages'],
    sqlite_copy_method: 'online_backup',
    raw_live_database_copy_allowed: false,
    project_inventory_checks: ['canonical_project_id', 'path_boundary', 'ownership', 'storage_format', 'sha256', 'integrity'],
    git_history_scope: 'all_reachable_objects_in_all_refs',
    git_object_reader: 'single_batch_process',
    secret_policy_reduced: false,
    creates_projects: false,
    migrates_data: false,
    runtime_changed: false,
    evidence: { decision: decisionPath, contract: 'documents/backup-and-restore.md' },
  });
  const metadata = JSON.stringify({
    path: decisionPath,
    bytes: bytes.length,
    sha256: createHash('sha256').update(bytes).digest('hex'),
    encoding: 'utf-8',
    authority: 'direct_owner_confirmation',
    decision_date: '2026-08-21',
  });
  const sourceId = uuid(`source:${decisionPath}`);
  const documentId = uuid(`document:${decisionPath}`);
  const versionId = uuid(`version:${decisionPath}`);
  const candidateId = uuid(`candidate:${semanticKey}:1`);
  const database = new DatabaseSync(databasePath);
  const created = { sources: 0, documents: 0, versions: 0, candidates: 0 };
  database.exec('PRAGMA foreign_keys=ON; BEGIN IMMEDIATE;');
  try {
    const duplicate = database.prepare(
      "SELECT id FROM memory_candidates WHERE semantic_key=? AND status IN ('pending','approved') AND id<>?",
    ).get(semanticKey, candidateId);
    if (duplicate) throw new Error(`Semantic duplicate or evolution blocks ${semanticKey}`);
    const conflict = database.prepare(
      "SELECT id FROM memory_conflicts WHERE status='open' AND (candidate_id=? OR existing_memory_item_id IN (SELECT id FROM memory_items WHERE semantic_key=?))",
    ).get(candidateId, semanticKey);
    if (conflict) throw new Error(`Open memory conflict blocks ${semanticKey}`);

    created.sources += Number(database.prepare(
      "INSERT OR IGNORE INTO sources (id,type,title,content,data_json,status,author,valid_at,access_level) VALUES (?, 'owner_decision', ?, ?, ?, 'active', 'owner', '2026-08-21', 'internal')",
    ).run(sourceId, title, `Repository file: ${decisionPath}`, metadata).changes);
    created.documents += Number(database.prepare(
      "INSERT OR IGNORE INTO documents (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, 'owner', '2026-08-21', 'internal', 1)",
    ).run(documentId, title, decision, metadata, sourceId).changes);
    created.versions += Number(database.prepare(
      "INSERT OR IGNORE INTO document_versions (id,document_id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, 'owner', '2026-08-21', 'internal', 1)",
    ).run(versionId, documentId, title, decision, metadata, sourceId).changes);
    created.candidates += Number(database.prepare(
      "INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'decision', ?, ?, ?, ?, 'pending', ?, 'owner', '2026-08-21', 'internal', 1)",
    ).run(candidateId, semanticKey, title, content, data, sourceId).changes);
    const candidate = database.prepare('SELECT * FROM memory_candidates WHERE id=?').get(candidateId);
    if (candidate.status === 'pending') {
      database.prepare(
        "UPDATE memory_candidates SET status='approved',reviewed_by='owner',reviewed_at=?,review_note='Одобрено прямым решением владельца от 21.08.2026.',updated_at=?,version=version+1 WHERE id=?",
      ).run(reviewedAt, reviewedAt, candidateId);
    }
    const applied = database.prepare('SELECT * FROM memory_candidates WHERE id=?').get(candidateId);
    if (applied.status !== 'approved' || applied.semantic_key !== semanticKey || applied.content !== content || applied.data_json !== data) {
      throw new Error('Applied backup policy differs from the canonical payload.');
    }
    database.exec('COMMIT');
    return { databasePath, semanticKey, candidateId, created };
  } catch (error) {
    database.exec('ROLLBACK');
    throw error;
  } finally {
    database.close();
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  console.log(`Applied core/project backup policy: ${JSON.stringify(applyCoreProjectBackupPolicy(process.argv[2] ? resolve(process.argv[2]) : defaultDatabase))}`);
}

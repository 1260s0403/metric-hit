import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabasePath = join(repositoryRoot, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/telegram-invite-channel-published-topics-2026-09-14.md';
const semanticKey = 'editorial.telegram_invite_channel_published_topics';
const scopeId = 'scope:subproject:editorial';
const reviewedAt = '2026-09-14T00:00:00.000Z';
const owner = 'owner';

function stableUuid(key) {
  const hex = createHash('sha256').update(`metrichit-telegram-invite-published-topics:${key}`).digest('hex');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
}

export function applyTelegramInviteChannelPublishedTopics(databasePath = defaultDatabasePath) {
  const bytes = readFileSync(join(repositoryRoot, decisionPath));
  const documentContent = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  const sha256 = createHash('sha256').update(bytes).digest('hex');
  const title = 'Уже опубликованные темы invite-канала Telegram MetricHit';
  const content = 'В invite-канале уже опубликованы восемь тематических углов: первые запросы; поэтапный запуск; дневной лимит после выбора страницы, задачи и группы запросов; соответствие намерения запроса посадочной странице; регион как часть задачи; исходный снимок перед стартом; расходы в контексте страницы, запросов, региона и выполненного объёма; первая посадочная страница как рамка проекта. Следующий invite-пост не повторяет эти углы или их основной вывод; смежная тема требует самостоятельного практического вопроса и нового вывода.';
  const metadata = JSON.stringify({ path: decisionPath, bytes: bytes.length, sha256, encoding: 'utf-8', authority: 'direct_owner_channel_review', reviewed_date: '2026-09-14', platform: 'telegram', channel_role: 'invite_to_main_channel', topic_count: 8, semantic_duplicate_prevention: true });
  const sourceId = stableUuid(`source:${decisionPath}`);
  const documentId = stableUuid(`document:${decisionPath}`);
  const versionId = stableUuid(`version:${decisionPath}:1`);
  const candidateId = stableUuid(`candidate:${semanticKey}:1`);
  const recordId = stableUuid(`record:${scopeId}:${semanticKey}:1`);
  const database = new DatabaseSync(databasePath);
  const created = { sources: 0, documents: 0, versions: 0, candidates: 0, scopedRecords: 0 };
  database.exec('PRAGMA foreign_keys=ON; BEGIN IMMEDIATE;');
  try {
    const existingCandidate = database.prepare('SELECT id,status,content,data_json FROM memory_candidates WHERE semantic_key=?').get(semanticKey);
    if (existingCandidate && existingCandidate.id !== candidateId) throw new Error('Semantic duplicate or evolution blocks Telegram invite topic registry');
    if (existingCandidate && (existingCandidate.status !== 'approved' || existingCandidate.content !== content || existingCandidate.data_json !== metadata)) throw new Error('Existing Telegram invite topic registry differs from approved evidence');
    const existingRecord = database.prepare("SELECT id,lifecycle_status,content,metadata_json FROM scoped_memory_records WHERE scope_id=? AND semantic_key=? AND lifecycle_status='active'").get(scopeId, semanticKey);
    if (existingRecord && (existingRecord.id !== recordId || existingRecord.content !== content || existingRecord.metadata_json !== metadata)) throw new Error('Active scoped Telegram invite topic registry differs from approved evidence');
    if (!database.prepare("SELECT id FROM scope_passports WHERE id=? AND status='active'").get(scopeId)) throw new Error('Editorial scope is unavailable');
    created.sources += Number(database.prepare("INSERT OR IGNORE INTO sources (id,type,title,content,data_json,status,author,valid_at,access_level) VALUES (?,'owner_decision',?,?,?,'active',?,'2026-09-14','internal')").run(sourceId, title, `Repository file: ${decisionPath}`, metadata, owner).changes);
    created.documents += Number(database.prepare("INSERT OR IGNORE INTO documents (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?,'owner_decision',?,?,?,'active',?,?,'2026-09-14','internal',1)").run(documentId, title, documentContent, metadata, sourceId, owner).changes);
    created.versions += Number(database.prepare("INSERT OR IGNORE INTO document_versions (id,document_id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?,?, 'owner_decision',?,?,?,'active',?,?,'2026-09-14','internal',1)").run(versionId, documentId, title, documentContent, metadata, sourceId, owner).changes);
    created.candidates += Number(database.prepare("INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?,'decision',?,?,?,?,'pending',?,?,'2026-09-14','internal',1)").run(candidateId, semanticKey, title, content, metadata, sourceId, owner).changes);
    if (database.prepare('SELECT status FROM memory_candidates WHERE id=?').get(candidateId)?.status === 'pending') database.prepare("UPDATE memory_candidates SET status='approved',reviewed_by=?,reviewed_at=?,review_note=?,updated_at=?,version=version+1 WHERE id=?").run(owner, reviewedAt, 'Одобрено прямым поручением владельца зафиксировать темы invite-канала от 14.09.2026.', reviewedAt, candidateId);
    created.scopedRecords += Number(database.prepare("INSERT OR IGNORE INTO scoped_memory_records (id,semantic_key,scope_id,layer,record_type,lifecycle_status,title,content,source_ref,valid_from,supersedes_id,rule_effect,task_types_json,metadata_json,created_at,updated_at) VALUES (?,? ,?,'working','fact','active',?,?,?,? ,NULL,NULL,'[\"editorial\"]',?,?,?)").run(recordId, semanticKey, scopeId, title, content, `approved-memory://memory_candidates/${candidateId}`, reviewedAt, metadata, reviewedAt, reviewedAt).changes);
    database.exec('COMMIT');
    return { databasePath, created, semanticKey, candidateId, recordId, scopeId };
  } catch (error) {
    database.exec('ROLLBACK');
    throw error;
  } finally {
    database.close();
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  console.log(JSON.stringify(applyTelegramInviteChannelPublishedTopics(process.argv[2] ? resolve(process.argv[2]) : defaultDatabasePath)));
}

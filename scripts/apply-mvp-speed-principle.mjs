import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabase = join(root, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/mvp-speed-principle-2026-08-15.md';
const semanticKey = 'engineering.mvp_speed_principle';
const owner = 'owner';
const reviewedAt = '2026-08-15T18:00:00.000Z';

function uuid(key) {
  const hex = createHash('sha256').update(`metrichit-mvp-speed:${key}`).digest('hex');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
}

function assertRow(row, expected, label) {
  if (!row) throw new Error(`Missing ${label}`);
  for (const [field, value] of Object.entries(expected)) if (row[field] !== value) throw new Error(`${label}.${field} differs`);
}

export function applyMvpSpeedPrinciple(databasePath = defaultDatabase) {
  const bytes = readFileSync(join(root, decisionPath));
  const decision = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  if (decision.includes('\uFFFD')) throw new Error('MVP speed decision contains U+FFFD');
  const title = 'Принцип MVP и скорости разработки';
  const content = 'Скорость разработки критична. Для каждой задачи реализуется минимальный законченный пользовательский сценарий. Нельзя добавлять функции и абстракции «на будущее»; сложность допустима только при доказанной необходимости. Большие задачи по возможности делятся на законченные вертикальные этапы примерно по 20–30 минут, но не так, чтобы система оставалась небезопасной, полурабочей или неконсистентной. Нельзя экономить на целостности данных, security, idempotency, критических тестах и восстановимости. Недоделанное не считается MVP.';
  const sourceId = uuid(`source:${decisionPath}`);
  const documentId = uuid(`document:${decisionPath}`);
  const versionId = uuid(`version:${decisionPath}`);
  const candidateId = uuid(`candidate:${semanticKey}`);
  const metadata = JSON.stringify({ path: decisionPath, bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex'), encoding: 'utf-8', authority: 'direct_owner_confirmation', decision_date: '2026-08-15' });
  const data = JSON.stringify({ development_speed: 'critical', delivery: 'minimal_complete_user_scenario', premature_features_and_abstractions: 'forbidden', complexity: 'proven_need_only', vertical_stage_target_minutes: [20, 30], forbidden_partial_states: ['unsafe', 'half_working', 'inconsistent'], non_negotiable: ['data_integrity', 'security', 'idempotency', 'critical_tests', 'recoverability'], incomplete_is_mvp: false, evidence: { path: decisionPath } });
  const db = new DatabaseSync(databasePath);
  const created = { sources: 0, documents: 0, versions: 0, candidates: 0 };
  db.exec('PRAGMA foreign_keys=ON; BEGIN IMMEDIATE;');
  try {
    const duplicate = db.prepare("SELECT id FROM memory_candidates WHERE semantic_key=? AND status IN ('pending','approved') AND id<>?").get(semanticKey, candidateId);
    if (duplicate) throw new Error(`Semantic duplicate or evolution blocks ${semanticKey}`);
    const conflict = db.prepare("SELECT id FROM memory_conflicts WHERE status='open' AND (candidate_id=? OR existing_memory_item_id IN (SELECT id FROM memory_items WHERE semantic_key=?))").get(candidateId, semanticKey);
    if (conflict) throw new Error(`Open memory conflict blocks ${semanticKey}`);
    created.sources += Number(db.prepare("INSERT OR IGNORE INTO sources (id,type,title,content,data_json,status,author,valid_at,access_level) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, '2026-08-15', 'internal')").run(sourceId, title, `Repository file: ${decisionPath}`, metadata, owner).changes);
    created.documents += Number(db.prepare("INSERT OR IGNORE INTO documents (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-15', 'internal', 1)").run(documentId, title, decision, metadata, sourceId, owner).changes);
    created.versions += Number(db.prepare("INSERT OR IGNORE INTO document_versions (id,document_id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-15', 'internal', 1)").run(versionId, documentId, title, decision, metadata, sourceId, owner).changes);
    created.candidates += Number(db.prepare("INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'decision', ?, ?, ?, ?, 'pending', ?, ?, '2026-08-15', 'internal', 1)").run(candidateId, semanticKey, title, content, data, sourceId, owner).changes);
    const candidate = db.prepare('SELECT status FROM memory_candidates WHERE id=?').get(candidateId);
    if (candidate?.status === 'pending') db.prepare("UPDATE memory_candidates SET status='approved',reviewed_by=?,reviewed_at=?,review_note=?,updated_at=?,version=version+1 WHERE id=?").run(owner, reviewedAt, 'Одобрено прямым решением владельца MetricHit от 15.08.2026.', reviewedAt, candidateId);
    assertRow(db.prepare('SELECT * FROM memory_candidates WHERE id=?').get(candidateId), { type: 'decision', semantic_key: semanticKey, title, content, data_json: data, status: 'approved', source_id: sourceId, reviewed_by: owner, reviewed_at: reviewedAt }, 'MVP speed candidate');
    assertRow(db.prepare('SELECT * FROM sources WHERE id=?').get(sourceId), { type: 'owner_decision', title, content: `Repository file: ${decisionPath}`, data_json: metadata, status: 'active', author: owner }, 'MVP speed source');
    assertRow(db.prepare('SELECT * FROM documents WHERE id=?').get(documentId), { type: 'owner_decision', title, content: decision, data_json: metadata, status: 'active', source_id: sourceId, author: owner, version: 1 }, 'MVP speed document');
    assertRow(db.prepare('SELECT * FROM document_versions WHERE id=?').get(versionId), { document_id: documentId, type: 'owner_decision', title, content: decision, data_json: metadata, status: 'active', source_id: sourceId, author: owner, version: 1 }, 'MVP speed document version');
    db.exec('COMMIT');
    return { databasePath, semanticKey, created, sourceId, documentId, versionId, candidateId };
  } catch (error) {
    db.exec('ROLLBACK');
    throw error;
  } finally { db.close(); }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) console.log(`Applied MVP speed principle: ${JSON.stringify(applyMvpSpeedPrinciple(process.argv[2] ? resolve(process.argv[2]) : defaultDatabase))}`);

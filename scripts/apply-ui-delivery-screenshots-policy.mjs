import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabase = join(root, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/ui-delivery-screenshots-policy-2026-08-17.md';
const semanticKey = 'ui.delivery_screenshots_policy';
const owner = 'owner';
const reviewedAt = '2026-08-17T16:00:00.000Z';

function uuid(key) {
  const hash = createHash('sha256').update(`metrichit-ui-delivery-screenshots:${key}`).digest('hex');
  return `${hash.slice(0, 8)}-${hash.slice(8, 12)}-4${hash.slice(13, 16)}-a${hash.slice(17, 20)}-${hash.slice(20, 32)}`;
}

function assertRow(row, expected, label) {
  if (!row) throw new Error(`Missing ${label}`);
  for (const [field, value] of Object.entries(expected)) if (row[field] !== value) throw new Error(`${label}.${field} differs`);
}

export function applyUiDeliveryScreenshotsPolicy(databasePath = defaultDatabase) {
  const bytes = readFileSync(join(root, decisionPath));
  const decision = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  if (decision.includes('\uFFFD')) throw new Error('Decision contains U+FFFD');
  const title = 'Скриншоты в финальном отчёте по интерфейсу';
  const content = 'После завершения работ с интерфейсом любого проекта, включая само «Ядро», финальный отчёт должен содержать скриншоты выполненного результата. В отчёт включается не более четырёх скриншотов. Правило относится только к интерфейсным работам и не расширяет состав иных проверок или формат отчёта.';
  const data = JSON.stringify({
    applies_to: 'interface_work_for_any_project_including_core',
    final_report: { screenshots_required: true, maximum_count: 4 },
    scope: 'interface_work_only',
    expands_other_checks_or_report_format: false,
    evidence: { path: decisionPath },
  });
  const metadata = JSON.stringify({
    path: decisionPath,
    bytes: bytes.length,
    sha256: createHash('sha256').update(bytes).digest('hex'),
    encoding: 'utf-8',
    authority: 'direct_owner_confirmation',
    decision_date: '2026-08-17',
  });
  const sourceId = uuid(`source:${decisionPath}`);
  const documentId = uuid(`document:${decisionPath}`);
  const versionId = uuid(`version:${decisionPath}`);
  const candidateId = uuid(`candidate:${semanticKey}`);
  const db = new DatabaseSync(databasePath);
  const created = { sources: 0, documents: 0, versions: 0, candidates: 0 };
  db.exec('PRAGMA foreign_keys=ON; BEGIN IMMEDIATE;');
  try {
    const duplicate = db.prepare("SELECT id FROM memory_candidates WHERE semantic_key=? AND status IN ('pending','approved') AND id<>?").get(semanticKey, candidateId);
    if (duplicate) throw new Error(`Semantic duplicate or evolution blocks ${semanticKey}`);
    const conflict = db.prepare("SELECT id FROM memory_conflicts WHERE status='open' AND (candidate_id=? OR existing_memory_item_id IN (SELECT id FROM memory_items WHERE semantic_key=?))").get(candidateId, semanticKey);
    if (conflict) throw new Error(`Open memory conflict blocks ${semanticKey}`);
    created.sources += Number(db.prepare("INSERT OR IGNORE INTO sources (id,type,title,content,data_json,status,author,valid_at,access_level) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, '2026-08-17', 'internal')").run(sourceId, title, `Repository file: ${decisionPath}`, metadata, owner).changes);
    created.documents += Number(db.prepare("INSERT OR IGNORE INTO documents (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-17', 'internal', 1)").run(documentId, title, decision, metadata, sourceId, owner).changes);
    created.versions += Number(db.prepare("INSERT OR IGNORE INTO document_versions (id,document_id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-17', 'internal', 1)").run(versionId, documentId, title, decision, metadata, sourceId, owner).changes);
    created.candidates += Number(db.prepare("INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'decision', ?, ?, ?, ?, 'pending', ?, ?, '2026-08-17', 'internal', 1)").run(candidateId, semanticKey, title, content, data, sourceId, owner).changes);
    const candidate = db.prepare('SELECT status FROM memory_candidates WHERE id=?').get(candidateId);
    if (candidate.status === 'pending') db.prepare("UPDATE memory_candidates SET status='approved',reviewed_by=?,reviewed_at=?,review_note=?,updated_at=?,version=version+1 WHERE id=?").run(owner, reviewedAt, 'Одобрено прямым решением владельца MetricHit от 17.08.2026.', reviewedAt, candidateId);
    assertRow(db.prepare('SELECT * FROM memory_candidates WHERE id=?').get(candidateId), { type: 'decision', semantic_key: semanticKey, title, content, data_json: data, status: 'approved', source_id: sourceId, reviewed_by: owner, reviewed_at: reviewedAt }, 'UI delivery screenshots candidate');
    assertRow(db.prepare('SELECT * FROM sources WHERE id=?').get(sourceId), { data_json: metadata, status: 'active' }, 'source');
    assertRow(db.prepare('SELECT * FROM documents WHERE id=?').get(documentId), { content: decision, data_json: metadata, source_id: sourceId, version: 1 }, 'document');
    assertRow(db.prepare('SELECT * FROM document_versions WHERE id=?').get(versionId), { document_id: documentId, content: decision, data_json: metadata, version: 1 }, 'document version');
    db.exec('COMMIT');
    return { databasePath, semanticKey, created, sourceId, documentId, versionId, candidateId };
  } catch (error) {
    db.exec('ROLLBACK');
    throw error;
  } finally {
    db.close();
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) console.log(`Applied UI delivery screenshots policy: ${JSON.stringify(applyUiDeliveryScreenshotsPolicy(process.argv[2] ? resolve(process.argv[2]) : defaultDatabase))}`);

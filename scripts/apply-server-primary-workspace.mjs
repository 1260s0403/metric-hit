import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabase = join(root, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/server-primary-workspace-2026-08-16.md';
const owner = 'owner';
const reviewedAt = '2026-08-16T00:00:00.000Z';

function uuid(key) {
  const hex = createHash('sha256').update(`metrichit-server-primary-workspace:${key}`).digest('hex');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
}

function assertRow(row, expected, label) {
  if (!row) throw new Error(`Missing ${label}`);
  for (const [field, value] of Object.entries(expected)) if (row[field] !== value) throw new Error(`${label}.${field} differs`);
}

export function applyServerPrimaryWorkspace(databasePath = defaultDatabase) {
  const bytes = readFileSync(join(root, decisionPath));
  const decision = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  if (decision.includes('\uFFFD')) throw new Error('Server workspace decision contains U+FFFD');
  const title = 'SERVER как целевое primary workspace MetricHit';
  const metadata = JSON.stringify({ path: decisionPath, bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex'), encoding: 'utf-8', authority: 'direct_owner_confirmation', decision_date: '2026-08-16' });
  const entries = [
    {
      semanticKey: 'infrastructure.server_context', type: 'product_fact',
      content: 'Фактический серверный контекст: hostname SERVER; Windows Server 2025 Standard 64-bit, 10.0.26100; RAM 127.9 GB; C: 2047.9 GB всего и 2019.2 GB свободно; IPv4 65.109.62.241; Git 2.55.0.windows.3; Python 3.13.14.',
      data: { hostname: 'SERVER', os: { name: 'Windows Server 2025 Standard', architecture: '64-bit', version: '10.0.26100' }, ram_gb: 127.9, disk_c_gb: { total: 2047.9, free: 2019.2 }, ipv4: '65.109.62.241', git: '2.55.0.windows.3', python: '3.13.14', evidence: { path: decisionPath } },
    },
    {
      semanticKey: 'migration.server_primary_workspace', type: 'decision',
      content: 'Серверный перенос больше не на паузе: весь проект «Ядро» будет полностью перенесён на SERVER. После успешной миграции и проверок SERVER становится primary workspace; домашний ПК остаётся резервной точкой до подтверждения миграции. Перенос ещё не выполнен.',
      data: { migration_status: 'authorized_not_started', scope: 'entire_core_project', target_hostname: 'SERVER', primary_workspace_after: ['successful_migration', 'verification'], home_pc_role_until_confirmation: 'backup_point', migration_completed: false, evidence: { path: decisionPath } },
    },
  ];
  const sourceId = uuid(`source:${decisionPath}`);
  const documentId = uuid(`document:${decisionPath}`);
  const versionId = uuid(`version:${decisionPath}`);
  const db = new DatabaseSync(databasePath);
  const created = { sources: 0, documents: 0, versions: 0, candidates: 0 };
  db.exec('PRAGMA foreign_keys=ON; BEGIN IMMEDIATE;');
  try {
    for (const entry of entries) {
      const candidateId = uuid(`candidate:${entry.semanticKey}`);
      const duplicate = db.prepare("SELECT id FROM memory_candidates WHERE semantic_key=? AND status IN ('pending','approved') AND id<>?").get(entry.semanticKey, candidateId);
      if (duplicate) throw new Error(`Semantic duplicate or evolution blocks ${entry.semanticKey}`);
      const conflict = db.prepare("SELECT id FROM memory_conflicts WHERE status='open' AND (candidate_id=? OR existing_memory_item_id IN (SELECT id FROM memory_items WHERE semantic_key=?))").get(candidateId, entry.semanticKey);
      if (conflict) throw new Error(`Open memory conflict blocks ${entry.semanticKey}`);
    }
    created.sources += Number(db.prepare("INSERT OR IGNORE INTO sources (id,type,title,content,data_json,status,author,valid_at,access_level) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, '2026-08-16', 'internal')").run(sourceId, title, `Repository file: ${decisionPath}`, metadata, owner).changes);
    created.documents += Number(db.prepare("INSERT OR IGNORE INTO documents (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-16', 'internal', 1)").run(documentId, title, decision, metadata, sourceId, owner).changes);
    created.versions += Number(db.prepare("INSERT OR IGNORE INTO document_versions (id,document_id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-16', 'internal', 1)").run(versionId, documentId, title, decision, metadata, sourceId, owner).changes);
    for (const entry of entries) {
      const candidateId = uuid(`candidate:${entry.semanticKey}`);
      const data = JSON.stringify(entry.data);
      created.candidates += Number(db.prepare("INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, '2026-08-16', 'internal', 1)").run(candidateId, entry.type, entry.semanticKey, title, entry.content, data, sourceId, owner).changes);
      const candidate = db.prepare('SELECT status FROM memory_candidates WHERE id=?').get(candidateId);
      if (candidate?.status === 'pending') db.prepare("UPDATE memory_candidates SET status='approved',reviewed_by=?,reviewed_at=?,review_note=?,updated_at=?,version=version+1 WHERE id=?").run(owner, reviewedAt, 'Одобрено прямым решением владельца MetricHit от 16.08.2026.', reviewedAt, candidateId);
      assertRow(db.prepare('SELECT * FROM memory_candidates WHERE id=?').get(candidateId), { type: entry.type, semantic_key: entry.semanticKey, title, content: entry.content, data_json: data, status: 'approved', source_id: sourceId, reviewed_by: owner, reviewed_at: reviewedAt }, entry.semanticKey);
    }
    assertRow(db.prepare('SELECT * FROM sources WHERE id=?').get(sourceId), { data_json: metadata, status: 'active' }, 'source');
    assertRow(db.prepare('SELECT * FROM documents WHERE id=?').get(documentId), { content: decision, data_json: metadata, source_id: sourceId, version: 1 }, 'document');
    assertRow(db.prepare('SELECT * FROM document_versions WHERE id=?').get(versionId), { document_id: documentId, content: decision, data_json: metadata, version: 1 }, 'document version');
    db.exec('COMMIT');
    return { databasePath, semanticKeys: entries.map(({ semanticKey }) => semanticKey), created };
  } catch (error) {
    db.exec('ROLLBACK');
    throw error;
  } finally { db.close(); }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) console.log(`Applied server primary workspace: ${JSON.stringify(applyServerPrimaryWorkspace(process.argv[2] ? resolve(process.argv[2]) : defaultDatabase))}`);

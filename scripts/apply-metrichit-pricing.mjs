import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabasePath = join(repositoryRoot, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/metrichit-pricing-2026-08-29.md';
const semanticKey = 'pricing.current_tiers';
const owner = 'owner';
const reviewedAt = '2026-08-29T09:00:00.000Z';
const revision = 2;

function stableUuid(key) {
  const hex = createHash('sha256').update(`metrichit-pricing:${key}`).digest('hex');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
}

function assertFields(row, expected, label) {
  if (!row) throw new Error(`Missing ${label}`);
  for (const [column, value] of Object.entries(expected)) {
    if (row[column] !== value) throw new Error(`${label}.${column} differs`);
  }
}

export function applyMetricHitPricing(databasePath = defaultDatabasePath) {
  const bytes = readFileSync(join(repositoryRoot, decisionPath));
  const decision = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  if (decision.includes('\uFFFD')) throw new Error('Pricing decision contains U+FFFD');

  const sourceId = stableUuid(`source:${decisionPath}`);
  const documentId = stableUuid(`document:${decisionPath}`);
  const versionId = stableUuid(`document-version:${decisionPath}:1`);
  const candidateId = stableUuid(`candidate:${semanticKey}:revision:${revision}`);
  const title = 'Действующая тарифная сетка';
  const content = 'Цена клика зависит от суммы пополнения: от 1 000 ₽ — 0,50 ₽; от 10 000 ₽ — 0,40 ₽; от 50 000 ₽ — 0,30 ₽; от 100 000 ₽ — 0,25 ₽; от 150 000 ₽ — 0,20 ₽; от 200 000 ₽ — 0,15 ₽.';
  const metadata = JSON.stringify({
    path: decisionPath,
    bytes: bytes.length,
    sha256: createHash('sha256').update(bytes).digest('hex'),
    encoding: 'utf-8',
    authority: 'direct_owner_confirmation',
    decision_date: '2026-08-29',
  });
  const data = JSON.stringify({
    currency: 'RUB',
    tiers: [[1000, 0.5], [10000, 0.4], [50000, 0.3], [100000, 0.25], [150000, 0.2], [200000, 0.15]],
    unit: 'RUB_per_completed_click',
    price_basis: 'top_up_amount',
    prepayment: true,
    subscription_fee: false,
    balance_expires: false,
    revision,
    supersedes_semantic_revision: 1,
    evidence: { path: decisionPath },
  });

  const database = new DatabaseSync(databasePath);
  const created = { sources: 0, documents: 0, versions: 0, candidates: 0 };
  database.exec('PRAGMA foreign_keys = ON; BEGIN IMMEDIATE;');
  try {
    const sameRevision = database.prepare(`
      SELECT id FROM memory_candidates
      WHERE semantic_key = ? AND status IN ('pending', 'approved')
        AND coalesce(json_extract(data_json, '$.revision'), 0) = ? AND id <> ?
    `).get(semanticKey, revision, candidateId);
    if (sameRevision) throw new Error(`Semantic duplicate blocks ${semanticKey} revision ${revision}`);
    const conflict = database.prepare(`
      SELECT id FROM memory_conflicts
      WHERE status = 'open' AND (
        candidate_id = ? OR existing_memory_item_id IN (
          SELECT id FROM memory_items WHERE semantic_key = ?
        )
      )
    `).get(candidateId, semanticKey);
    if (conflict) throw new Error(`Open memory conflict blocks ${semanticKey}`);

    created.sources += Number(database.prepare(`
      INSERT OR IGNORE INTO sources
        (id, type, title, content, data_json, status, author, valid_at, access_level)
      VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, '2026-08-29', 'internal')
    `).run(sourceId, title, `Repository file: ${decisionPath}`, metadata, owner).changes);
    created.documents += Number(database.prepare(`
      INSERT OR IGNORE INTO documents
        (id, type, title, content, data_json, status, source_id, author, valid_at, access_level, version)
      VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-29', 'internal', 1)
    `).run(documentId, title, decision, metadata, sourceId, owner).changes);
    created.versions += Number(database.prepare(`
      INSERT OR IGNORE INTO document_versions
        (id, document_id, type, title, content, data_json, status, source_id, author, valid_at, access_level, version)
      VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-29', 'internal', 1)
    `).run(versionId, documentId, title, decision, metadata, sourceId, owner).changes);
    created.candidates += Number(database.prepare(`
      INSERT OR IGNORE INTO memory_candidates
        (id, type, semantic_key, title, content, data_json, status, source_id, author, valid_at, access_level, version)
      VALUES (?, 'commercial_terms', ?, ?, ?, ?, 'pending', ?, ?, '2026-08-29', 'internal', 1)
    `).run(candidateId, semanticKey, title, content, data, sourceId, owner).changes);

    const candidate = database.prepare('SELECT status FROM memory_candidates WHERE id = ?').get(candidateId);
    if (candidate?.status === 'pending') {
      database.prepare(`
        UPDATE memory_candidates
        SET status = 'approved', reviewed_by = ?, reviewed_at = ?, review_note = ?,
            updated_at = ?, version = version + 1
        WHERE id = ?
      `).run(owner, reviewedAt, 'Одобрено прямым решением владельца MetricHit от 29.08.2026.', reviewedAt, candidateId);
    }

    assertFields(database.prepare('SELECT * FROM memory_candidates WHERE id = ?').get(candidateId), {
      type: 'commercial_terms', semantic_key: semanticKey, title, content, data_json: data,
      status: 'approved', source_id: sourceId, reviewed_by: owner, reviewed_at: reviewedAt,
    }, 'pricing candidate');
    assertFields(database.prepare('SELECT * FROM documents WHERE id = ?').get(documentId), {
      content: decision, data_json: metadata, source_id: sourceId, version: 1,
    }, 'pricing decision document');

    database.exec('COMMIT');
    return { databasePath, created, sourceId, documentId, versionId, candidateId, semanticKey, revision };
  } catch (error) {
    database.exec('ROLLBACK');
    throw error;
  } finally {
    database.close();
  }
}

function isMainModule() {
  return process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href;
}

if (isMainModule()) {
  const result = applyMetricHitPricing(process.argv[2] ? resolve(process.argv[2]) : defaultDatabasePath);
  console.log(`Applied MetricHit pricing: ${JSON.stringify(result)}`);
}

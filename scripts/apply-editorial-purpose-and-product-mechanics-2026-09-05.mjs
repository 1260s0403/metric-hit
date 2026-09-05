import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';
import { registerScopedRecord } from './structured-memory.mjs';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabasePath = join(repositoryRoot, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/editorial-purpose-and-product-mechanics-2026-09-05.md';
const semanticKey = 'content.editorial_purpose_and_product_mechanics_rule';
const title = 'Назначение Редакции и механика MetricHit';
const reviewedAt = '2026-09-05T00:00:00.000Z';
function stableUuid(key) { const hex = createHash('sha256').update(`metrichit-editorial-purpose:${key}`).digest('hex'); return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`; }
function assertFields(row, expected, label) { if (!row) throw new Error(`Missing ${label}`); for (const [key, value] of Object.entries(expected)) if (row[key] !== value) throw new Error(`${label}.${key} differs`); }

export function applyEditorialPurposeAndProductMechanics(databasePath = defaultDatabasePath) {
  const bytes = readFileSync(join(repositoryRoot, decisionPath));
  const content = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  const ruleContent = content.split(/\r?\n\r?\n/u).slice(2).join('\n\n').trim();
  const metadata = JSON.stringify({ path: decisionPath, sha256: createHash('sha256').update(bytes).digest('hex'), authority: 'direct_owner_confirmation', decision_date: '2026-09-05' });
  const sourceId = stableUuid(`source:${decisionPath}`), documentId = stableUuid(`document:${decisionPath}`), versionId = stableUuid(`version:${decisionPath}:1`), candidateId = stableUuid(`candidate:${semanticKey}:1`), scopedId = 'memory:editorial:purpose-product-mechanics:2026-09-05';
  const database = new DatabaseSync(resolve(databasePath)); const created = { sources: 0, documents: 0, versions: 0, candidates: 0, scoped: 0 };
  database.exec('PRAGMA foreign_keys=ON; BEGIN IMMEDIATE;');
  try {
    const duplicate = database.prepare("SELECT id FROM memory_candidates WHERE semantic_key=? AND status IN ('pending','approved') AND id<>?").get(semanticKey, candidateId); if (duplicate) throw new Error('Semantic duplicate blocks editorial purpose rule');
    created.sources += Number(database.prepare("INSERT OR IGNORE INTO sources (id,type,title,content,data_json,status,author,valid_at,access_level) VALUES (?, 'owner_decision', ?, ?, ?, 'active', 'owner', '2026-09-05', 'internal')").run(sourceId, title, `Repository file: ${decisionPath}`, metadata).changes);
    created.documents += Number(database.prepare("INSERT OR IGNORE INTO documents (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, 'owner', '2026-09-05', 'internal', 1)").run(documentId, title, content, metadata, sourceId).changes);
    created.versions += Number(database.prepare("INSERT OR IGNORE INTO document_versions (id,document_id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, 'owner', '2026-09-05', 'internal', 1)").run(versionId, documentId, title, content, metadata, sourceId).changes);
    const dataJson = JSON.stringify({ additive: true, applies_to: ['articles', 'longform'], excluded_platforms: ['telegram'], semantic_core_queries: 302, lsi_required: true, human_readability_required: true, product_mechanics: 'search_results_other_results_then_target_last_no_return_no_on_site_actions', editor_rejects: ['incorrect_product_mechanics', 'unnatural_exact_query_insertions'], publication: 'owner_gated', indexation_check: 'after_publication', pf_launch: 'separate_owner_command', evidence: { path: decisionPath } });
    created.candidates += Number(database.prepare("INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'editorial_rule', ?, ?, ?, ?, 'pending', ?, 'owner', '2026-09-05', 'internal', 1)").run(candidateId, semanticKey, title, ruleContent, dataJson, sourceId).changes);
    if (database.prepare('SELECT status FROM memory_candidates WHERE id=?').get(candidateId)?.status === 'pending') database.prepare("UPDATE memory_candidates SET status='approved',reviewed_by='owner',reviewed_at=?,review_note=?,updated_at=?,version=version+1 WHERE id=?").run(reviewedAt, 'Одобрено прямым указанием владельца MetricHit от 05.09.2026.', reviewedAt, candidateId);
    assertFields(database.prepare('SELECT semantic_key,content,data_json,status FROM memory_candidates WHERE id=?').get(candidateId), { semantic_key: semanticKey, content: ruleContent, data_json: dataJson, status: 'approved' }, 'editorial purpose candidate'); database.exec('COMMIT');
    const existing = database.prepare('SELECT semantic_key,content,source_ref FROM scoped_memory_records WHERE id=?').get(scopedId);
    if (existing) assertFields(existing, { semantic_key: semanticKey, content: ruleContent, source_ref: decisionPath }, 'editorial purpose scoped rule');
    else { registerScopedRecord(databasePath, { id: scopedId, semanticKey, scopeId: 'scope:subproject:editorial', layer: 'permanent', recordType: 'rule', title, content: ruleContent, sourceRef: decisionPath, validFrom: reviewedAt, ruleEffect: 'require', taskTypes: ['editorial', 'research', 'code'] }); created.scoped = 1; }
    return { databasePath: resolve(databasePath), created, semanticKey, scopedId };
  } catch (error) { if (database.isTransaction) database.exec('ROLLBACK'); throw error; } finally { database.close(); }
}
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) console.log(JSON.stringify(applyEditorialPurposeAndProductMechanics(process.argv[2] ? resolve(process.argv[2]) : defaultDatabasePath), null, 2));

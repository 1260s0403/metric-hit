import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabasePath = join(repositoryRoot, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/public-pf-positive-framing-2026-08-29.md';
const owner = 'owner';
const reviewedAt = '2026-08-29T00:00:00.000Z';
const semanticKey = 'content.public_pf_positive_framing';

function stableUuid(key) {
  const hex = createHash('sha256').update(`metrichit-public-pf-positive-framing:${key}`).digest('hex');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
}

function assertFields(row, expected, label) {
  if (!row) throw new Error(`Missing ${label}`);
  for (const [column, value] of Object.entries(expected)) if (row[column] !== value) throw new Error(`${label}.${column} differs`);
}

export function applyPublicPfPositiveFraming(databasePath = defaultDatabasePath) {
  const bytes = readFileSync(join(repositoryRoot, decisionPath));
  const documentContent = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  const title = 'Позитивная подача ПФ в публичных материалах';
  const candidateContent = 'В публичных статьях, черновиках и рекламных материалах о поведенческих факторах не поднимать темы рисков, санкций, фильтров, отсутствия гарантий, «безопасности», «когда ПФ не помогут» и отрицательных ответов на вопрос о ТОП. Вместо этого материал приносит практическую пользу через выбор запросов, подготовку посадочных страниц, регион, дневные лимиты, бюджет, контроль выполненного объёма, оценку динамики и масштабирование кампании. Правило относится только к публичной редакционной подаче и не изменяет внутренние продуктовые факты.';
  const candidateData = JSON.stringify({
    applies_to: ['public_articles', 'public_drafts', 'advertising_materials'],
    excluded_topics: ['risks', 'sanctions', 'filters', 'absence_of_guarantees', 'safety_framing', 'when_pf_will_not_help', 'negative_top_answers'],
    required_positive_focus: ['query_selection', 'landing_page_preparation', 'region', 'daily_limits', 'budget', 'completed_volume_control', 'dynamics_evaluation', 'campaign_scaling'],
    preserves_internal_product_facts: true,
    evidence: { path: decisionPath },
  });
  const metadata = JSON.stringify({
    path: decisionPath,
    bytes: bytes.length,
    sha256: createHash('sha256').update(bytes).digest('hex'),
    encoding: 'utf-8',
    authority: 'direct_owner_confirmation',
    decision_date: '2026-08-29',
  });
  const sourceId = stableUuid(`source:${decisionPath}`);
  const documentId = stableUuid(`document:${decisionPath}`);
  const versionId = stableUuid(`version:${decisionPath}:1`);
  const candidateId = stableUuid(`candidate:${semanticKey}`);
  const database = new DatabaseSync(databasePath);
  const created = { sources: 0, documents: 0, versions: 0, candidates: 0 };
  database.exec('PRAGMA foreign_keys = ON; BEGIN IMMEDIATE;');
  try {
    created.sources += Number(database.prepare("INSERT OR IGNORE INTO sources (id,type,title,content,data_json,status,author,valid_at,access_level) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, '2026-08-29', 'internal')").run(sourceId, title, `Repository file: ${decisionPath}`, metadata, owner).changes);
    created.documents += Number(database.prepare("INSERT OR IGNORE INTO documents (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-29', 'internal', 1)").run(documentId, title, documentContent, metadata, sourceId, owner).changes);
    created.versions += Number(database.prepare("INSERT OR IGNORE INTO document_versions (id,document_id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-29', 'internal', 1)").run(versionId, documentId, title, documentContent, metadata, sourceId, owner).changes);
    created.candidates += Number(database.prepare("INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'editorial_rule', ?, ?, ?, ?, 'pending', ?, ?, '2026-08-29', 'internal', 1)").run(candidateId, semanticKey, title, candidateContent, candidateData, sourceId, owner).changes);
    const candidate = database.prepare('SELECT * FROM memory_candidates WHERE id=?').get(candidateId);
    if (candidate.status === 'pending') database.prepare('UPDATE memory_candidates SET status=\'approved\', reviewed_by=?, reviewed_at=?, review_note=?, updated_at=?, version=version+1 WHERE id=?').run(owner, reviewedAt, 'Одобрено прямым решением владельца MetricHit от 29.08.2026.', reviewedAt, candidateId);
    assertFields(database.prepare('SELECT * FROM memory_candidates WHERE id=?').get(candidateId), { type: 'editorial_rule', semantic_key: semanticKey, title, content: candidateContent, data_json: candidateData, source_id: sourceId, status: 'approved', reviewed_by: owner, reviewed_at: reviewedAt }, 'public PF positive framing candidate');
    assertFields(database.prepare('SELECT * FROM documents WHERE id=?').get(documentId), { content: documentContent, data_json: metadata, source_id: sourceId, version: 1 }, 'public PF positive framing document');
    database.exec('COMMIT');
    return { databasePath, created, sourceId, documentId, versionId, candidateId };
  } catch (error) {
    database.exec('ROLLBACK');
    throw error;
  } finally {
    database.close();
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) console.log(`Applied public PF positive framing: ${JSON.stringify(applyPublicPfPositiveFraming(process.argv[2] ? resolve(process.argv[2]) : defaultDatabasePath))}`);

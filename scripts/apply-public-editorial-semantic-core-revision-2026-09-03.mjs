import { createHash, randomUUID } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const decisionPath = 'knowledge/decisions/public-editorial-semantic-core-2026-09-03.md';
const projectId = '00000000-0000-4000-a000-000000000102';
const semanticCoreKey = 'content.metrichit_semantic_core';
const semanticPolicyKey = 'content.public_editorial_semantic_core_policy';
const referenceKey = 'content.metrichit_semantic_core.reference';
const expectedCount = 302;
const revision = 6;

function hash(value) { return createHash('sha256').update(value).digest('hex'); }
function stableUuid(value) {
  const hex = hash(`metrichit-semantic-core-revision-2026-09-03:${value}`);
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
}
function now() { return new Date().toISOString(); }
function parseTerms(documentContent) {
  const section = documentContent.split('## Утверждённый набор\n')[1];
  if (!section) throw new Error('approved semantic-core list is missing');
  const terms = section.split(/\r?\n/).filter((line) => line.startsWith('- ')).map((line) => line.slice(2).trim());
  if (terms.length !== expectedCount || new Set(terms.map((term) => term.toLocaleLowerCase('ru-RU'))).size !== expectedCount) {
    throw new Error('approved semantic-core list must contain 302 unique exact queries');
  }
  return terms;
}
function isGeo(term) {
  return /(астрахан|киров|московск|севастопол|новороссийск|челябинск|стерлитамак|самар|владивосток|сургут|барнаул|владикавказ|ижевск|екб|подольск|санкт петербург|москва|\bмск\b|новосибирск|\bспб\b|ростов на дону|оренбург|казань|краснодар|нижний новгород)/iu.test(term);
}
function clusterFor(term) {
  if (isGeo(term)) return 'geo_candidates_after_demand_validation';
  if (/(яндекс карт|яндекс карты|пф яндекс карт|карты накрутка)/iu.test(term)) return 'yandex_maps';
  if (/(софт|программ|бот|робот|приложени|прокси|акки|профил|куки)/iu.test(term)) return 'software_and_automation';
  if (/(цена|стоимость|дешево|купить|заказать|услуг|услуга|продажа)/iu.test(term)) return 'commercial_and_price';
  if (/^(что такое|как |пф что это|поведенческий фактор это|пф это)/iu.test(term)) return 'education_and_howto';
  if (/(трафик|посещен|посетител|просмотр|позиц|в топ|топ яндекс|вывести в топ|раскрутка сайта)/iu.test(term)) return 'traffic_and_positions';
  return 'behavioral_factors_general';
}
function taxonomyFor(terms) {
  const result = {};
  for (const term of terms) {
    const cluster = clusterFor(term);
    (result[cluster] ??= []).push(term);
  }
  return result;
}
function upsertEvidence(database, { sourceId, documentId, versionId, content, metadata }) {
  const title = 'Замена семантического ядра публичных материалов';
  database.prepare("INSERT OR IGNORE INTO sources (id,type,title,content,data_json,status,author,valid_at,access_level) VALUES (?, 'owner_decision', ?, ?, ?, 'active', 'owner', '2026-09-03', 'internal')")
    .run(sourceId, title, `Repository file: ${decisionPath}`, metadata);
  database.prepare("INSERT OR IGNORE INTO documents (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, 'owner', '2026-09-03', 'internal', 1)")
    .run(documentId, title, content, metadata, sourceId);
  database.prepare("INSERT OR IGNORE INTO document_versions (id,document_id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, 'owner', '2026-09-03', 'internal', 1)")
    .run(versionId, documentId, title, content, metadata, sourceId);
}
function applyCore(databasePath, data, content, metadata, ids) {
  const database = new DatabaseSync(databasePath);
  database.exec('PRAGMA foreign_keys = ON; BEGIN IMMEDIATE;');
  try {
    upsertEvidence(database, { ...ids, content, metadata });
    const existing = database.prepare("SELECT id,status FROM memory_candidates WHERE semantic_key=? AND status='approved' ORDER BY updated_at DESC LIMIT 1").get(semanticCoreKey);
    const candidateId = ids.coreCandidateId;
    database.prepare("INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'fact', ?, ?, ?, ?, 'pending', ?, 'owner', '2026-09-03', 'internal', 1)")
      .run(candidateId, semanticCoreKey, 'Полное не-навигационное семантическое ядро MetricHit', '302 точных запросa владельца для новых публичных постов и статей вне Telegram.', JSON.stringify(data), ids.sourceId);
    database.prepare("UPDATE memory_candidates SET status='approved',reviewed_by='owner',reviewed_at='2026-09-03T00:00:00.000Z',review_note='Одобрено прямым указанием владельца от 03.09.2026.',updated_at=?,version=version+1 WHERE id=? AND status='pending'").run(now(), candidateId);
    const candidate = database.prepare('SELECT id,status,data_json,content FROM memory_candidates WHERE id=?').get(candidateId);
    if (!candidate || candidate.status !== 'approved' || candidate.data_json !== JSON.stringify(data)) throw new Error('semantic-core candidate differs');
    database.exec('COMMIT');
    return { candidateId, priorCandidateId: existing?.id ?? null, contentHash: hash(candidate.content), dataHash: hash(candidate.data_json) };
  } catch (error) { database.exec('ROLLBACK'); throw error; } finally { database.close(); }
}
function applyCentral(databasePath, core, content, metadata, ids) {
  const database = new DatabaseSync(databasePath);
  database.exec('PRAGMA foreign_keys = ON; BEGIN IMMEDIATE;');
  try {
    const policyContent = 'Каждый новый публичный пост или статья MetricHit вне Telegram использует основной и вторичные целевые запросы только дословно из утверждённого семантического ядра из 302 запросов. Запросы принадлежат одному кластеру либо документированно смежным кластерам при едином интенте; геокандидаты требуют предварительного подтверждения спроса. Telegram, опубликованный архив и существующие черновики исключены.';
    const policyData = JSON.stringify({ revision, supersedes_semantic_revision: revision - 1, applies_to: ['new_public_posts', 'new_public_articles'], excluded_platforms: ['telegram'], semantic_core: { keyword_count: expectedCount, target_queries_must_be_verbatim_approved_core_entries: true, geo_candidates_require_prior_demand_verification: true }, evidence: { path: decisionPath } });
    const policyId = ids.policyCandidateId;
    database.prepare("INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'editorial_rule', ?, ?, ?, ?, 'pending', ?, 'owner', '2026-09-03', 'internal', 1)")
      .run(policyId, semanticPolicyKey, 'Семантическое ядро для новых публичных материалов вне Telegram', policyContent, policyData, ids.sourceId);
    database.prepare("UPDATE memory_candidates SET status='approved',reviewed_by='owner',reviewed_at='2026-09-03T00:00:00.000Z',review_note='Одобрено прямым указанием владельца от 03.09.2026.',updated_at=?,version=version+1 WHERE id=? AND status='pending'").run(now(), policyId);
    const current = database.prepare("SELECT id FROM scoped_memory_records WHERE semantic_key=? AND lifecycle_status='active'").get(referenceKey);
    if (current && current.id !== ids.referenceId) database.prepare("UPDATE scoped_memory_records SET lifecycle_status='superseded',updated_at=? WHERE id=?").run(now(), current.id);
    const referenceMetadata = JSON.stringify({ reference_type: 'approved_memory_candidate', project_id: projectId, candidate_id: ids.coreCandidateId, candidate_semantic_key: semanticCoreKey, keyword_count: expectedCount, content_sha256: core.contentHash, data_json_sha256: core.dataHash, authority: 'project_sqlite', legacy_duplicate_policy: 'audit_only' });
    database.prepare("INSERT OR IGNORE INTO scoped_memory_records (id,semantic_key,scope_id,layer,record_type,lifecycle_status,title,content,source_ref,valid_from,supersedes_id,rule_effect,task_types_json,metadata_json,created_at,updated_at) VALUES (?, ?, 'scope:subproject:editorial', 'permanent', 'fact', 'active', ?, ?, ?, '2026-09-03T00:00:00.000Z', ?, NULL, '[\"editorial\",\"research\"]', ?, ?, ?)")
      .run(ids.referenceId, referenceKey, 'Семантическое ядро MetricHit — ссылка', 'Утверждено 302 точных не-навигационных запроса для новых публичных постов и статей вне Telegram.', `project://${projectId}/memory_candidates/${ids.coreCandidateId}`, current?.id ?? null, referenceMetadata, now(), now());
    database.exec('COMMIT');
  } catch (error) { database.exec('ROLLBACK'); throw error; } finally { database.close(); }
}
export function applyPublicEditorialSemanticCoreRevision(centralDatabasePath, projectDatabasePath) {
  const content = readFileSync(join(repositoryRoot, decisionPath), 'utf8');
  const terms = parseTerms(content);
  const data = { project_id: projectId, taxonomy: taxonomyFor(terms), keyword_count: expectedCount, use: ['content_planning', 'article_seo', 'semantic_research'], geo_candidates: { require_demand_validation: true }, exclusions: { navigation_and_brand_queries: ['MetricHit', 'Metric Hit', 'Метрик Хит', 'mtrhit'] }, provenance: { decision_path: decisionPath, authority: 'direct_owner_confirmation_2026-09-03' } };
  const ids = { sourceId: stableUuid('source'), documentId: stableUuid('document'), versionId: stableUuid('version'), coreCandidateId: stableUuid('core-candidate'), policyCandidateId: stableUuid('policy-candidate'), referenceId: 'memory:editorial:semantic-core-reference:2026-09-03' };
  const metadata = JSON.stringify({ path: decisionPath, bytes: Buffer.byteLength(content), sha256: hash(content), authority: 'direct_owner_confirmation', decision_date: '2026-09-03' });
  const project = applyCore(resolve(projectDatabasePath), data, content, metadata, ids);
  applyCore(resolve(centralDatabasePath), data, content, metadata, ids);
  applyCentral(resolve(centralDatabasePath), project, content, metadata, ids);
  return { keyword_count: terms.length, taxonomy: Object.fromEntries(Object.entries(data.taxonomy).map(([key, values]) => [key, values.length])), candidate_id: ids.coreCandidateId, policy_candidate_id: ids.policyCandidateId };
}
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) console.log(JSON.stringify(applyPublicEditorialSemanticCoreRevision(process.argv[2], process.argv[3]), null, 2));

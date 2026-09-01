import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabasePath = join(repositoryRoot, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/public-editorial-approved-core-target-queries-2026-09-01.md';
const owner = 'owner';
const reviewedAt = '2026-09-01T00:00:00.000Z';
const semanticKey = 'content.public_editorial_semantic_core_policy';
const revision = 4;

function stableUuid(key) {
  const hex = createHash('sha256').update(`metrichit-public-editorial-approved-core-target-queries:${key}`).digest('hex');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
}

function priorApprovedCoreCandidateId() {
  return stableUuid(`candidate:${semanticKey}:${revision - 1}`);
}

function assertFields(row, expected, label) {
  if (!row) throw new Error(`Missing ${label}`);
  for (const [column, value] of Object.entries(expected)) if (row[column] !== value) throw new Error(`${label}.${column} differs`);
}

export function applyPublicEditorialApprovedCoreTargetQueries(databasePath = defaultDatabasePath) {
  const bytes = readFileSync(join(repositoryRoot, decisionPath));
  const documentContent = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  const title = 'Целевые запросы публичных материалов только из утверждённого ядра';
  const candidateContent = 'Каждый новый публичный пост или статья MetricHit вне Telegram использует один основной целевой запрос и при необходимости ноль или несколько вторичных целевых запросов, выбранных дословно только из утверждённого полного не-навигационного семантического ядра MetricHit из 145 запросов. Все целевые запросы принадлежат одному выбранному кластеру либо нескольким документированно смежным кластерам и обслуживают один пользовательский интент; переоптимизация, смешение несвязанных кластеров и повтор запросов не допускаются. Для нескольких кластеров execution card и delivery QA фиксируют полный список кластеров и обоснование их смежности. Нельзя создавать синонимы, LSI-фразы, геоварианты или другие дополнительные целевые запросы вне утверждённого списка. Обычный естественный неключевой текст разрешён, но не считается целевым поисковым запросом. Compiler и delivery validation fail-closed отклоняют ключ вне ядра, вне зафиксированных кластеров, повтор, несколько кластеров без обоснования смежности или несоответствующее card доказательство. Брендовые и навигационные варианты исключены, геокандидаты требуют предварительного подтверждения спроса. Telegram полностью исключён; цель индексации Яндекса для новых публичных материалов вне Telegram не меняется. Архив и существующие черновики не меняются.';
  const candidateData = JSON.stringify({
    revision,
    supersedes_semantic_revision: revision - 1,
    supersedes_candidate_id: priorApprovedCoreCandidateId(),
    applies_to: ['new_public_posts', 'new_public_articles'],
    platforms: ['vk', 'tenchat', 'article_platforms', 'future_public_editorial_channels'],
    excluded_platforms: ['telegram'],
    semantic_core: {
      keyword_count: 145,
      target_queries_must_be_verbatim_approved_core_entries: true,
      primary_and_secondary_target_queries_only: true,
      one_or_more_documented_adjacent_clusters_and_one_intent: true,
      multiple_clusters_require_adjacency_rationale: true,
      brand_and_navigation_excluded: true,
      geo_candidates_require_prior_demand_verification: true,
      invented_synonyms_lsi_geo_variants_and_target_terms_prohibited: true,
      natural_non_key_prose_allowed: true,
    },
    execution_card: ['selected_clusters', 'adjacent_cluster_rationale', 'primary_target_query', 'secondary_target_queries', 'user_intent', 'platform', 'format', 'core_reference'],
    primary_query_placement: { article: ['h1'], social_post: ['headline', 'opening_paragraph'], natural: true, keyword_stuffing_prohibited: true },
    content_scope: { serves_one_selected_intent: true, multiple_clusters_only_if_documented_adjacent: true, unrelated_clusters_mixed: false, duplicate_target_queries_prohibited: true },
    delivery_validation: ['semantic_cluster_selection', 'target_queries_approved_core', 'adjacent_clusters_one_intent', 'primary_query_prominence', 'geo_demand_verification'],
    evidence: { path: decisionPath },
  });
  const metadata = JSON.stringify({ path: decisionPath, bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex'), encoding: 'utf-8', authority: 'direct_owner_confirmation', decision_date: '2026-09-01', revision });
  const sourceId = stableUuid(`source:${decisionPath}:${revision}`);
  const documentId = stableUuid(`document:${decisionPath}:${revision}`);
  const versionId = stableUuid(`version:${decisionPath}:${revision}`);
  const candidateId = stableUuid(`candidate:${semanticKey}:${revision}`);
  const database = new DatabaseSync(databasePath);
  const created = { sources: 0, documents: 0, versions: 0, candidates: 0 };
  database.exec('PRAGMA foreign_keys = ON; BEGIN IMMEDIATE;');
  try {
    const priorRows = database.prepare("SELECT id,status,coalesce(json_extract(data_json, '$.revision'), 0) AS revision FROM memory_candidates WHERE semantic_key=? AND status IN ('pending','approved') AND id<>?").all(semanticKey, candidateId);
    const competing = priorRows.filter((row) => row.status !== 'approved' || Number(row.revision) >= revision);
    if (competing.length) throw new Error('Semantic duplicate or evolution requires only approved prior revisions');
    const prior = priorRows.find((row) => row.id === priorApprovedCoreCandidateId() && Number(row.revision) === revision - 1);
    if (!prior) throw new Error('Approved semantic-core revision 3 is required before this superseding clarification');
    const conflict = database.prepare("SELECT id FROM memory_conflicts WHERE status='open' AND (candidate_id=? OR existing_memory_item_id IN (SELECT id FROM memory_items WHERE semantic_key=?))").get(candidateId, semanticKey);
    if (conflict) throw new Error('Open memory conflict blocks approved-core target-query policy');
    created.sources += Number(database.prepare("INSERT OR IGNORE INTO sources (id,type,title,content,data_json,status,author,valid_at,access_level) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, '2026-09-01', 'internal')").run(sourceId, title, `Repository file: ${decisionPath}`, metadata, owner).changes);
    created.documents += Number(database.prepare("INSERT OR IGNORE INTO documents (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-09-01', 'internal', 1)").run(documentId, title, documentContent, metadata, sourceId, owner).changes);
    created.versions += Number(database.prepare("INSERT OR IGNORE INTO document_versions (id,document_id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-09-01', 'internal', 1)").run(versionId, documentId, title, documentContent, metadata, sourceId, owner).changes);
    created.candidates += Number(database.prepare("INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'editorial_rule', ?, ?, ?, ?, 'pending', ?, ?, '2026-09-01', 'internal', 1)").run(candidateId, semanticKey, title, candidateContent, candidateData, sourceId, owner).changes);
    if (database.prepare('SELECT status FROM memory_candidates WHERE id=?').get(candidateId)?.status === 'pending') database.prepare("UPDATE memory_candidates SET status='approved', reviewed_by=?, reviewed_at=?, review_note=?, updated_at=?, version=version+1 WHERE id=?").run(owner, reviewedAt, 'Одобрено прямым уточнением владельца MetricHit от 01.09.2026; заменяет редакцию 3.', reviewedAt, candidateId);
    assertFields(database.prepare('SELECT * FROM memory_candidates WHERE id=?').get(candidateId), { type: 'editorial_rule', semantic_key: semanticKey, title, content: candidateContent, data_json: candidateData, source_id: sourceId, status: 'approved', reviewed_by: owner, reviewed_at: reviewedAt }, 'approved-core target-query policy candidate');
    assertFields(database.prepare('SELECT * FROM documents WHERE id=?').get(documentId), { content: documentContent, data_json: metadata, source_id: sourceId, version: 1 }, 'approved-core target-query policy document');
    database.exec('COMMIT');
    return { databasePath, created, sourceId, documentId, versionId, candidateId };
  } catch (error) { database.exec('ROLLBACK'); throw error; } finally { database.close(); }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) console.log(`Applied approved-core target-query policy: ${JSON.stringify(applyPublicEditorialApprovedCoreTargetQueries(process.argv[2] ? resolve(process.argv[2]) : defaultDatabasePath))}`);

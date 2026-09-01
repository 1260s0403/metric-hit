import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabasePath = join(repositoryRoot, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/public-editorial-semantic-core-policy-2026-09-01.md';
const owner = 'owner';
const reviewedAt = '2026-09-01T00:00:00.000Z';
const semanticKey = 'content.public_editorial_semantic_core_policy';

function stableUuid(key) {
  const hex = createHash('sha256').update(`metrichit-public-editorial-semantic-core:${key}`).digest('hex');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
}

function assertFields(row, expected, label) {
  if (!row) throw new Error(`Missing ${label}`);
  for (const [column, value] of Object.entries(expected)) if (row[column] !== value) throw new Error(`${label}.${column} differs`);
}

export function applyPublicEditorialSemanticCorePolicy(databasePath = defaultDatabasePath) {
  const bytes = readFileSync(join(repositoryRoot, decisionPath));
  const documentContent = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  const title = 'Семантическое ядро для всех новых публичных постов и статей';
  const candidateContent = 'Каждый новый публичный пост или статья MetricHit для VK, Telegram, TenChat, статейных площадок и будущих открытых редакционных каналов начинается с выбора одного компактного не-навигационного кластера из утверждённого семантического ядра из 145 запросов. Execution card фиксирует кластер, один основной целевой запрос, пользовательский интент и площадку. Основной запрос естественно расположен в H1 статьи либо в заголовке или первом абзаце социального поста; переоптимизация не допускается. Материал раскрывает один выбранный интент и не смешивает несвязанные кластеры; брендовые и навигационные варианты исключены, а геокандидат требует предварительного подтверждения спроса. Delivery validation подтверждает эти факты до готовности нового черновика. Уже опубликованный архив не меняется.';
  const candidateData = JSON.stringify({
    applies_to: ['new_public_posts', 'new_public_articles'],
    platforms: ['vk', 'telegram', 'tenchat', 'article_platforms', 'future_public_editorial_channels'],
    semantic_core: { keyword_count: 145, cluster: 'one_compact_non_navigational_cluster', brand_and_navigation_excluded: true, geo_candidates_require_prior_demand_verification: true },
    execution_card: ['selected_cluster', 'primary_target_query', 'user_intent', 'platform'],
    primary_query_placement: { article: ['h1'], social_post: ['headline', 'opening_paragraph'], natural: true, keyword_stuffing_prohibited: true },
    content_scope: { serves_one_selected_intent: true, unrelated_clusters_mixed: false },
    delivery_validation: ['semantic_cluster_selection', 'primary_query_prominence', 'single_cluster_intent', 'geo_demand_verification'],
    exceptions: ['no_retroactive_change_to_existing_published_archive'],
    evidence: { path: decisionPath },
  });
  const metadata = JSON.stringify({
    path: decisionPath,
    bytes: bytes.length,
    sha256: createHash('sha256').update(bytes).digest('hex'),
    encoding: 'utf-8',
    authority: 'direct_owner_confirmation',
    decision_date: '2026-09-01',
  });
  const sourceId = stableUuid(`source:${decisionPath}`);
  const documentId = stableUuid(`document:${decisionPath}`);
  const versionId = stableUuid(`version:${decisionPath}:1`);
  const candidateId = stableUuid(`candidate:${semanticKey}`);
  const database = new DatabaseSync(databasePath);
  const created = { sources: 0, documents: 0, versions: 0, candidates: 0 };
  database.exec('PRAGMA foreign_keys = ON; BEGIN IMMEDIATE;');
  try {
    const duplicate = database.prepare("SELECT id FROM memory_candidates WHERE semantic_key=? AND status IN ('pending','approved') AND id<>?").get(semanticKey, candidateId);
    if (duplicate) throw new Error('Semantic duplicate blocks public editorial semantic-core policy');
    const conflict = database.prepare("SELECT id FROM memory_conflicts WHERE status='open' AND (candidate_id=? OR existing_memory_item_id IN (SELECT id FROM memory_items WHERE semantic_key=?))").get(candidateId, semanticKey);
    if (conflict) throw new Error('Open memory conflict blocks public editorial semantic-core policy');
    created.sources += Number(database.prepare("INSERT OR IGNORE INTO sources (id,type,title,content,data_json,status,author,valid_at,access_level) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, '2026-09-01', 'internal')").run(sourceId, title, `Repository file: ${decisionPath}`, metadata, owner).changes);
    created.documents += Number(database.prepare("INSERT OR IGNORE INTO documents (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-09-01', 'internal', 1)").run(documentId, title, documentContent, metadata, sourceId, owner).changes);
    created.versions += Number(database.prepare("INSERT OR IGNORE INTO document_versions (id,document_id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-09-01', 'internal', 1)").run(versionId, documentId, title, documentContent, metadata, sourceId, owner).changes);
    created.candidates += Number(database.prepare("INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'editorial_rule', ?, ?, ?, ?, 'pending', ?, ?, '2026-09-01', 'internal', 1)").run(candidateId, semanticKey, title, candidateContent, candidateData, sourceId, owner).changes);
    if (database.prepare('SELECT status FROM memory_candidates WHERE id=?').get(candidateId)?.status === 'pending') {
      database.prepare("UPDATE memory_candidates SET status='approved', reviewed_by=?, reviewed_at=?, review_note=?, updated_at=?, version=version+1 WHERE id=?").run(owner, reviewedAt, 'Одобрено прямым решением владельца MetricHit от 01.09.2026.', reviewedAt, candidateId);
    }
    assertFields(database.prepare('SELECT * FROM memory_candidates WHERE id=?').get(candidateId), { type: 'editorial_rule', semantic_key: semanticKey, title, content: candidateContent, data_json: candidateData, source_id: sourceId, status: 'approved', reviewed_by: owner, reviewed_at: reviewedAt }, 'public editorial semantic-core policy candidate');
    assertFields(database.prepare('SELECT * FROM documents WHERE id=?').get(documentId), { content: documentContent, data_json: metadata, source_id: sourceId, version: 1 }, 'public editorial semantic-core policy document');
    database.exec('COMMIT');
    return { databasePath, created, sourceId, documentId, versionId, candidateId };
  } catch (error) {
    database.exec('ROLLBACK');
    throw error;
  } finally {
    database.close();
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) console.log(`Applied public editorial semantic-core policy: ${JSON.stringify(applyPublicEditorialSemanticCorePolicy(process.argv[2] ? resolve(process.argv[2]) : defaultDatabasePath))}`);

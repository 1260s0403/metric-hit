import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabasePath = join(repositoryRoot, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/public-editorial-target-query-volume-ladder-2026-09-01.md';
const owner = 'owner';
const reviewedAt = '2026-09-01T00:00:00.000Z';
const semanticKey = 'content.public_editorial_target_query_volume_ladder_policy';

function stableUuid(key) {
  const hex = createHash('sha256').update(`metrichit-public-editorial-target-query-volume-ladder:${key}`).digest('hex');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
}

function assertFields(row, expected, label) {
  if (!row) throw new Error(`Missing ${label}`);
  for (const [column, value] of Object.entries(expected)) if (row[column] !== value) throw new Error(`${label}.${column} differs`);
}

export function applyPublicEditorialTargetQueryVolumeLadder(databasePath = defaultDatabasePath) {
  const bytes = readFileSync(join(repositoryRoot, decisionPath));
  const documentContent = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  const title = 'Количество целевых запросов по объёму публичного материала вне Telegram';
  const candidateContent = 'Каждый новый публичный пост или статья MetricHit вне Telegram использует уникальные точные целевые запросы из утверждённого не-навигационного ядра из 145 запросов в зависимости от объёма основного текста: 1 800–2 800 знаков — 8–12 запросов; 2 801–5 000 — 10–16; 5 001–7 000 — 14–20; 7 001–9 000 — 18–26. Основной запрос входит в число, находится в заголовке и первом абзаце; каждый вторичный естественно присутствует в основном тексте хотя бы раз. Для текста короче 1 800 или длиннее 9 000 знаков delivery QA фиксирует обоснование количества без выдумывания порогов. Сохраняются один интент, один либо несколько документированно смежных кластеров, точные записи ядра, отсутствие повторов и keyword stuffing, запрет выдуманных синонимов/LSI/геовариантов и geo demand gate. Telegram полностью исключён; архив, существующие черновики и публикации не меняются.';
  const candidateData = JSON.stringify({
    revision: 1,
    applies_to: ['new_public_posts', 'new_public_articles'],
    platforms: ['vk', 'tenchat', 'article_platforms', 'future_public_editorial_channels'],
    excluded_platforms: ['telegram'],
    target_query_count: {
      unique_only: true,
      primary_included: true,
      required_by_body_character_count: [
        { minimum_characters: 1800, maximum_characters: 2800, minimum_queries: 8, maximum_queries: 12 },
        { minimum_characters: 2801, maximum_characters: 5000, minimum_queries: 10, maximum_queries: 16 },
        { minimum_characters: 5001, maximum_characters: 7000, minimum_queries: 14, maximum_queries: 20 },
        { minimum_characters: 7001, maximum_characters: 9000, minimum_queries: 18, maximum_queries: 26 },
      ],
      outside_defined_bands_requires_documented_rationale: true,
    },
    placement: { primary: ['headline', 'opening_paragraph'], every_secondary_natural_in_body_at_least_once: true },
    preserved_requirements: ['one_user_intent', 'one_or_documented_adjacent_clusters', 'verbatim_approved_core_only', 'no_duplicates', 'no_invented_synonyms_lsi_or_geo_targets', 'geo_demand_gate', 'no_keyword_stuffing'],
    execution_card: ['primary_target_query', 'secondary_target_queries', 'selected_clusters', 'adjacent_cluster_rationale', 'user_intent', 'platform', 'format', 'core_reference'],
    delivery_validation: ['target_query_volume_ladder'],
    exceptions: ['telegram_exempt', 'no_retroactive_change_to_existing_published_archive_or_drafts'],
    evidence: { path: decisionPath },
  });
  const metadata = JSON.stringify({ path: decisionPath, bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex'), encoding: 'utf-8', authority: 'direct_owner_confirmation', decision_date: '2026-09-01', revision: 1 });
  const sourceId = stableUuid(`source:${decisionPath}`);
  const documentId = stableUuid(`document:${decisionPath}`);
  const versionId = stableUuid(`version:${decisionPath}:1`);
  const candidateId = stableUuid(`candidate:${semanticKey}:1`);
  const database = new DatabaseSync(databasePath);
  const created = { sources: 0, documents: 0, versions: 0, candidates: 0 };
  database.exec('PRAGMA foreign_keys = ON; BEGIN IMMEDIATE;');
  try {
    const duplicate = database.prepare("SELECT id FROM memory_candidates WHERE semantic_key=? AND status IN ('pending','approved') AND id<>?").get(semanticKey, candidateId);
    if (duplicate) throw new Error('Semantic duplicate blocks public editorial target-query volume ladder');
    const conflict = database.prepare("SELECT id FROM memory_conflicts WHERE status='open' AND (candidate_id=? OR existing_memory_item_id IN (SELECT id FROM memory_items WHERE semantic_key=?))").get(candidateId, semanticKey);
    if (conflict) throw new Error('Open memory conflict blocks public editorial target-query volume ladder');
    created.sources += Number(database.prepare("INSERT OR IGNORE INTO sources (id,type,title,content,data_json,status,author,valid_at,access_level) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, '2026-09-01', 'internal')").run(sourceId, title, `Repository file: ${decisionPath}`, metadata, owner).changes);
    created.documents += Number(database.prepare("INSERT OR IGNORE INTO documents (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-09-01', 'internal', 1)").run(documentId, title, documentContent, metadata, sourceId, owner).changes);
    created.versions += Number(database.prepare("INSERT OR IGNORE INTO document_versions (id,document_id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-09-01', 'internal', 1)").run(versionId, documentId, title, documentContent, metadata, sourceId, owner).changes);
    created.candidates += Number(database.prepare("INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'editorial_rule', ?, ?, ?, ?, 'pending', ?, ?, '2026-09-01', 'internal', 1)").run(candidateId, semanticKey, title, candidateContent, candidateData, sourceId, owner).changes);
    if (database.prepare('SELECT status FROM memory_candidates WHERE id=?').get(candidateId)?.status === 'pending') database.prepare("UPDATE memory_candidates SET status='approved', reviewed_by=?, reviewed_at=?, review_note=?, updated_at=?, version=version+1 WHERE id=?").run(owner, reviewedAt, 'Одобрено прямым указанием владельца MetricHit от 01.09.2026.', reviewedAt, candidateId);
    assertFields(database.prepare('SELECT * FROM memory_candidates WHERE id=?').get(candidateId), { type: 'editorial_rule', semantic_key: semanticKey, title, content: candidateContent, data_json: candidateData, source_id: sourceId, status: 'approved', reviewed_by: owner, reviewed_at: reviewedAt }, 'target-query volume ladder candidate');
    assertFields(database.prepare('SELECT * FROM documents WHERE id=?').get(documentId), { content: documentContent, data_json: metadata, source_id: sourceId, version: 1 }, 'target-query volume ladder document');
    database.exec('COMMIT');
    return { databasePath, created, sourceId, documentId, versionId, candidateId };
  } catch (error) { database.exec('ROLLBACK'); throw error; } finally { database.close(); }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) console.log(`Applied public editorial target-query volume ladder: ${JSON.stringify(applyPublicEditorialTargetQueryVolumeLadder(process.argv[2] ? resolve(process.argv[2]) : defaultDatabasePath))}`);

import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabasePath = join(repositoryRoot, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/public-editorial-indexation-pf-policy-2026-09-01.md';
const owner = 'owner';
const reviewedAt = '2026-09-01T00:00:00.000Z';
const semanticKey = 'content.public_editorial_yandex_indexation_pf_target_policy';
const revision = 1;

function stableUuid(key) {
  const hex = createHash('sha256').update(`metrichit-public-editorial-indexation-pf:${key}`).digest('hex');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
}

function assertFields(row, expected, label) {
  if (!row) throw new Error(`Missing ${label}`);
  for (const [column, value] of Object.entries(expected)) if (row[column] !== value) throw new Error(`${label}.${column} differs`);
}

export function applyPublicEditorialIndexationPfPolicy(databasePath = defaultDatabasePath) {
  const bytes = readFileSync(join(repositoryRoot, decisionPath));
  const documentContent = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  const title = 'Индексация Яндекса и post-indexation PF-target для публичных материалов вне Telegram';
  const candidateContent = 'Для каждого нового публичного поста или статьи MetricHit вне Telegram главная редакционная цель — попасть в индекс Яндекса по выбранным утверждённым не-навигационным запросам одного кластера либо нескольких документированно смежных кластеров при едином пользовательском интенте. Execution card фиксирует только SEO-цель индексации; до публикации и delivery не требуют и не выполняют проверку индексируемости, находимости, URL, статуса или доказательства индексации свежего материала. Только после независимой фактической проверки индексации опубликованный материал может рассматриваться для отдельной owner-approved ПФ-кампании с указанными материалом/URL, бюджетом и scope. Правило не запускает кампанию, не разрешает публикацию, расходы или доступ к аккаунту. Telegram полностью исключён из этого правила. Опубликованный архив и существующие черновики не меняются.';
  const candidateData = JSON.stringify({
    revision,
    priority: 'highest_editorial_objective_for_non_telegram_public_materials',
    applies_to: ['new_public_posts', 'new_public_articles'],
    platforms: ['vk', 'tenchat', 'article_platforms', 'future_public_editorial_channels'],
    excluded_platforms: ['telegram'],
    yandex_indexation_objective: { required: true, selected_semantic_core_query_and_adjacent_clusters_allowed: true },
    execution_card: ['seo_indexation_objective'],
    delivery_validation: ['semantic_cluster_selection', 'primary_query_prominence', 'adjacent_clusters_one_intent'],
    prohibited_pre_delivery_checks: ['indexability', 'retrievability', 'target_url_status', 'indexation_status', 'indexation_evidence'],
    post_indexation_pf_target: { eligible_only_after_verified_yandex_indexation: true, eligible_only_after_independently_verified_yandex_indexation: true, campaign_automatic_authorization: false, separate_owner_approval_required_fields: ['material_or_url', 'budget', 'scope'] },
    external_actions_prohibited_without_separate_owner_approval: ['publication', 'pf_campaign_launch', 'spending', 'account_access'],
    exceptions: ['telegram_exempt_from_indexation_pf_target_gate', 'no_retroactive_change_to_existing_published_archive_or_drafts'],
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
    if (competing.length) throw new Error('Semantic duplicate or evolution blocks public editorial Yandex indexation/PF-target policy');
    const conflict = database.prepare("SELECT id FROM memory_conflicts WHERE status='open' AND (candidate_id=? OR existing_memory_item_id IN (SELECT id FROM memory_items WHERE semantic_key=?))").get(candidateId, semanticKey);
    if (conflict) throw new Error('Open memory conflict blocks public editorial Yandex indexation/PF-target policy');
    created.sources += Number(database.prepare("INSERT OR IGNORE INTO sources (id,type,title,content,data_json,status,author,valid_at,access_level) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, '2026-09-01', 'internal')").run(sourceId, title, `Repository file: ${decisionPath}`, metadata, owner).changes);
    created.documents += Number(database.prepare("INSERT OR IGNORE INTO documents (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-09-01', 'internal', 1)").run(documentId, title, documentContent, metadata, sourceId, owner).changes);
    created.versions += Number(database.prepare("INSERT OR IGNORE INTO document_versions (id,document_id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-09-01', 'internal', 1)").run(versionId, documentId, title, documentContent, metadata, sourceId, owner).changes);
    created.candidates += Number(database.prepare("INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'editorial_rule', ?, ?, ?, ?, 'pending', ?, ?, '2026-09-01', 'internal', 1)").run(candidateId, semanticKey, title, candidateContent, candidateData, sourceId, owner).changes);
    if (database.prepare('SELECT status FROM memory_candidates WHERE id=?').get(candidateId)?.status === 'pending') database.prepare("UPDATE memory_candidates SET status='approved', reviewed_by=?, reviewed_at=?, review_note=?, updated_at=?, version=version+1 WHERE id=?").run(owner, reviewedAt, 'Одобрено прямым уточнением владельца MetricHit от 01.09.2026; заменяет редакцию 2.', reviewedAt, candidateId);
    assertFields(database.prepare('SELECT * FROM memory_candidates WHERE id=?').get(candidateId), { type: 'editorial_rule', semantic_key: semanticKey, title, content: candidateContent, data_json: candidateData, source_id: sourceId, status: 'approved', reviewed_by: owner, reviewed_at: reviewedAt }, 'public editorial Yandex indexation/PF-target policy candidate');
    assertFields(database.prepare('SELECT * FROM documents WHERE id=?').get(documentId), { content: documentContent, data_json: metadata, source_id: sourceId, version: 1 }, 'public editorial Yandex indexation/PF-target policy document');
    database.exec('COMMIT');
    return { databasePath, created, sourceId, documentId, versionId, candidateId };
  } catch (error) { database.exec('ROLLBACK'); throw error; } finally { database.close(); }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) console.log(`Applied public editorial Yandex indexation/PF-target policy: ${JSON.stringify(applyPublicEditorialIndexationPfPolicy(process.argv[2] ? resolve(process.argv[2]) : defaultDatabasePath))}`);

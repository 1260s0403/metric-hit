import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const defaultDatabasePath = join(repositoryRoot, 'data', 'database', 'metrichit.db');
const decisionPath = 'knowledge/decisions/editorial-publication-policy-and-timeweb-draft-2026-08-29.md';
const owner = 'owner';
const reviewedAt = '2026-08-29T00:00:00.000Z';

function stableUuid(key) {
  const hex = createHash('sha256').update(`metrichit-editorial-publication-policy:${key}`).digest('hex');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
}

function assertFields(row, expected, label) {
  if (!row) throw new Error(`Missing ${label}`);
  for (const [column, value] of Object.entries(expected)) if (row[column] !== value) throw new Error(`${label}.${column} differs`);
}

function approve(database, candidateId) {
  const candidate = database.prepare('SELECT * FROM memory_candidates WHERE id=?').get(candidateId);
  if (candidate.status === 'pending') database.prepare("UPDATE memory_candidates SET status='approved', reviewed_by=?, reviewed_at=?, review_note=?, updated_at=?, version=version+1 WHERE id=?").run(owner, reviewedAt, 'Одобрено прямым решением владельца MetricHit от 29.08.2026.', reviewedAt, candidateId);
}

export function applyEditorialPublicationPolicyAndTimewebDraft(databasePath = defaultDatabasePath) {
  const bytes = readFileSync(join(repositoryRoot, decisionPath));
  const documentContent = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  const policyTitle = 'Правила подготовки статей MetricHit';
  const policyContent = 'Статьи MetricHit оригинальны, сохраняют подтверждённые кейсы и цифры, естественно используют утверждённые ключи и содержат не менее 9 000 знаков содержательного текста. Тарифная сетка, пороги пополнения и таблицы тарифов запрещены; допустимо контекстное упоминание «от 0,15 ₽ за клик». Служебные SEO-метки не публикуются. В статье четыре естественные ссылки на https://go.mtrhit.ru/: в начале, две внутри и в финале/CTA. Нужны две оригинальные эффектные иллюстрации, соответствующие деловой или технической площадке. Заявка на авторство описывает регулярное экспертное направление MetricHit, а не одну статью.';
  const draftTitle = 'Черновик Timeweb Cloud: «Сервис накрутки ПФ: как SEO-команде выстроить управляемое продвижение в Яндексе»';
  const draftContent = 'Материал сохранён как article в канале articles для Timeweb Cloud. Статус: draft/unpublished; публичный URL отсутствует. Материал не публиковался и не является результатом.';
  const registryTitle = 'Текущее состояние editorial-реестра MetricHit';
  const registryContent = 'Историческая запись о пустых реестрах редакции больше не описывает текущее состояние: зарегистрирован один article-материал для Timeweb Cloud со статусом draft. Публикаций и результатов в реестре нет; внешний URL отсутствует.';
  const metadata = JSON.stringify({ path: decisionPath, bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex'), encoding: 'utf-8', authority: 'direct_owner_confirmation', decision_date: '2026-08-29' });
  const policyData = JSON.stringify({ applies_to: ['articles', 'author_applications'], minimum_content_characters: 9000, prohibited: ['tariff_grid', 'topup_thresholds', 'tariff_tables', 'service_seo_labels', 'bare_urls', 'link_spam', 'copied_or_mechanically_reordered_text'], permitted_minimum_price: 'от 0,15 ₽ за клик', landing: 'https://go.mtrhit.ru/', landing_link_distribution: ['beginning', 'body_1', 'body_2', 'final_cta'], required_original_illustrations: 2, evidence: { path: decisionPath } });
  const draftData = JSON.stringify({ channel: 'articles', platform: 'Timeweb Cloud', publication_status: 'draft', public_url: null, final_article_path: 'work/articles/drafts/2026-08-29-timeweb-cloud-pf-service-selection.md', evidence: { path: decisionPath } });
  const registryData = JSON.stringify({ articles_materials: 1, articles_drafts: 1, articles_publications: 0, articles_results: 0, evidence: { path: decisionPath } });
  const sourceId = stableUuid(`source:${decisionPath}`);
  const documentId = stableUuid(`document:${decisionPath}`);
  const versionId = stableUuid(`version:${decisionPath}:1`);
  const policyId = stableUuid('candidate:content.editorial_article_preparation_policy');
  const draftId = stableUuid('candidate:publication.timeweb_cloud_draft_2026_08_29');
  const registryId = stableUuid('candidate:editorial.registry_current_state');
  const database = new DatabaseSync(databasePath);
  const created = { sources: 0, documents: 0, versions: 0, candidates: 0 };
  database.exec('PRAGMA foreign_keys = ON; BEGIN IMMEDIATE;');
  try {
    created.sources += Number(database.prepare("INSERT OR IGNORE INTO sources (id,type,title,content,data_json,status,author,valid_at,access_level) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, '2026-08-29', 'internal')").run(sourceId, policyTitle, `Repository file: ${decisionPath}`, metadata, owner).changes);
    created.documents += Number(database.prepare("INSERT OR IGNORE INTO documents (id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-29', 'internal', 1)").run(documentId, policyTitle, documentContent, metadata, sourceId, owner).changes);
    created.versions += Number(database.prepare("INSERT OR IGNORE INTO document_versions (id,document_id,type,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, ?, 'owner_decision', ?, ?, ?, 'active', ?, ?, '2026-08-29', 'internal', 1)").run(versionId, documentId, policyTitle, documentContent, metadata, sourceId, owner).changes);
    created.candidates += Number(database.prepare("INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'editorial_rule', 'content.editorial_article_preparation_policy', ?, ?, ?, 'pending', ?, ?, '2026-08-29', 'internal', 1)").run(policyId, policyTitle, policyContent, policyData, sourceId, owner).changes);
    created.candidates += Number(database.prepare("INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'publication_state', 'publication.timeweb_cloud_draft_2026_08_29', ?, ?, ?, 'pending', ?, ?, '2026-08-29', 'internal', 1)").run(draftId, draftTitle, draftContent, draftData, sourceId, owner).changes);
    created.candidates += Number(database.prepare("INSERT OR IGNORE INTO memory_candidates (id,type,semantic_key,title,content,data_json,status,source_id,author,valid_at,access_level,version) VALUES (?, 'decision', 'editorial.registry_current_state', ?, ?, ?, 'pending', ?, ?, '2026-08-29', 'internal', 1)").run(registryId, registryTitle, registryContent, registryData, sourceId, owner).changes);
    approve(database, policyId);
    approve(database, draftId);
    approve(database, registryId);
    assertFields(database.prepare('SELECT * FROM memory_candidates WHERE id=?').get(policyId), { type: 'editorial_rule', semantic_key: 'content.editorial_article_preparation_policy', title: policyTitle, content: policyContent, data_json: policyData, source_id: sourceId, status: 'approved', reviewed_by: owner, reviewed_at: reviewedAt }, 'editorial article policy');
    assertFields(database.prepare('SELECT * FROM memory_candidates WHERE id=?').get(draftId), { type: 'publication_state', semantic_key: 'publication.timeweb_cloud_draft_2026_08_29', title: draftTitle, content: draftContent, data_json: draftData, source_id: sourceId, status: 'approved', reviewed_by: owner, reviewed_at: reviewedAt }, 'Timeweb draft state');
    assertFields(database.prepare('SELECT * FROM memory_candidates WHERE id=?').get(registryId), { type: 'decision', semantic_key: 'editorial.registry_current_state', title: registryTitle, content: registryContent, data_json: registryData, source_id: sourceId, status: 'approved', reviewed_by: owner, reviewed_at: reviewedAt }, 'editorial registry current state');
    database.exec('COMMIT');
    return { databasePath, created, sourceId, documentId, versionId, policyId, draftId, registryId };
  } catch (error) {
    database.exec('ROLLBACK');
    throw error;
  } finally {
    database.close();
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) console.log(`Applied editorial publication policy and Timeweb draft: ${JSON.stringify(applyEditorialPublicationPolicyAndTimewebDraft(process.argv[2] ? resolve(process.argv[2]) : defaultDatabasePath))}`);
